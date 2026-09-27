#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MINOR="3.13"
PIP_VERSION="25.0"
TUSD_VERSION="v2.10.1"
TUSD_ARCHIVE="tusd_linux_amd64.tar.gz"
TUSD_SHA256="e8c8d7738275d2d9377db953aecbc242262d3620e77fbd3c1491361d9cea6ac8"
TUSD_URL="https://github.com/tus/tusd/releases/download/${TUSD_VERSION}/${TUSD_ARCHIVE}"

fail() {
  printf 'Setup failed: %s\n' "$1" >&2
  exit 1
}

[[ "$(uname -s)" == "Linux" ]] || fail "Ubuntu Linux is required."
[[ "$(uname -m)" == "x86_64" ]] || fail "x86_64 is required."
[[ -r /etc/os-release ]] || fail "Unable to identify the Linux distribution."

. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "Ubuntu is required."
case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *) fail "Ubuntu 22.04 or 24.04 is required." ;;
esac
[[ "$(dpkg --print-architecture)" == "amd64" ]] || fail "Ubuntu amd64 is required."

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  fail "Run as root or install sudo for apt package installation."
fi

cd "$ROOT_DIR"

"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl ffmpeg software-properties-common tar
"${SUDO[@]}" add-apt-repository -y ppa:deadsnakes/ppa
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y "python${PYTHON_MINOR}" "python${PYTHON_MINOR}-venv"

ACTUAL_PYTHON_MINOR="$("python${PYTHON_MINOR}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$ACTUAL_PYTHON_MINOR" == "$PYTHON_MINOR" ]] || fail "Python ${PYTHON_MINOR} is required; found ${ACTUAL_PYTHON_MINOR}."

if [[ -e .venv ]]; then
  [[ -x .venv/bin/python ]] || fail ".venv exists but does not contain an executable Python."
  VENV_PYTHON_MINOR="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [[ "$VENV_PYTHON_MINOR" == "$PYTHON_MINOR" ]] || fail ".venv uses Python ${VENV_PYTHON_MINOR}; Python ${PYTHON_MINOR} is required."
else
  "python${PYTHON_MINOR}" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade "pip==${PIP_VERSION}"
.venv/bin/python -m pip install --requirement requirements.txt
.venv/bin/python -m pip check

mkdir -p .tools storage/uploads storage/transcripts storage/users

TUSD_BIN="$ROOT_DIR/.tools/tusd"
INSTALLED_TUSD_VERSION=""
if [[ -x "$TUSD_BIN" ]]; then
  INSTALLED_TUSD_VERSION="$("$TUSD_BIN" -version 2>/dev/null | sed -n 's/^Version: //p' | head -n 1)"
fi

if [[ "$INSTALLED_TUSD_VERSION" != "$TUSD_VERSION" ]]; then
  DOWNLOAD_DIR="$(mktemp -d)"
  trap 'rm -rf "$DOWNLOAD_DIR"' EXIT
  curl --fail --location --retry 3 --output "$DOWNLOAD_DIR/$TUSD_ARCHIVE" "$TUSD_URL"
  printf '%s  %s\n' "$TUSD_SHA256" "$DOWNLOAD_DIR/$TUSD_ARCHIVE" | sha256sum --check --status
  tar -xzf "$DOWNLOAD_DIR/$TUSD_ARCHIVE" -C "$DOWNLOAD_DIR"
  install -m 0755 "$DOWNLOAD_DIR/tusd_linux_amd64/tusd" "$TUSD_BIN"
  rm -rf "$DOWNLOAD_DIR"
  trap - EXIT
fi

VERIFIED_TUSD_VERSION="$("$TUSD_BIN" -version 2>/dev/null | sed -n 's/^Version: //p' | head -n 1)"
[[ "$VERIFIED_TUSD_VERSION" == "$TUSD_VERSION" ]] || fail "tusd ${TUSD_VERSION} verification failed."

if [[ ! -e .env ]]; then
  install -m 0600 .env.example .env
fi

command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is unavailable after installation."
command -v ffprobe >/dev/null 2>&1 || fail "ffprobe is unavailable after installation."
.venv/bin/python -c 'import app.main'

printf '\nSetup complete\n'
printf 'Ubuntu: %s amd64\n' "$VERSION_ID"
printf 'Python: %s\n' "$(.venv/bin/python --version 2>&1)"
printf 'pip: %s\n' "$(.venv/bin/python -m pip --version)"
printf 'tusd: %s\n' "$VERIFIED_TUSD_VERSION"
printf 'ffmpeg: %s\n' "$(ffmpeg -version | head -n 1)"
printf 'Environment: %s\n' "$ROOT_DIR/.env"
printf 'Fill in .env, then run ./run_api.sh and ./run_tusd.sh in separate terminals.\n'
