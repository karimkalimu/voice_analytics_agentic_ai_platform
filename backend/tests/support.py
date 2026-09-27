import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import analysis, database, prompts, storage
from app.main import app
from app.routes import files


def model_response(content, refusal=None, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, refusal=refusal), finish_reason=finish_reason,
    )])


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        storage_root = self.root / "storage"
        for directory in ("uploads", "transcripts", "users"):
            (storage_root / directory).mkdir(parents=True)
        shutil.copytree(prompts.PROMPT_DIR, self.root / "prompts")
        for module, name, value in (
            (storage, "BASE_DIR", self.root),
            (storage, "STORAGE_DIR", storage_root),
            (storage, "UPLOAD_DIR", storage_root / "uploads"),
            (storage, "LEGACY_TRANSCRIPT_DIR", storage_root / "transcripts"),
            (storage, "USER_DIR", storage_root / "users"),
            (database, "DB_PATH", self.root / "app.db"),
            (prompts, "PROMPT_DIR", self.root / "prompts"),
        ):
            active = patch.object(module, name, value)
            active.start()
            self.addCleanup(active.stop)
        database.init_db()
        self.uid = "user-a"
        app.dependency_overrides[files.current_uid] = lambda: self.uid
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app, client=("127.0.0.1", 50000))
        self.addCleanup(self.client.close)

    def make_file(self, user_id="user-a", upload_id="upload1", audio=b"audio", transcript="An engineer discussed software.",
                  options=None, config=None):
        alias = storage.upload_alias(upload_id)
        alias.write_bytes(audio)
        Path(f"{alias}.info").write_text("{}")
        file_id = database.register_file(user_id, upload_id, "sample.wav", storage.relative_path(alias),
                                         options, config)
        row = database.get_file(file_id)
        database.update_storage_path(file_id, storage.finalize_audio(row))
        database.set_audio_hash(file_id, hashlib.sha256(audio).hexdigest())
        if transcript is not None:
            row = database.get_file(file_id)
            value = storage.write_transcript(row, transcript)
            database.update_transcription(file_id, "transcribed", value, "en", duration_sec=2, version="1")
            database.save_analysis(file_id, "An engineer discussed software.", json.dumps({
                "professional_topics": ["software"], "personal_topics": [], "upcoming_events": [],
            }), analysis.current_analysis_version())
            if options:
                database.update_layer2_status(file_id, "completed")
        return file_id

    def update_row(self, file_id, **values):
        columns = ", ".join(f"{name} = ?" for name in values)
        with closing(sqlite3.connect(database.DB_PATH)) as db, db:
            db.execute(f"UPDATE files SET {columns} WHERE id = ?", (*values.values(), file_id))
