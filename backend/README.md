# Audio analysis POC backend

This repository registers completed tusd uploads, validates POC audio policy, transcribes acceptable English speech with AssemblyAI, runs Layer 1 summary and taxonomy analysis, optionally runs selected Layer 2 analyses, creates offline aggregate analyses, and lists a Firebase user's files.

## Components and reasons

| Component | Role and reason |
| --- | --- |
| FastAPI in `app/main.py` | Serves the small HTTP API and validates the tusd hook payload. FastAPI was requested for this backend. |
| Uvicorn | Runs the ASGI app; FastAPI does not include a production HTTP server. |
| Built-in `sqlite3` in `app/database.py` | Stores one row per uploaded file and one row per aggregate job without an ORM or migration framework. `app.db` is created at startup; WAL and a 30-second busy timeout support concurrent POC requests. |
| Firebase Admin in `app/auth.py` | Uses [Firebase's ID-token verifier](https://firebase.google.com/docs/auth/admin/verify-id-tokens) to extract the signed UID instead of trusting a client-provided user ID. No signup or login endpoint exists. |
| tusd HTTP `pre-create` hook | Checks the token sent to tusd on the initial POST and requires its UID to match `user_id` metadata. This prevents a client from claiming another user's UID. [tusd documents this authentication hook](https://tus.github.io/tusd/advanced-topics/hooks/#authenticating-users). |
| tusd HTTP `post-finish` hook | Registers the existing file only after tusd finishes writing it. It validates the [hook payload's `Storage.Path`, `Size`, and `Offset`](https://tus.github.io/tusd/advanced-topics/hooks/#hook-requests-and-responses), requires offset to equal declared size, and compares that size with the local file; background processing then finalizes the audio into its user directory. |
| `app/storage.py` | Uses a SHA-256 digest of the verified Firebase UID as a filesystem-safe user directory. Audio has a stable file-ID path independent of the client filename. A hardlink followed by an atomic symlink swap leaves tusd's working URL usable after completion. |
| Existing `storage/uploads/` | Remains tusd's working directory for active uploads and completed-upload `.info` sidecars. Completed data bytes live under `storage/users/`; the tusd data path becomes a symlink. |
| Unique `upload_id` in SQLite | Makes repeated `post-finish` hook deliveries safe to register once. |
| SHA-256 and versioned file results | Identical audio from the same Firebase user can reuse language, duration, and an existing transcript. Analysis is reused only when its prompt, schema, model, base URL, and configured version match. Transcript reuse updates the new row inside a SQLite write transaction so deletion sees the shared reference. |
| Loopback-only hook and path containment checks | Keep direct remote callers from submitting hook events and prevent a reported path from pointing outside `storage/uploads/`. |
| FastAPI `BackgroundTasks` | Starts transcription after the completion-hook response, so tusd does not wait for AssemblyAI. This is a small in-process POC; no queue or worker service is used. |
| `app/guardrails.py` | Enforces file size, probed duration, full decode, conservative audio level, intelligible-speech, confidence, language, profanity, and active-file limits. It also supplies the public policy response from the same configuration. |
| `app/content_policy.py` | Applies a deterministic English profanity resource first, then the weak LLM tier with strict boolean output. Transcript content stays in a separate untrusted user-role JSON value. |
| AssemblyAI REST API in `app/transcription.py` | Streams the existing local file to AssemblyAI, requests automatic language detection, and polls for the transcript. The Python standard library handles HTTPS, so no AssemblyAI SDK dependency is needed. |
| LiteLLM in `app/llm.py` | Calls the configured model and endpoint for the selected weak, medium, or strong tier through one interface. Layer 1 currently uses medium. |
| Prompt files in `prompts/` | Keep each LLM instruction outside Python. They are loaded at runtime, and their contents contribute to cache versions. |
| `app/layer2.py` | Runs allowlisted analyses selected at upload creation or later through `POST /files/{id}/layer2`. Noun count, adjective count, sentiment, and topic mentions use the weak tier with strict JSON validation. Noun counting accepts a validated `unique_only` boolean; topic mentions requires a validated `topic` string. Both configurations participate in per-option cache versions. |
| Pending Layer 2 options in SQLite | Records exactly which options an accepted request still needs, so a restart resumes unfinished work without rerunning unrelated earlier selections. |
| `app/aggregate_analysis.py` | Selects eligible owned files, computes deterministic counts, duration, and groups, and uses the medium LLM tier for bounded collection and per-group context synthesis. Aggregate jobs are independent from per-file processing. |
| `aggregate_jobs` in SQLite | Persists each backend-controlled aggregate request, optional user scope, status, result, safe error, and timestamps so offline jobs survive restarts. |
| FFmpeg in `app/audio.py` | Decodes the existing audio to mono 16 kHz PCM for deterministic RMS without adding a Python package. The `ffmpeg` executable must be on `PATH`. RMS is the normalized sample amplitude from 0 to 1; digital silence yields 0. |
| LiteLLM `openai/` routing prefix | The tier's `MODEL` value is the exact remote model ID. The service adds LiteLLM's OpenAI-compatible routing prefix so an ID such as `openai/gpt-oss-120b` reaches the configured endpoint intact. |
| Pydantic in `app/analysis.py` | Generates the strict JSON schema sent to the model and validates its response before saving it. Pydantic is already installed with FastAPI. |
| `python-dotenv` in `app/__init__.py` | Loads `.env` before Firebase and transcription modules use their credentials. Shell sourcing still supplies the API and tusd launch arguments. |
| `storage/users/<uid-sha256>/transcripts/` | Holds UTF-8 `.txt` transcripts. Matching uploads for the same user can reference the same transcript, and deletion retains it until the last reference is removed. `storage/transcripts/` is migrated on startup. |
| FFprobe duration | Supplies `duration_sec` from the uploaded local audio before transcription rather than asking AssemblyAI or the LLM to estimate it. |
| Startup recovery | Migrates older audio and transcripts into user directories, resumes intermediate per-file states, backfills missing terminal audio hashes, and reruns persisted aggregate jobs left in `queued` or `running`. |

## Ubuntu amd64 setup

The supported setup target is Ubuntu 22.04 or 24.04 on x86_64/amd64. It uses Python 3.13, pip 25.0, and tusd v2.10.1. The setup script rejects other operating systems, Ubuntu releases, architectures, and Python minor versions.

From this directory:

```sh
chmod +x ubuntu_setup.sh run_api.sh run_tusd.sh
./ubuntu_setup.sh
```

The script installs exactly these apt packages: `ca-certificates`, `curl`, `ffmpeg`, `software-properties-common`, `tar`, `python3.13`, and `python3.13-venv`. Python 3.13 comes from the [deadsnakes Ubuntu PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa), which supplies it for both supported Ubuntu releases. This third-party PPA warns that timely security updates are not guaranteed, so reassess the Python source before using this POC as a security-critical service.

Every directly used Python package has an exact version in `requirements.txt`; pip resolves their transitive dependencies. The script pins pip, creates `.venv` only when absent, verifies an existing virtual environment uses Python 3.13, installs the pinned dependencies, and runs `pip check` and a backend import. It downloads the official [tusd v2.10.1](https://github.com/tus/tusd/releases/tag/v2.10.1) `tusd_linux_amd64.tar.gz` artifact into `.tools/tusd` and verifies its published SHA-256 digest before installation. It also creates the required storage directories and copies `.env.example` to `.env` only when `.env` is absent.

Fill in `.env`, then start the API:

```sh
./run_api.sh
```

Start tusd in another terminal:

```sh
./run_tusd.sh
```

Both launch scripts change to the repository root, load `.env`, use the repository-local executables, and report missing required configuration. The setup and launch scripts never write credentials or overwrite an existing `.env`.

`.env` holds `GOOGLE_APPLICATION_CREDENTIALS`, `ASSEMBLYAI_API_KEY`, `LLM_{WEAK,MEDIUM,STRONG}_{API_KEY,BASE_URL,MODEL}`, processing versions, POC guardrail limits, and the service ports and tusd flags. The guardrail defaults are `POC_MAX_AUDIO_DURATION_SEC=90`, `POC_MAX_AUDIO_SIZE_MB=25`, `POC_MAX_ACTIVE_FILES_PER_USER=5`, `POC_MIN_AUDIO_RMS=0.001`, `POC_MIN_TRANSCRIPT_WORDS=3`, `POC_MIN_TRANSCRIPT_WORDS_PER_MINUTE=5`, and `POC_MIN_AVG_WORD_CONFIDENCE=0.35`. The version values default to `1`; bump `TRANSCRIPTION_VERSION` when transcription behavior changes and `GUARDRAIL_VERSION` when policy behavior changes. Layer 1's stored version changes automatically with its prompt, schema, medium-tier model, or base URL. Each Layer 2 option has its own stored version; RMS uses the decoding algorithm, while text options include prompt, schema, weak-tier model, base URL, transcript digest, and validated configuration. Bumping `LAYER2_VERSION` invalidates all Layer 2 options on the next upload. `python-dotenv` loads `.env` for the app; the launch scripts source it for service arguments. `.env.example` shows the variables without exposing credentials.

The TUS client sends `Authorization: Bearer <firebase_id_token>` on the initial upload POST and sets TUS metadata keys `user_id` and `filename`. It may set `layer2_options` to a UTF-8 JSON array of unique IDs from `rms`, `count_nouns`, `count_adjectives`, `sentiment`, and `topic_mentions`, for example `["rms","topic_mentions"]`. It may set `layer2_config` to `{"count_nouns":{"unique_only":true},"topic_mentions":{"topic":"machine learning"}}`. `unique_only` must be a JSON boolean and defaults to `false`; a selected `topic_mentions` option requires its `topic` string. These are separate metadata values, each Base64-encoded in the TUS `Upload-Metadata` header; tusd passes decoded strings to the hook. Missing `layer2_options` means `[]`. Invalid options, configuration, or path-like filenames reject upload creation with 400. At `post-finish`, the backend requires tusd's final offset, declared size, and actual local file size to agree. The backend requires `user_id` to match the verified token UID. All `/files` endpoints require the same bearer token. `GET /health` does not require authentication. The hook endpoint accepts direct loopback calls from local tusd. [The TUS protocol defines the header encoding](https://github.com/tus/tus-resumable-upload-protocol/blob/main/protocol.md#upload-metadata).

An authenticated `POST /files/{id}/layer2` with `Content-Type: application/json` and `{"options":["topic_mentions"],"config":{"topic_mentions":{"topic":"machine learning"}}}` adds that analysis to a completed file with a readable transcript and saved Layer 1 result. The `config` object uses the same shape as TUS `layer2_config`; it is optional only for options without required configuration. Unknown or duplicate options, malformed or unsupported configuration, malformed JSON, and extra fields return 422. An empty options array is a no-op. Newly requested options and requested options without a result at the current version run in a FastAPI background task. The response has the same JSON shape as `GET /files/{id}`: 202 with `status: "analyzing_layer2"` when work is queued, or 200 when all requested results are already current. Missing or unowned files return 404; active files or files without a usable transcript and Layer 1 result return 409. Earlier results remain available if a requested option fails. A restart resumes the pending options.

## Offline aggregate analysis

Aggregate jobs are backend-controlled and are not exposed through FastAPI. The Uvicorn application has no `/aggregate-jobs` routes. Backend code can create a persisted `queued` job with `queue_aggregate_job()` and execute it with `run_aggregate_job()`. Jobs move through `queued`, `running`, `completed`, or `failed`; startup reruns jobs left in `queued` or `running`.

Run a global user-partitioned job from this directory:

```sh
.venv/bin/python -m app.aggregate_job --group-by user
```

Optional arguments are `--user-id`, `--created-from`, `--created-to`, and `--taxonomy-label`. Dates must be timezone-aware ISO 8601 values. The CLI persists the job, prints its ID and queued status, runs it, then prints the final status, result, and safe error. Examples:

```sh
.venv/bin/python -m app.aggregate_job --group-by user --created-from 2026-09-01T00:00:00Z
.venv/bin/python -m app.aggregate_job --group-by taxonomy --taxonomy-label software
.venv/bin/python -m app.aggregate_job --group-by all --user-id FIREBASE_UID
```

The internal job configuration is:

```json
{
  "user_id": null,
  "created_from": null,
  "created_to": null,
  "taxonomy_label": null,
  "group_by": "user"
}
```

`user_id: null` means global offline scope across all users. A nonempty `user_id` restricts selection to that stored Firebase UID. Date bounds are optional and inclusive. `taxonomy_label` is an optional case-insensitive exact filter across all Layer 1 taxonomy arrays. `group_by` is one of `all`, `user`, `taxonomy`, or `sentiment`. No arbitrary field, JSON path, SQL, or grouping expression is accepted.

`user` partitions strictly by the persisted file `user_id`. Each user summary and taxonomy receive only that user's compact Layer 1 records. Global `user` jobs do not send a mixed-user collection to the LLM and do not merge professional topics, personal topics, or upcoming events at the top level. Their top-level summary reports counts and directs readers to isolated user groups. `taxonomy` includes a file in each of its labels and uses `unclassified` when it has no labels. `sentiment` uses the stored Layer 2 sentiment and uses `unclassified` when it is absent. Global taxonomy and sentiment jobs aggregate matching records across users by that selected dimension. `all` is valid only with an explicit `user_id`, so one content summary can never combine multiple users under an undifferentiated group.

Only `completed` files with positive duration, nonempty Layer 1 summary, valid taxonomy, and a readable UTF-8 transcript are eligible. Rejected, failed, active, incomplete, and missing-artifact files are excluded. A request with no matching files completes without an LLM call and returns a clear empty result.

The completed result is:

```json
{
  "file_count": 2,
  "total_duration_sec": 47.25,
  "overall_summary": "Aggregate includes 2 eligible files across 2 users. Per-user summaries are provided in groups.",
  "group_by": "user",
  "groups": [
    {
      "user_id": "firebase-uid",
      "file_count": 7,
      "total_duration_sec": 420.0,
      "summary": "These files discuss the user's recurring project context.",
      "professional_topics": ["software"],
      "personal_topics": ["gardening"],
      "upcoming_events": []
    }
  ]
}
```

Counts, durations, and group membership are computed deterministically. The medium LLM tier synthesizes contextual summaries through strict schemas. User grouping uses `prompts/aggregate_user_summary.md` to return one validated summary and taxonomy per user. Every synthesis uses only that group's eligible records. The model receives compact existing Layer 1 summaries and taxonomy rather than transcripts. Each LLM input is capped at 24,000 characters, each category contributes at most 25 labels per record, and larger selections are reduced through bounded batches before final synthesis. Collection instructions are in `prompts/aggregate_analysis.md`, other group-summary instructions are in `prompts/aggregate_group_summary.md`, and all record content remains untrusted user-role JSON. A group without meaningful context receives a short safe summary.

After a successful tusd completion event, the file moves through `uploaded`, `validating_audio`, `transcribing`, `validating_transcript`, `transcribed`, `analyzing`, and then `analyzing_layer2` if any options were selected, before `completed`. Policy rejection uses terminal status `rejected` with a stable `rejection_code` and user-facing `error`; operational failures remain `transcription_failed`, `analysis_failed`, and `layer2_failed`. `GET /files` and `GET /files/{id}` include `duration_sec`, `summary`, three topic/event arrays, `status`, `language`, `rejection_code`, persistent user-facing `error`, hash and version fields, nullable `transcript_path`, `transcript_available`, `layer2_options` as an array, `layer2_config` as an object, `layer2_results` as an object, and `layer2_version` as an object keyed by completed option. A result is `{"rms":{"rms_normalized":0.2}}`, `{"count_nouns":{"count":42}}`, `{"count_adjectives":{"count":15}}`, `{"sentiment":{"label":"positive"}}`, or `{"topic_mentions":{"count":3}}`; the result object contains only options that succeeded. `GET /files/{id}/transcript` returns `{"transcript": "..."}` when available. `DELETE /files/{id}` returns 204 after removing the row and unreferenced local audio, tusd alias and `.info`, and transcript files; it returns 409 while processing is active. An unknown or other user's file returns 404. Completed and rejected files stay terminal at startup; interrupted validation stages resume. Storage paths in metadata are server-local.

## POC input requirements

- The upload must contain valid audio that ffprobe recognizes and ffmpeg can fully decode.
- The server-observed file size must not exceed 25 MB and actual probed duration must not exceed 90 seconds.
- The recording must contain enough audible, intelligible English speech for analysis.
- Audio containing English profanity is not processed.
- At most five files per user may be in active processing states at once.

Before transcription, the backend checks file size, audio stream and duration with ffprobe, full decoding and normalized RMS with ffmpeg, and the per-user active-file limit. These checks avoid AssemblyAI and LLM cost for files that are already unusable or outside the POC limits.

After transcription, the backend checks detected language, a conservative usable-word floor, understood-word density for longer recordings, aggregate AssemblyAI word confidence when available, a deterministic profanity resource, and a strict weak-tier contextual profanity classifier. A prompt-injection-style sentence is retained as transcript data and is not itself a rejection reason.

`GET /guardrails` is public and returns all configured thresholds in `limits` plus seven string-only policy sections covering access and uploads, audio validation, transcript and content validation, LLM input isolation, Layer 1 validation, Layer 2 validation, and failure handling. Flutter can render these directly without understanding backend implementation details. Configured values come from the same settings used for enforcement.

The transcript is always passed to LLM calls as untrusted user-role JSON, while trusted instructions stay in prompt files. Spoken instructions cannot replace backend prompts. Layer 2 option IDs and configuration fields are allowlisted, and every LLM response is validated against a strict schema.

Duration, size, active-file, English-language, and profanity restrictions are POC/demo policy choices and may differ in production.

`GET /files` accepts composable optional filters: `created_from` and `created_to` (ISO 8601 timestamps with timezone, inclusive), `duration_min` and `duration_max` (seconds, nonnegative), `taxonomy_label` (case-insensitive exact match in any of the three taxonomy arrays), `sentiment` (`positive`, `neutral`, or `negative`), `rms_min` and `rms_max` (normalized 0–1), `noun_count_min` and `noun_count_max`, and `adjective_count_min` and `adjective_count_max` (nonnegative integers). Bounds are inclusive. Unknown, duplicate, malformed, reversed, or out-of-range parameters return 422. Missing result values do not match a requested result filter. Filters operate only on the authenticated user's stored rows; no client input becomes a SQL field name or JSON path. No query parameters preserves the existing list response.

Layer 1 summarizes only explicit transcript content. Technical subjects qualify as professional topics; personal topics require actual private-life content rather than first-person wording alone. Upcoming events require an explicit future plan. Topic labels are concise, distinct, and never placeholders such as `None`; absent categories remain empty arrays. Audio and transcript text stay in the user-content role, while prompt files define the analysis instructions. Provider refusals and invalid structured output leave short persistent messages in `error`, with internal details kept in server logs.

Completed artifacts live at `storage/users/<sha256-of-Firebase-uid>/audio/<file-id>/audio` and `storage/users/<sha256-of-Firebase-uid>/transcripts/<transcript-source-file-id>.txt`. Active tusd uploads, completed-upload `.info` files, and symlink aliases stay under `storage/uploads/` so tusd can still answer HEAD for completed URLs. A future object store can use keys `users/<uid-sha256>/audio/<file-id>/audio` and `users/<uid-sha256>/transcripts/<source-file-id>.txt`. Flutter should start one TUS upload per selected file, giving each its own metadata and tracking each returned upload URL; there is no batch endpoint. Each file progresses and can fail independently. Flutter should use a client-generated UUID in its own resume fingerprint or local upload-to-TUS-URL mapping. Adding `client_upload_id` metadata to this backend would not resolve a client-side filename-and-size fingerprint collision, so no backend field was added.

The credential JSON, `.env`, `.venv/`, and `app.db` are local files covered by `.gitignore`. Do not publish the service account key. Use HTTPS for client traffic outside the local machine.

`requirements.txt` pins FastAPI, Uvicorn, Firebase Admin, python-dotenv, LiteLLM, and Pydantic to the exact versions used by the working Python 3.13 environment. Transitive Python packages and apt package revisions remain those currently published by their package repositories.

## Current status

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for verification results and remaining work.

The broader assignment is archived in [docs/AI_full_stack_task.md](docs/AI_full_stack_task.md). It is background for future stages, not the scope of this backend foundation.
