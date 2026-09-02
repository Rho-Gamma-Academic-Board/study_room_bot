#!/bin/bash
# Shared launchd helpers for the study room bot (macOS only).

set -euo pipefail

LAUNCHD_LABEL="${LAUNCHD_LABEL:-com.otstudyrooms.bot}"
LAUNCHD_DOMAIN="gui/$(id -u)"
LAUNCHD_SERVICE="${LAUNCHD_DOMAIN}/${LAUNCHD_LABEL}"

launchd_plist_path() {
  echo "${HOME}/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"
}

launchd_installed() {
  launchctl print "$LAUNCHD_SERVICE" >/dev/null 2>&1
}

launchd_unload() {
  local plist
  plist="$(launchd_plist_path)"
  launchctl bootout "$LAUNCHD_SERVICE" 2>/dev/null \
    || launchctl unload "$plist" 2>/dev/null \
    || true
}

launchd_load() {
  local plist="$1"
  launchctl bootout "$LAUNCHD_SERVICE" 2>/dev/null || true
  if launchctl bootstrap "$LAUNCHD_DOMAIN" "$plist" 2>/dev/null; then
    return 0
  fi
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
}

remove_legacy_cron() {
  local run_bot="$1"
  if ! crontab -l 2>/dev/null | grep -qF "$run_bot"; then
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -vF "$run_bot" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  echo "Removed legacy cron entry for $run_bot"
}
