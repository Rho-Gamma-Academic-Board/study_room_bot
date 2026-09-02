#!/bin/bash
# Headless booking run — used by cron (and manual testing).
# Usage: ./run-bot.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export RUN_HEADLESS=1
export PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/study_room_bot.log"
ERR="$ROOT/logs/study_room_bot_error.log"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >> "$ERR"
  exit 1
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run-bot.sh ====="
  "$ROOT/venv/bin/python3" "$ROOT/bot/study_room_bot.py"
} >> "$LOG" 2>> "$ERR"
