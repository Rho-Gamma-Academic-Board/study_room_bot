#!/usr/bin/env bash
# Poll board Outlook every few minutes and upsert Google Calendar check-in codes.
# Usage: ./scripts/install-outlook-scrape-launchd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRAPE="$ROOT/scrape-outlook.sh"
LABEL="com.otstudyrooms.outlook-scrape"
DOMAIN="gui/$(id -u)"
SERVICE="${DOMAIN}/${LABEL}"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
# StartCalendarInterval has no "every N minutes" — fire every 5 min via StartInterval.
INTERVAL_SECONDS="${OUTLOOK_SCRAPE_INTERVAL:-300}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: launchd is macOS only" >&2
  exit 1
fi

if [[ ! -f "$SCRAPE" ]]; then
  echo "Missing $SCRAPE"
  exit 1
fi
chmod +x "$SCRAPE"

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SCRAPE}</string>
    <string>--once</string>
    <string>--wait</string>
    <string>0</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${ROOT}/venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>OUTLOOK_SCRAPE_ACCOUNT</key>
    <string>Josh</string>
  </dict>
  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/logs/outlook-scrape.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/logs/outlook-scrape.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "$SERVICE" 2>/dev/null || true
if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
fi

echo "Installed Outlook scrape LaunchAgent (every ${INTERVAL_SECONDS}s):"
echo "  $PLIST"
echo "One-time Outlook login if needed:"
echo "  ./venv/bin/python3 bot/auth_board_outlook.py"
echo "Test now: ./scrape-outlook.sh --once --wait 0"
