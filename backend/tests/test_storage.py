import json
import os
from pathlib import Path

from app import analysis, database, storage
from support import WorkspaceCase


class StorageTests(WorkspaceCase):
    def test_user_namespace_and_deletion(self):
        first = self.make_file(user_id="../user-a", upload_id="uploadA")
        second = self.make_file(user_id="user-b", upload_id="uploadB")
        row = database.get_file(first)
        audio = storage.stored_audio_path(row)
        transcript = storage.stored_transcript_path(row)
        alias = storage.upload_alias(row["upload_id"])
        self.assertEqual(audio, storage.final_audio_path(row))
        self.assertTrue(audio.is_file())
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), audio)
        self.assertTrue(transcript.is_file())
        self.assertNotIn("..", row["storage_path"])
        self.assertTrue(database.delete_owned_file(first, "../user-a"))
        self.assertFalse(audio.exists())
        self.assertFalse(alias.is_symlink())
        self.assertFalse(Path(f"{alias}.info").exists())
        self.assertFalse(transcript.exists())
        self.assertTrue(storage.stored_audio_path(database.get_file(second)).is_file())

    def test_legacy_shared_transcript_migration(self):
        legacy = storage.LEGACY_TRANSCRIPT_DIR / "1.txt"
        legacy.write_text("Shared transcript", encoding="utf-8")
        file_ids = []
        for upload_id in ("legacyA", "legacyB"):
            alias = storage.upload_alias(upload_id)
            alias.write_bytes(upload_id.encode())
            file_id = database.register_file("user-a", upload_id, "sample.wav", storage.relative_path(alias))
            database.update_transcription(file_id, "transcribed", storage.relative_path(legacy), "en", duration_sec=1, version="1")
            database.save_analysis(file_id, "Shared transcript", json.dumps({
                "professional_topics": [], "personal_topics": [], "upcoming_events": [],
            }), analysis.current_analysis_version())
            file_ids.append(file_id)
        database.migrate_storage()
        rows = [database.get_file(file_id) for file_id in file_ids]
        self.assertEqual(rows[0]["transcript_path"], rows[1]["transcript_path"])
        self.assertTrue(storage.stored_transcript_path(rows[0]).is_file())
        self.assertFalse(legacy.exists())
        self.assertTrue(all(storage.stored_audio_path(row).is_file() for row in rows))
        shared = storage.stored_transcript_path(rows[0])
        database.delete_owned_file(file_ids[0], "user-a")
        self.assertTrue(shared.is_file())
        database.delete_owned_file(file_ids[1], "user-a")
        self.assertFalse(shared.exists())

    def test_finalization_recovers_hardlink_before_alias_swap(self):
        alias = storage.upload_alias("crashA")
        alias.write_bytes(b"audio")
        file_id = database.register_file("user-a", "crashA", "sample.wav", storage.relative_path(alias))
        row = database.get_file(file_id)
        final = storage.final_audio_path(row)
        final.parent.mkdir(parents=True)
        os.link(alias, final)
        self.assertEqual(storage.finalize_audio(row), storage.relative_path(final))
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), final)
