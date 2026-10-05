#!/usr/bin/env bash
# Start the study-room intake API (chapter site owns the UI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d venv ]]; then
  echo "Missing venv — run ./setup.sh first"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"

if [[ -f "$ROOT/config/intake.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/config/intake.env"
  set +a
fi
# Calendar/booking settings load in Python via shared.config (do not bash-source
# ucf_credentials.env — values contain spaces).

if [[ -z "${INTAKE_PASSWORD:-}" ]]; then
  echo "Set INTAKE_PASSWORD in config/intake.env (copy from config/intake.env.example)"
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PORT="${INTAKE_PORT:-8790}"
HOST="${INTAKE_HOST:-0.0.0.0}"

echo "Intake API → http://127.0.0.1:${PORT}/api/health"
echo "UI → chapter site /academic/study-rooms (proxies /study-room-api → this API)"
exec python -m uvicorn api.main:app --host "$HOST" --port "$PORT"
