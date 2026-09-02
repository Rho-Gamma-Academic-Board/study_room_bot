#!/bin/bash
# Headless booking run — used by cron (and manual testing).
# Usage: ./run-bot.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export RUN_HEADLESS=1
export PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin"

LOG="$ROOT/study_room_bot.log"
ERR="$ROOT/study_room_bot_error.log"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt" >> "$ERR"
  exit 1
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run-bot.sh ====="
  "$ROOT/venv/bin/python3" "$ROOT/study_room_bot.py"
} >> "$LOG" 2>> "$ERR"
