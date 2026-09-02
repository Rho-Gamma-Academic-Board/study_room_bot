#!/bin/bash
# Remove the study room bot LaunchAgent.
# Usage: ./uninstall-launchd.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

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
