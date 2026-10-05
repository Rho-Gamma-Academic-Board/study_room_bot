#!/usr/bin/env bash
# Guided first-time setup — calendar, accounts, launchd schedule.
# Usage: ./onboard.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/launchd.sh
source "$ROOT/scripts/launchd.sh"

BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
GOLD='\033[38;5;220m'; GREEN='\033[38;5;82m'; RED='\033[38;5;196m'

say() { printf "%b\n" "$1"; }
step() { printf '\n%b\n' "${GOLD}${BOLD}==> $1${RESET}"; }

account_count() {
  if [[ ! -d "$ROOT/data/accounts" ]]; then
    echo 0
    return
  fi
  find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' \
    ! -name 'example.env' ! -name '*.example' 2>/dev/null | wc -l | tr -d ' '
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  say "${RED}This wizard is macOS only.${RESET}"
  exit 1
fi

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  say "${RED}Run ./setup.sh first (or use the curl installer).${RESET}"
  exit 1
fi

say ""
say "${GOLD}${BOLD}OT Study Rooms — setup wizard${RESET}"
say "${DIM}Calendar service account, LibCal cookies, board Outlook, schedule.${RESET}"
say ""

step "1/4  Google Calendar (service account)"
"$ROOT/scripts/write-config.sh"
if [[ -f "$ROOT/config/service-account.json" ]]; then
  say "${GREEN}  ok${RESET} config/service-account.json found"
else
  say "Place an IAM service account JSON at config/service-account.json"
  say "${DIM}Share Academic Board - Study Rooms with the SA email (Make changes to events).${RESET}"
  say "${DIM}Set STUDY_ROOMS_CALENDAR_ID in config/ucf_credentials.env${RESET}"
  read -r -p "Press Enter once the file is in place (or Ctrl+C to abort)... "
  if [[ ! -f "$ROOT/config/service-account.json" ]]; then
    say "${RED}Still missing service-account.json${RESET}"
    exit 1
  fi
fi

say ""
say "Verifying calendar access..."
"$ROOT/venv/bin/python3" "$ROOT/bot/auth_google_calendar.py" || true

step "2/4  LibCal cookie accounts"
count="$(account_count)"
say "You have ${count} account(s). Full 12pm–10pm coverage needs ${BOLD}3${RESET}."
say "${DIM}Prefer ./start-intake.sh for members; or ./import-cookies.sh here.${RESET}"
say ""

while true; do
  count="$(account_count)"
  if (( count >= 3 )); then
    read -r -p "Add another account? [y/N] " more
    [[ "$more" =~ ^[Yy]$ ]] || break
  else
    need=$((3 - count))
    say "${DIM}Need $need more for full-day coverage.${RESET}"
    read -r -p "Add an account now? [Y/n] " more
    [[ -z "$more" || "$more" =~ ^[Yy]$ ]] || break
  fi
  say ""
  "$ROOT/import-cookies.sh" || true
  say ""
done

step "3/4  Board Outlook (check-in codes)"
say "Patrons forward LibCal alerts → BOOKING_EMAIL (board Outlook)."
say "Sign in once so ./scrape-outlook.sh can read the Inbox:"
read -r -p "Run board Outlook auth now? [Y/n] " outlook
if [[ -z "$outlook" || "$outlook" =~ ^[Yy]$ ]]; then
  "$ROOT/venv/bin/python3" "$ROOT/bot/auth_board_outlook.py" || true
fi

step "4/4  Auto-booking schedule"
if launchd_installed; then
  say "${GREEN}  ok${RESET} LaunchAgent already installed"
  say "    $(launchd_plist_path)"
else
  say "Install a randomized morning run window (Fri–Tue → books Mon–Fri rooms)?"
  read -r -p "Install LaunchAgent? [Y/n] " install
  if [[ -z "$install" || "$install" =~ ^[Yy]$ ]]; then
    "$ROOT/install-launchd.sh"
  fi
fi

say ""
say "${GREEN}${BOLD}Setup complete.${RESET}"
say ""
say "  ./start-intake.sh     — intake API (:8790)"
say "  ./run-bot.sh --now    — test a booking now"
say "  ./scrape-outlook.sh   — LibCal forwards → calendar"
say "  Chapter site UI       — /academic/study-rooms"
say "  ./start.sh            — ops menu anytime"
say ""
