#!/usr/bin/env bash
# Install LaunchAgent so member intake stays up on this Mac (Tailscale Funnel target).
# Usage: ./scripts/install-intake-launchd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
START_INTAKE="$ROOT/start-intake.sh"
LABEL="com.otstudyrooms.intake"
DOMAIN="gui/$(id -u)"
SERVICE="${DOMAIN}/${LABEL}"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: launchd is macOS only" >&2
  exit 1
fi

if [[ ! -x "$START_INTAKE" ]]; then
  echo "Missing $START_INTAKE"
  exit 1
fi

if [[ ! -f "$ROOT/config/intake.env" ]]; then
  echo "Create config/intake.env first (copy intake.env.example, set INTAKE_PASSWORD)."
  exit 1
fi

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
    <string>${START_INTAKE}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${ROOT}/venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/logs/intake.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/logs/intake.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "$SERVICE" 2>/dev/null || true
if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
fi

echo "Installed intake LaunchAgent:"
echo "  $PLIST"
echo "Status: launchctl print $SERVICE"
echo "Logs: $ROOT/logs/intake.*.log"
echo
echo "Next (Tailscale Funnel):"
echo "  tailscale serve --bg 8790"
echo "  tailscale funnel --bg 8790"
echo "Then set Vercel STUDY_ROOM_INTAKE_URL to the HTTPS URL Funnel prints,"
echo "and set INTAKE_PUBLIC_URL / INTAKE_HTTPS=1 in config/intake.env."
