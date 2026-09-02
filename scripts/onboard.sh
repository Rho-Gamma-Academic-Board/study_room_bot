#!/bin/bash
# Guided first-time setup — calendar, accounts, launchd schedule in one flow.
# Usage: ./onboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
  find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' ! -name 'example.env' 2>/dev/null | wc -l | tr -d ' '
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
say "${DIM}This walks through calendar, UCF accounts, and scheduling.${RESET}"
say ""

# --- Google OAuth file ---
step "1/4  Google OAuth credentials"
if [[ -f "$ROOT/config/credentials.json" ]]; then
  say "${GREEN}  ok${RESET} config/credentials.json found"
  read -r -p "Replace credentials.json? [y/N] " replace
  if [[ "$replace" =~ ^[Yy]$ ]]; then
    "$ROOT/import-google-credentials.sh" || exit 1
  fi
else
  say "You need a Google OAuth Desktop client JSON from Google Cloud Console."
  say "${DIM}APIs & Services → Credentials → Create OAuth client → Desktop app → Download JSON${RESET}"
  say ""
  "$ROOT/import-google-credentials.sh" || exit 1
fi

# --- Calendar config ---
step "2/4  Google Calendar"
"$ROOT/scripts/write-config.sh"
say "${GREEN}  ok${RESET} Calendar: Academic Board - Study Rooms (rg.academicboard@gmail.com)"

if [[ ! -f "$ROOT/config/token.json" ]]; then
  say ""
  say "Opening Google sign-in (pick the account that owns the calendar)..."
  "$ROOT/venv/bin/python3" "$ROOT/bot/auth_google_calendar.py" || true
else
  say "${GREEN}  ok${RESET} Google Calendar already signed in"
  read -r -p "Re-sign in to Google Calendar? [y/N] " redo
  if [[ "$redo" =~ ^[Yy]$ ]]; then
    "$ROOT/venv/bin/python3" "$ROOT/bot/auth_google_calendar.py" || true
  fi
fi

# --- UCF accounts ---
step "3/4  UCF accounts"
count="$(account_count)"
say "You have ${count} account(s). Full 12pm–10pm coverage needs ${BOLD}3${RESET}."
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
  "$ROOT/add-account.sh" || true
  say ""
done

# --- LaunchAgent ---
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
say "  ./start.sh          — menu anytime"
say "  ./run-bot.sh        — test a booking now"
say "  ./sign-in.sh <id>   — refresh a session if login expires"
say ""
