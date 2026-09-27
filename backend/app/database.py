import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from app import storage

BASE_DIR = storage.BASE_DIR
DB_PATH = BASE_DIR / "app.db"
ACTIVE_STATUSES = ("uploaded", "validating_audio", "transcribing", "validating_transcript",
                   "transcribed", "analyzing", "analyzing_layer2")
ACTIVE_LIMIT_MESSAGE = "Too many files are currently processing. Please wait for an existing file to finish."
AGGREGATE_JOBS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS aggregate_jobs (
        id INTEGER PRIMARY KEY,
        user_id TEXT,
        request_json TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""


def connect_db():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    with closing(connect_db()) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                upload_id TEXT NOT NULL UNIQUE,
                original_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                status TEXT NOT NULL,
                transcript_path TEXT,
                language TEXT,
                error TEXT,
                rejection_code TEXT,
                guardrail_version TEXT,
                duration_sec REAL,
                summary TEXT,
                taxonomy TEXT,
                audio_sha256 TEXT,
                transcription_version TEXT,
                analysis_version TEXT,
                layer2_options TEXT NOT NULL DEFAULT '[]',
                layer2_results TEXT NOT NULL DEFAULT '{}',
                layer2_version TEXT NOT NULL DEFAULT '{}',
                layer2_pending_options TEXT NOT NULL DEFAULT '[]',
                layer2_config TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute(AGGREGATE_JOBS_SCHEMA)
        aggregate_columns = {row[1]: row for row in db.execute("PRAGMA table_info(aggregate_jobs)")}
        if aggregate_columns["user_id"][3]:
            db.execute("ALTER TABLE aggregate_jobs RENAME TO aggregate_jobs_required_user")
            db.execute(AGGREGATE_JOBS_SCHEMA)
            db.execute("""INSERT INTO aggregate_jobs
                       (id, user_id, request_json, status, result_json, error, created_at, updated_at)
                       SELECT id, user_id, request_json, status, result_json, error, created_at, updated_at
                       FROM aggregate_jobs_required_user""")
            db.execute("DROP TABLE aggregate_jobs_required_user")
        columns = {row[1] for row in db.execute("PRAGMA table_info(files)")}
        for name, kind in (("transcript_path", "TEXT"), ("language", "TEXT"),
                           ("error", "TEXT"), ("rejection_code", "TEXT"),
                           ("guardrail_version", "TEXT"), ("duration_sec", "REAL"),
                           ("summary", "TEXT"), ("taxonomy", "TEXT"),
                           ("audio_sha256", "TEXT"), ("transcription_version", "TEXT"),
                           ("analysis_version", "TEXT"),
                           ("layer2_options", "TEXT NOT NULL DEFAULT '[]'"),
                           ("layer2_results", "TEXT NOT NULL DEFAULT '{}'"),
                           ("layer2_version", "TEXT NOT NULL DEFAULT '{}'"),
                           ("layer2_pending_options", "TEXT NOT NULL DEFAULT '[]'"),
                           ("layer2_config", "TEXT NOT NULL DEFAULT '{}'")):
            if name not in columns:
                db.execute(f"ALTER TABLE files ADD COLUMN {name} {kind}")
                if name == "layer2_pending_options":
                    db.execute("""UPDATE files SET layer2_pending_options = layer2_options
                               WHERE status = 'analyzing_layer2'""")
        db.execute("""UPDATE files SET status = 'rejected', rejection_code = 'unsupported_language',
                   error = 'This POC currently supports English speech only.'
                   WHERE status = 'unsupported_language'""")


def migrate_storage():
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        legacy_transcripts = set()
        for source in db.execute("SELECT * FROM files ORDER BY id").fetchall():
            row = dict(source)
            try:
                path = storage.finalize_audio(row)
                if path != row["storage_path"]:
                    db.execute("UPDATE files SET storage_path = ? WHERE id = ?", (path, row["id"]))
                    row["storage_path"] = path
            except (OSError, ValueError):
                logging.exception("Could not finalize audio for file %s", row["id"])
                db.execute("UPDATE files SET error = ? WHERE id = ?",
                           ("Uploaded audio could not be finalized.", row["id"]))
            if row["transcript_path"]:
                legacy_transcripts.add(row["transcript_path"])
                try:
                    path = storage.migrate_transcript(row)
                    if path != row["transcript_path"]:
                        db.execute("UPDATE files SET transcript_path = ? WHERE id = ?", (path, row["id"]))
                except (OSError, ValueError):
                    logging.exception("Could not migrate transcript for file %s", row["id"])
                    db.execute("UPDATE files SET error = ? WHERE id = ?",
                               ("Transcript file is unavailable.", row["id"]))
        db.commit()
        for value in legacy_transcripts:
            path = storage.LEGACY_TRANSCRIPT_DIR / Path(value).name
            if (value == storage.relative_path(path)
                    and not db.execute("SELECT 1 FROM files WHERE transcript_path = ?", (value,)).fetchone()):
                path.unlink(missing_ok=True)


def register_file(user_id: str, upload_id: str, original_name: str, storage_path: str,
                  layer2_options: list[str] | None = None, layer2_config: dict | None = None,
                  max_active_files: int | None = None, guardrail_version: str | None = None):
    with closing(connect_db()) as db:
        db.execute("BEGIN IMMEDIATE")
        active = 0
        if max_active_files is not None:
            placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
            active = db.execute(
                f"SELECT COUNT(*) FROM files WHERE user_id = ? AND status IN ({placeholders})",
                (user_id, *ACTIVE_STATUSES),
            ).fetchone()[0]
        rejected = max_active_files is not None and active >= max_active_files
        cursor = db.execute(
            """INSERT OR IGNORE INTO files
               (user_id, upload_id, original_name, storage_path, status,
                layer2_options, layer2_pending_options, layer2_config, rejection_code,
                error, guardrail_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, upload_id, original_name, storage_path,
             "rejected" if rejected else "uploaded",
             json.dumps(layer2_options or []), json.dumps(layer2_options or []),
             json.dumps(layer2_config or {}), "active_limit_exceeded" if rejected else None,
             ACTIVE_LIMIT_MESSAGE if rejected else None, guardrail_version),
        )
        db.commit()
        return cursor.lastrowid if cursor.rowcount else None


def get_file_by_upload_id(upload_id: str):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM files WHERE upload_id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None


def update_storage_path(file_id: int, path: str):
    with closing(connect_db()) as db, db:
        db.execute("UPDATE files SET storage_path = ? WHERE id = ?", (path, file_id))


def set_file_status_error(file_id: int, status: str, error: str):
    with closing(connect_db()) as db, db:
        db.execute("UPDATE files SET status = ?, error = ?, rejection_code = NULL WHERE id = ?",
                   (status, error, file_id))


def set_file_error(file_id: int, error: str):
    with closing(connect_db()) as db, db:
        db.execute("UPDATE files SET error = ? WHERE id = ?", (error, file_id))


def update_audio_validation(file_id: int, duration_sec: float | None, version: str):
    with closing(connect_db()) as db, db:
        db.execute("""UPDATE files SET status = 'validating_audio', duration_sec = ?,
                   guardrail_version = ?, rejection_code = NULL, error = NULL WHERE id = ?""",
                   (duration_sec, version, file_id))


def reject_file(file_id: int, rejection_code: str, error: str, version: str):
    with closing(connect_db()) as db, db:
        db.execute("""UPDATE files SET status = 'rejected', rejection_code = ?, error = ?,
                   guardrail_version = ? WHERE id = ?""",
                   (rejection_code, error, version, file_id))


def mark_transcript_validated(file_id: int, version: str):
    with closing(connect_db()) as db, db:
        db.execute("""UPDATE files SET status = 'transcribed', rejection_code = NULL,
                   error = NULL, guardrail_version = ? WHERE id = ?""", (version, file_id))


def update_transcription(file_id: int, status: str, transcript_path: str | None = None,
                         language: str | None = None, error: str | None = None,
                         duration_sec: float | None = None, version: str | None = None):
    with closing(connect_db()) as db, db:
        db.execute(
            """UPDATE files SET status = ?, transcript_path = ?, language = ?, error = ?,
               rejection_code = NULL, duration_sec = ?, transcription_version = ?
               WHERE id = ?""",
            (status, transcript_path, language, error, duration_sec, version, file_id),
        )


def update_analysis_status(file_id: int, status: str, error: str | None = None,
                           version: str | None = None):
    with closing(connect_db()) as db, db:
        db.execute("UPDATE files SET status = ?, error = ?, analysis_version = ? WHERE id = ?",
                   (status, error, version, file_id))


def save_analysis(file_id: int, summary: str, taxonomy: str, version: str):
    with closing(connect_db()) as db, db:
        db.execute(
            """UPDATE files SET status = CASE WHEN layer2_options = '[]' THEN 'completed'
               ELSE 'analyzing_layer2' END, summary = ?, taxonomy = ?,
               analysis_version = ?, error = NULL
               WHERE id = ?""",
            (summary, taxonomy, version, file_id),
        )


def get_file(file_id: int, user_id: str | None = None):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        if user_id is None:
            row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM files WHERE id = ? AND user_id = ?",
                             (file_id, user_id)).fetchone()
        return dict(row) if row else None


def recoverable_file_ids():
    with closing(connect_db()) as db:
        return [row[0] for row in db.execute(
            """SELECT id FROM files WHERE status IN
               ('uploaded', 'validating_audio', 'transcribing', 'validating_transcript',
                'transcribed', 'analyzing', 'analyzing_layer2') ORDER BY id"""
        )]


def unhashed_file_ids():
    with closing(connect_db()) as db:
        return [row[0] for row in db.execute(
            """SELECT id FROM files WHERE audio_sha256 IS NULL AND status IN
               ('completed', 'rejected', 'transcription_failed', 'analysis_failed',
                'layer2_failed') ORDER BY id"""
        )]


def set_audio_hash(file_id: int, digest: str):
    with closing(connect_db()) as db, db:
        db.execute("UPDATE files SET audio_sha256 = ? WHERE id = ?", (digest, file_id))


def reuse_transcription(file_id: int, user_id: str, digest: str, version: str):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            """SELECT * FROM files
               WHERE user_id = ? AND audio_sha256 = ? AND transcription_version = ? AND id != ?
               AND language IS NOT NULL AND duration_sec IS NOT NULL
               AND (transcript_path IS NOT NULL OR
                    (status = 'rejected' AND rejection_code = 'unsupported_language'))
               ORDER BY id DESC""",
            (user_id, digest, version, file_id),
        ).fetchall()
        for row in rows:
            if row["transcript_path"]:
                try:
                    path = storage.stored_transcript_path(dict(row))
                except ValueError:
                    continue
                if not path.is_file():
                    continue
            db.execute(
                """UPDATE files SET status = 'validating_transcript', transcript_path = ?,
                   language = ?, error = NULL, rejection_code = NULL,
                   transcription_version = ? WHERE id = ?""",
                (row["transcript_path"], row["language"], version, file_id),
            )
            db.commit()
            return dict(row)
        db.rollback()
        return None


def cached_analysis(user_id: str, digest: str, transcription_version: str | None,
                    analysis_version: str, file_id: int):
    if transcription_version is None:
        return None
    with closing(connect_db()) as db:
        row = db.execute(
            """SELECT summary, taxonomy FROM files
               WHERE user_id = ? AND audio_sha256 = ? AND transcription_version = ?
               AND analysis_version = ? AND id != ? AND status IN
               ('completed', 'analyzing_layer2', 'layer2_failed')
               AND summary IS NOT NULL AND taxonomy IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (user_id, digest, transcription_version, analysis_version, file_id),
        ).fetchone()
        return row


def save_layer2_result(file_id: int, option: str, result: dict, version: str):
    with closing(connect_db()) as db, db:
        row = db.execute("""SELECT layer2_results, layer2_version, layer2_pending_options
                          FROM files WHERE id = ?""", (file_id,)).fetchone()
        if row is None:
            return
        results = json.loads(row[0])
        versions = json.loads(row[1])
        results[option] = result
        versions[option] = version
        pending = json.loads(row[2])
        pending = [item for item in pending if item != option]
        db.execute("""UPDATE files SET layer2_results = ?, layer2_version = ?,
                   layer2_pending_options = ?, status = 'analyzing_layer2', error = NULL
                   WHERE id = ?""",
                   (json.dumps(results), json.dumps(versions), json.dumps(pending), file_id))


def cached_layer2_result(row: dict, option: str, version: str):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        query = """SELECT layer2_results, layer2_version FROM files
                   WHERE user_id = ? AND audio_sha256 = ? AND id != ?"""
        args = [row["user_id"], row["audio_sha256"], row["id"]]
        if option != "rms":
            query += " AND transcription_version = ?"
            args.append(row["transcription_version"])
        query += " ORDER BY id DESC"
        for source in db.execute(query, args):
            versions = json.loads(source["layer2_version"])
            results = json.loads(source["layer2_results"])
            if versions.get(option) == version and option in results:
                return results[option]
    return None


def update_layer2_status(file_id: int, status: str, error: str | None = None):
    with closing(connect_db()) as db, db:
        db.execute("""UPDATE files SET status = ?, error = ?,
                   layer2_pending_options = CASE WHEN ? = 'completed' THEN '[]'
                   ELSE layer2_pending_options END WHERE id = ?""",
                   (status, error, status, file_id))


def claim_layer2(file_id: int, user_id: str, options: list[str], config: dict,
                 versions: dict[str, str | None], transcript_path: str):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM files WHERE id = ? AND user_id = ?",
                         (file_id, user_id)).fetchone()
        if row is None:
            return "not_found"
        if row["status"] not in ("completed", "layer2_failed"):
            return "conflict"
        if (not row["transcript_path"] or row["transcript_path"] != transcript_path
                or row["summary"] is None or row["taxonomy"] is None):
            return "unavailable"
        try:
            path = storage.stored_transcript_path(dict(row))
        except ValueError:
            return "unavailable"
        if not path.is_file():
            return "unavailable"
        selected = json.loads(row["layer2_options"])
        stored_config = json.loads(row["layer2_config"])
        results = json.loads(row["layer2_results"])
        stored_versions = json.loads(row["layer2_version"])
        pending = [option for option in options
                   if option not in results or versions.get(option) is None
                   or stored_versions.get(option) != versions[option]]
        selected.extend(option for option in options if option not in selected)
        stored_config.update(config)
        if not pending:
            db.execute("UPDATE files SET layer2_options = ?, layer2_config = ? WHERE id = ?",
                       (json.dumps(selected), json.dumps(stored_config), file_id))
            db.commit()
            return "unchanged"
        db.execute("""UPDATE files SET layer2_options = ?, layer2_config = ?, layer2_pending_options = ?,
                   status = 'analyzing_layer2', error = NULL WHERE id = ?""",
                   (json.dumps(selected), json.dumps(stored_config), json.dumps(pending), file_id))
        db.commit()
        return "scheduled"


