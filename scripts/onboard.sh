#!/bin/bash
# Guided first-time setup — calendar, accounts, cron in one flow.
# Usage: ./onboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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

cron_installed() {
  [[ -x "$ROOT/run-bot.sh" ]] && crontab -l 2>/dev/null | grep -qF "$ROOT/run-bot.sh"
}

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
if [[ ! -f "$ROOT/config/credentials.json" ]]; then
  say "Copy your Google OAuth Desktop client JSON to:"
  say "  ${BOLD}$ROOT/config/credentials.json${RESET}"
  say ""
  say "Get it from: Google Cloud Console → APIs & Services → Credentials"
  say "Create an OAuth 2.0 Client ID (Desktop app), download JSON, rename it."
  say ""
  read -r -p "Press Enter when credentials.json is in config/ (or Ctrl+C to exit)... "
  if [[ ! -f "$ROOT/config/credentials.json" ]]; then
    say "${RED}Still missing config/credentials.json — add it and re-run ./onboard.sh${RESET}"
    exit 1
  fi
else
  say "${GREEN}  ok${RESET} config/credentials.json found"
fi

# --- Calendar config ---
step "2/4  Google Calendar"
"$ROOT/scripts/write-config.sh"

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

# --- Cron ---
step "4/4  Auto-booking schedule"
if cron_installed; then
  say "${GREEN}  ok${RESET} Cron already installed"
  crontab -l 2>/dev/null | grep -F "$ROOT/run-bot.sh" | sed 's/^/    /'
else
  say "Install a randomized morning run window (Fri–Tue → books Mon–Fri rooms)?"
  read -r -p "Install cron? [Y/n] " install
  if [[ -z "$install" || "$install" =~ ^[Yy]$ ]]; then
    "$ROOT/install-cron.sh"
  fi
fi

say ""
say "${GREEN}${BOLD}Setup complete.${RESET}"
say ""
say "  ./start.sh          — menu anytime"
say "  ./run-bot.sh        — test a booking now"
say "  ./sign-in.sh <id>   — refresh a session if login expires"
say ""
