#!/usr/bin/env bash
# Poll board Outlook every few minutes and upsert Google Calendar check-in codes.
# Linux equivalent of ./scripts/install-outlook-scrape-launchd.sh
# Usage: ./scripts/install-outlook-scrape-cron.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRAPE="$ROOT/scrape-outlook.sh"
INTERVAL_MINUTES="${OUTLOOK_SCRAPE_INTERVAL_MINUTES:-5}"

# shellcheck source=scripts/cron.sh
source "$ROOT/scripts/cron.sh"

if [[ ! -f "$SCRAPE" ]]; then
  echo "Missing $SCRAPE"
  exit 1
fi
chmod +x "$SCRAPE"

if ! command -v crontab >/dev/null 2>&1; then
  echo "error: crontab not found — install cron (e.g. apt install cron)" >&2
  exit 1
fi

mkdir -p "$ROOT/logs"

# */N needs N that divides 60 cleanly for predictable polls.
TZ_NAME="${BOOKING_TZ:-America/New_York}"
SCRAPE_LINE="CRON_TZ=${TZ_NAME}
*/${INTERVAL_MINUTES} * * * * cd ${ROOT} && OUTLOOK_SCRAPE_ACCOUNT=Josh TZ=${TZ_NAME} PATH=\"${ROOT}/venv/bin:/usr/local/bin:/usr/bin:/bin\" ${SCRAPE} --once --wait 0 >>${ROOT}/logs/outlook-scrape.out.log 2>>${ROOT}/logs/outlook-scrape.err.log"

cron_install_block "$CRON_SCRAPE_TAG" "$SCRAPE_LINE"

echo "Installed Outlook scrape cron (every ${INTERVAL_MINUTES} min):"
echo "  tag: #${CRON_SCRAPE_TAG}"
echo "One-time Outlook login if needed:"
echo "  ./venv/bin/python3 bot/auth_board_outlook.py"
echo "Test now: ./scrape-outlook.sh --once --wait 0"