def delete_owned_file(file_id: int, user_id: str):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM files WHERE id = ? AND user_id = ?",
                         (file_id, user_id)).fetchone()
        if row is None:
            db.rollback()
            return None
        if row["status"] in ACTIVE_STATUSES:
            db.rollback()
            return False
        db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        delete_audio = not db.execute("SELECT 1 FROM files WHERE storage_path = ? LIMIT 1",
                                      (row["storage_path"],)).fetchone()
        delete_transcript = row["transcript_path"] and not db.execute(
            "SELECT 1 FROM files WHERE transcript_path = ? LIMIT 1", (row["transcript_path"],)
        ).fetchone()
        if delete_audio:
            storage.remove_audio(dict(row))
        if delete_transcript:
            storage.remove_transcript(dict(row))
        db.commit()
        return True


def list_files(user_id: str | None):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        if user_id is None:
            rows = db.execute("SELECT * FROM files ORDER BY created_at DESC, id DESC").fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM files WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def create_aggregate_job(user_id: str | None, request: dict):
    with closing(connect_db()) as db, db:
        cursor = db.execute(
            "INSERT INTO aggregate_jobs (user_id, request_json, status) VALUES (?, ?, 'queued')",
            (user_id, json.dumps(request)),
        )
        job_id = cursor.lastrowid
    return get_aggregate_job(job_id, user_id)


def get_aggregate_job(job_id: int, user_id: str | None = None):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        if user_id is None:
            row = db.execute("SELECT * FROM aggregate_jobs WHERE id = ?", (job_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM aggregate_jobs WHERE id = ? AND user_id = ?",
                             (job_id, user_id)).fetchone()
        return dict(row) if row else None


def list_aggregate_jobs(user_id: str | None = None):
    with closing(connect_db()) as db:
        db.row_factory = sqlite3.Row
        if user_id is None:
            rows = db.execute(
                "SELECT * FROM aggregate_jobs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM aggregate_jobs WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def update_aggregate_job(job_id: int, status: str, result: dict | None = None,
                         error: str | None = None):
    with closing(connect_db()) as db, db:
        db.execute(
            """UPDATE aggregate_jobs SET status = ?, result_json = ?, error = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, json.dumps(result) if result is not None else None, error, job_id),
        )


def recoverable_aggregate_job_ids():
    with closing(connect_db()) as db:
        return [row[0] for row in db.execute(
            "SELECT id FROM aggregate_jobs WHERE status IN ('queued', 'running') ORDER BY id"
        )]
