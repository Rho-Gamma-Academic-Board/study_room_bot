#!/bin/bash
# Manual test run — no weekday restrictions, live terminal output.
# Usage: ./run-bot-now.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export RUN_HEADLESS=1
unset SCHEDULED_RUN
export PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

exec "$ROOT/venv/bin/python3" "$ROOT/bot/study_room_bot.py"
