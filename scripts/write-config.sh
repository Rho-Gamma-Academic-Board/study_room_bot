#!/bin/bash
# Write config/ucf_credentials.env from interactive prompts.
# Usage: ./scripts/write-config.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$ROOT/config"
ENV_FILE="$CONFIG_DIR/ucf_credentials.env"
EXAMPLE="$CONFIG_DIR/ucf_credentials.env.example"

mkdir -p "$CONFIG_DIR"

current_booking=""
current_calendar=""
if [[ -f "$ENV_FILE" ]]; then
  current_booking="$(grep -E '^BOOKING_EMAIL=' "$ENV_FILE" | cut -d= -f2- || true)"
  current_calendar="$(grep -E '^STUDY_ROOMS_CALENDAR_NAME=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

echo
echo "Google Calendar settings (used when adding bookings to a shared calendar)."
echo

read -r -p "Booking email${current_booking:+ [$current_booking]}: " BOOKING_EMAIL
BOOKING_EMAIL="${BOOKING_EMAIL:-$current_booking}"

read -r -p "Calendar name${current_calendar:+ [$current_calendar]}: " CALENDAR_NAME
CALENDAR_NAME="${CALENDAR_NAME:-${current_calendar:-Academic Board - Study Rooms}}"

read -r -p "Calendar description [Automated study room bookings]: " CALENDAR_DESC
CALENDAR_DESC="${CALENDAR_DESC:-Automated study room bookings}"

if [[ -z "$BOOKING_EMAIL" ]]; then
  echo "Booking email is required."
  exit 1
fi

cat > "$ENV_FILE" <<EOF
# Google Calendar
BOOKING_EMAIL=${BOOKING_EMAIL}
STUDY_ROOMS_CALENDAR_NAME=${CALENDAR_NAME}
STUDY_ROOMS_CALENDAR_DESCRIPTION=${CALENDAR_DESC}
EOF

chmod 600 "$ENV_FILE"
echo
echo "Wrote $ENV_FILE"
