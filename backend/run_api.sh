#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

[[ -f .env ]] || { printf 'Missing .env. Run ./ubuntu_setup.sh first.\n' >&2; exit 1; }
[[ -x .venv/bin/uvicorn ]] || { printf 'Missing .venv. Run ./ubuntu_setup.sh first.\n' >&2; exit 1; }

set -a
. ./.env
set +a

for NAME in GOOGLE_APPLICATION_CREDENTIALS ASSEMBLYAI_API_KEY LLM_WEAK_API_KEY LLM_WEAK_BASE_URL LLM_WEAK_MODEL LLM_MEDIUM_API_KEY LLM_MEDIUM_BASE_URL LLM_MEDIUM_MODEL LLM_STRONG_API_KEY LLM_STRONG_BASE_URL LLM_STRONG_MODEL API_HOST API_PORT; do
  [[ -n "${!NAME:-}" ]] || { printf 'Missing required environment value: %s\n' "$NAME" >&2; exit 1; }
done

if [[ "$GOOGLE_APPLICATION_CREDENTIALS" = /* ]]; then
  CREDENTIAL_PATH="$GOOGLE_APPLICATION_CREDENTIALS"
else
  CREDENTIAL_PATH="$ROOT_DIR/$GOOGLE_APPLICATION_CREDENTIALS"
fi
[[ -f "$CREDENTIAL_PATH" ]] || { printf 'Firebase credential file does not exist: %s\n' "$GOOGLE_APPLICATION_CREDENTIALS" >&2; exit 1; }

exec .venv/bin/uvicorn app.main:app --host "$API_HOST" --port "$API_PORT"
