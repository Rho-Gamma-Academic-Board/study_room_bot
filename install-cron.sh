#!/bin/bash
# Install weekday study-room booking cron (Mon–Fri targets, 3 days ahead).
# Runs 8:00 AM on Fri, Sat, Sun, Mon, Tue — books Mon, Tue, Wed, Thu, Fri.
# Usage: ./install-cron.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_BOT="$ROOT/run-bot.sh"
# cron: minute hour dom month dow — dow 5=Fri, 6=Sat, 0=Sun, 1=Mon, 2=Tue
CRON_SCHEDULE="${CRON_SCHEDULE:-0 8 * * 5,6,0,1,2}"
CRON_LINE="$CRON_SCHEDULE $RUN_BOT"

if [[ ! -x "$RUN_BOT" ]]; then
  echo "Missing $RUN_BOT"
  exit 1
fi

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "$RUN_BOT" > "$TMP" || true
echo "$CRON_LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "Installed cron job (weekday rooms only — no Sat/Sun bookings):"
crontab -l | grep "$RUN_BOT"
echo
echo "Runs: Fri→Mon, Sat→Tue, Sun→Wed, Mon→Thu, Tue→Fri"
echo "Logs: $ROOT/study_room_bot.log"
echo "Errors: $ROOT/study_room_bot_error.log"
echo
echo "Test now: $RUN_BOT"
echo "Remove: $ROOT/uninstall-cron.sh"
