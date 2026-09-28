# POC guardrails

The backend treats authentication tokens, upload metadata, filenames, filter values, transcript text, Layer 2 configuration, and model output as separate trust boundaries.

## Ownership and uploads

- Firebase Admin verifies bearer tokens; all file operations use the signed UID.
- TUS `pre-create` requires metadata `user_id` to match the token UID.
- Filenames never construct storage paths; upload IDs and resolved paths are validated.
- The completion hook is loopback-only and checks declared size, final offset, and local file size.
- Unique upload IDs make repeated hooks idempotent; a transaction enforces five active files per user.

## Audio content

- Before transcription: maximum 25 MB, valid audio stream, maximum 90 seconds, full FFmpeg decode, and minimum audible RMS.
- After transcription: English language, usable speech volume and density, provider confidence when available, deterministic profanity matching, and a strict contextual profanity classifier.
- Rejections store a stable code and safe user-facing reason.

## Filters and Layer 2 input

- Fixed Pydantic models reject unknown, duplicate, malformed, reversed, or out-of-range filters.
- Client values never become SQL field names, JSON paths, or grouping expressions.
- Layer 2 uses an option allowlist. `unique_only` must be boolean; topic mentions require a trimmed 1–100 character topic.

## Prompt injection and model output

- Trusted instructions remain in server-owned prompt files.
- Transcripts and user configuration are sent separately as untrusted user-role JSON.
- Spoken or typed instructions cannot replace backend prompts.
- Every LLM response is validated against a strict schema before storage.
- Provider refusals and invalid output become safe errors; internal details remain in logs.
- Aggregate prompts use bounded summaries and taxonomy, with hierarchical reduction for larger selections.

## Storage and deployment boundary

- Audio and transcripts are stored below a directory derived from `SHA-256(user_id)`; reuse is limited to the same verified user.
- Deletion is blocked during processing and removes unreferenced owned artifacts.
- Initial TUS creation is authenticated. Later `PATCH` and `HEAD` requests use the unguessable upload URL as a private POC capability.
- The tusd hook stays private. External traffic should use HTTPS.
