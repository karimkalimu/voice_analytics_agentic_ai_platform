#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

[[ -f .env ]] || { printf 'Missing .env. Run ./ubuntu_setup.sh first.\n' >&2; exit 1; }
[[ -x .tools/tusd ]] || { printf 'Missing .tools/tusd. Run ./ubuntu_setup.sh first.\n' >&2; exit 1; }

set -a
. ./.env
set +a

for NAME in TUSD_PORT TUSD_UPLOAD_DIR TUSD_HOOK_URL TUSD_HOOK_EVENTS; do
  [[ -n "${!NAME:-}" ]] || { printf 'Missing required environment value: %s\n' "$NAME" >&2; exit 1; }
done

mkdir -p "$TUSD_UPLOAD_DIR"
exec .tools/tusd -upload-dir="$TUSD_UPLOAD_DIR" -port="$TUSD_PORT" -hooks-http="$TUSD_HOOK_URL" -hooks-enabled-events="$TUSD_HOOK_EVENTS"
