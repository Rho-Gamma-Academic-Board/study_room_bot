#!/bin/bash
# Remove the study room bot cron job.
# Usage: ./uninstall-cron.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_BOT="$ROOT/run-bot.sh"

if ! crontab -l 2>/dev/null | grep -q "$RUN_BOT"; then
  echo "No cron job found for $RUN_BOT"
  exit 0
fi

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "$RUN_BOT" > "$TMP" || true
crontab "$TMP"
rm -f "$TMP"

echo "Removed cron job for $RUN_BOT"
