#!/usr/bin/env bash
# Remove study-room booking + Outlook scrape cron entries.
# Usage: ./uninstall-cron.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=scripts/cron.sh
source "$ROOT/scripts/cron.sh"

removed=0
if cron_block_installed "$CRON_BOOK_TAG"; then
  cron_remove_block "$CRON_BOOK_TAG"
  echo "Removed cron block #${CRON_BOOK_TAG}"
  removed=1
fi
if cron_block_installed "$CRON_SCRAPE_TAG"; then
  cron_remove_block "$CRON_SCRAPE_TAG"
  echo "Removed cron block #${CRON_SCRAPE_TAG}"
  removed=1
fi

if (( removed == 0 )); then
  echo "No study-room cron blocks found."
fi
