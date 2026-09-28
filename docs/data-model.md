# Data model and storage keys

Firebase supplies the verified `user_id`. Every user-facing query is scoped to that ID. SQLite provides logical POC partitioning; a production database can use the same value as its partition key.

## SQLite schema

```sql
CREATE TABLE files (
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
);

CREATE TABLE aggregate_jobs (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

JSON fields are validated before storage. Unique `upload_id` makes completion hooks idempotent. Hash and version fields prevent reuse across users or incompatible processing configurations. Aggregate jobs persist their validated request, result, error, and recovery state.

## Lifecycle

```text
uploaded -> validating_audio -> transcribing -> validating_transcript
         -> transcribed -> analyzing -> analyzing_layer2 -> completed
```

Policy rejection ends as `rejected`. Operational failures use `transcription_failed`, `analysis_failed`, or `layer2_failed`. Aggregate jobs use `queued`, `running`, `completed`, and `failed`.

## POC filesystem

```text
backend/storage/
  uploads/<tusd-upload-id>[.info]
  users/<sha256-of-user-id>/audio/<file-id>/audio
  users/<sha256-of-user-id>/transcripts/<source-file-id>.txt
```

The verified UID is hashed before use as a directory. Completed upload bytes move into the user directory while tusd retains its resumable-upload metadata.

## Object-storage key design

```text
users/<sha256-of-user-id>/audio/<file-id>/audio
users/<sha256-of-user-id>/transcripts/<source-file-id>.txt
```

Production access should go through authorized backend operations or short-lived signed URLs. Database rows store the owning `user_id` and object key.
