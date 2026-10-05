#!/usr/bin/env bash
# Remove the study-room booking LaunchAgent (macOS).
# On Linux, use ./uninstall-cron.sh
# Usage: ./uninstall-launchd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "launchd is macOS only — removing Linux cron equivalent..." >&2
  exec "$ROOT/uninstall-cron.sh"
fi

# shellcheck source=scripts/launchd.sh
source "$ROOT/scripts/launchd.sh"

PLIST="$(launchd_plist_path)"

if [[ ! -f "$PLIST" ]] && ! launchd_installed; then
  echo "No LaunchAgent found for ${LAUNCHD_LABEL}"
  exit 0
fi

launchd_unload
rm -f "$PLIST"

echo "Removed LaunchAgent ${LAUNCHD_LABEL}"
