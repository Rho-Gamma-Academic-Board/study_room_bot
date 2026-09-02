#!/bin/bash
# Manual brute-force run — bypasses weekday checks, prints to terminal.
# Usage: ./run-bot-now.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export BRUTE_RUN=1
export RUN_HEADLESS=1
export PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

exec "$ROOT/venv/bin/python3" "$ROOT/bot/study_room_bot.py"
