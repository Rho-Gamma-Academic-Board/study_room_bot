#!/usr/bin/env bash
# Book study rooms (cookie sessions), then optionally scrape Outlook → Calendar.
#   ./run-bot.sh          # headless → logs/ (what launchd uses)
#   ./run-bot.sh --now    # live terminal output, no schedule jitter
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export RUN_HEADLESS=1
export PATH="$ROOT/venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
# Prefer 360H, book 3 days ahead, don't linger on confirmation pages.
export DAYS_AHEAD="${DAYS_AHEAD:-3}"
export TARGET_ROOM="${TARGET_ROOM:-360H}"
export CLOSE_AFTER_SECONDS="${CLOSE_AFTER_SECONDS:-5}"
# After booking, pull check-in codes from board Outlook into Google Calendar.
AUTO_SCRAPE="${AUTO_SCRAPE:-1}"

NOW=0
if [[ "${1:-}" == "--now" ]]; then
  NOW=1
  shift
  unset SCHEDULED_RUN
fi

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

run_booking() {
  "$ROOT/venv/bin/python3" "$ROOT/bot/study_room_bot.py" "$@"
}

run_scrape_retries() {
  # LibCal forwards can lag a bit; retry a few times without needing a prompt.
  local waits=(90 120 180)
  local i=1
  for w in "${waits[@]}"; do
    echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') auto-scrape attempt ${i}/${#waits[@]} (wait ${w}s) ====="
    "$ROOT/scrape-outlook.sh" --once --wait "$w" || true
    i=$((i + 1))
  done
}

if (( NOW )); then
  run_booking "$@"
  if [[ "$AUTO_SCRAPE" == "1" ]]; then
    run_scrape_retries
  fi
  exit 0
fi

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/study_room_bot.log"
ERR="$ROOT/logs/study_room_bot_error.log"

if [[ "${SCHEDULED_RUN:-}" == "1" ]]; then
  JITTER_MIN="${SCHEDULE_JITTER_MINUTES:-8}"
  if [[ -f "$ROOT/config/schedule.env" ]]; then
    # shellcheck disable=SC1090
    source "$ROOT/config/schedule.env"
    JITTER_MIN="${SCHEDULE_JITTER_MINUTES:-$JITTER_MIN}"
  fi
  JITTER_SEC=$((RANDOM % (JITTER_MIN * 60 + 1)))
  JITTER_MIN_PART=$((JITTER_SEC / 60))
  JITTER_SEC_PART=$((JITTER_SEC % 60))
  {
    echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') scheduled jitter: ${JITTER_SEC}s (~${JITTER_MIN_PART}m ${JITTER_SEC_PART}s) ====="
  } >> "$LOG"
  sleep "$JITTER_SEC"
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') run-bot.sh TARGET_ROOM=${TARGET_ROOM} DAYS_AHEAD=${DAYS_AHEAD} ====="
  run_booking "$@"
  if [[ "$AUTO_SCRAPE" == "1" ]]; then
    run_scrape_retries
  fi
} >> "$LOG" 2>> "$ERR"
