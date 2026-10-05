#!/usr/bin/env bash
# Shared crontab helpers for the study room bot (Linux).
# Entries are wrapped in tagged comment blocks so install/uninstall is idempotent.

set -euo pipefail

CRON_BOOK_TAG="${CRON_BOOK_TAG:-otstudyrooms.bot}"
CRON_SCRAPE_TAG="${CRON_SCRAPE_TAG:-otstudyrooms.outlook-scrape}"

_cron_current() {
  crontab -l 2>/dev/null || true
}

cron_remove_block() {
  local tag="$1"
  local tmp
  tmp="$(mktemp)"
  _cron_current | awk -v tag="$tag" '
    $0 == "# BEGIN " tag { skip=1; next }
    $0 == "# END " tag { skip=0; next }
    !skip { print }
  ' > "$tmp"
  # Drop trailing blank lines left by removals.
  if [[ -s "$tmp" ]]; then
    crontab "$tmp"
  else
    crontab -r 2>/dev/null || true
  fi
  rm -f "$tmp"
}

cron_install_block() {
  local tag="$1"
  local body="$2"
  local tmp
  tmp="$(mktemp)"
  {
    _cron_current | awk -v tag="$tag" '
      $0 == "# BEGIN " tag { skip=1; next }
      $0 == "# END " tag { skip=0; next }
      !skip { print }
    '
    echo "# BEGIN ${tag}"
    printf '%s\n' "$body"
    echo "# END ${tag}"
  } > "$tmp"
  crontab "$tmp"
  rm -f "$tmp"
}

cron_block_installed() {
  local tag="$1"
  _cron_current | grep -qxF "# BEGIN ${tag}"
}
