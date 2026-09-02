#!/bin/bash
# Headless booking run — used by launchd (and manual testing).
# Usage: ./run-bot.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export RUN_HEADLESS=1
export PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/study_room_bot.log"
ERR="$ROOT/logs/study_room_bot_error.log"

if [[ "${SCHEDULED_RUN:-}" == "1" ]]; then
  JITTER_MIN="${SCHEDULE_JITTER_MINUTES:-50}"
  if [[ -f "$ROOT/config/schedule.env" ]]; then
    # shellcheck disable=SC1090
    source "$ROOT/config/schedule.env"
    JITTER_MIN="${SCHEDULE_JITTER_MINUTES:-$JITTER_MIN}"
  fi
  JITTER_SEC=$((RANDOM % (JITTER_MIN * 60 + 1)))
  {
    echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') scheduled jitter: ${JITTER_SEC}s (~$((JITTER_SEC / 60))m ${JITTER_SEC % 60}s) ====="
  } >> "$LOG"
  sleep "$JITTER_SEC"
fi

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >> "$ERR"
  exit 1
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run-bot.sh ====="
  "$ROOT/venv/bin/python3" "$ROOT/bot/study_room_bot.py"
} >> "$LOG" 2>> "$ERR"
