#!/bin/bash
# Interactive launcher — run after git clone or pull.
# Usage: ./start.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/launchd.sh
source "$ROOT/scripts/launchd.sh"

# Width of the whole UI column. Everything is drawn inside this and the
# column is centered on the terminal.
UI_WIDTH=72
PAD=""

# Colors (gold + red theme)
if [[ -t 1 ]]; then
  RESET='\033[0m'
  BOLD='\033[1m'
  DIM='\033[2m'
  GOLD='\033[38;5;220m'
  GOLD_BRIGHT='\033[38;5;226m'
  GOLD_DIM='\033[38;5;179m'
  RED='\033[38;5;196m'
  RED_BRIGHT='\033[38;5;203m'
  RED_DARK='\033[38;5;124m'
  WHITE='\033[97m'
  GREEN='\033[38;5;82m'
else
  RESET='' BOLD='' DIM='' GOLD='' GOLD_BRIGHT='' GOLD_DIM=''
  RED='' RED_BRIGHT='' RED_DARK='' WHITE='' GREEN=''
fi

repeat() {
  local char="$1" count="$2" out="" i
  for ((i = 0; i < count; i++)); do
    out+="$char"
  done
  printf '%s' "$out"
}

# Recompute the left margin that centers UI_WIDTH on the current terminal.
compute_pad() {
  local cols
  cols="$(tput cols 2>/dev/null || echo 80)"
  [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
  local margin=$(( (cols - UI_WIDTH) / 2 ))
  ((margin < 0)) && margin=0
  PAD="$(repeat ' ' "$margin")"
}

# Print one line inside the centered column.
say() {
  printf "%b\n" "${PAD}${1-}"
}

# Pad an ASCII string with spaces so it is centered in `width` columns.
pad_center() {
  local text="$1" width="$2"
  local len=${#text}
  local left=$(( (width - len) / 2 ))
  ((left < 0)) && left=0
  local right=$(( width - len - left ))
  ((right < 0)) && right=0
  printf '%s%s%s' "$(repeat ' ' "$left")" "$text" "$(repeat ' ' "$right")"
}

line() {
  local char="${1:-═}"
  say "${RED}$(repeat "$char" "$UI_WIDTH")${RESET}"
}

section_title() {
  printf '\n'
  line '═'
  say " ${GOLD_BRIGHT}${BOLD}$1${RESET}"
  line '─'
}

menu_item() {
  local num="$1" label="$2" sub="${3:-}"
  local text="  ${RED}┃${RESET}  ${GOLD_BRIGHT}${BOLD}[ $num ]${RESET}  ${WHITE}${BOLD}${label}${RESET}"
  [[ -n "$sub" ]] && text+="  ${DIM}${sub}${RESET}"
  say "$text"
}

# Each banner row below is exactly 70 visible columns between the frame
# edges. Never pad these with printf field widths — printf counts bytes and
# the box-drawing characters are multi-byte.
banner_row() {
  say "${RED}${BOLD}║${1}${RED}${BOLD}║${RESET}"
}

show_banner() {
  compute_pad
  printf '\n'
  say "${RED}${BOLD}╔$(repeat '═' 70)╗${RESET}"
  banner_row "                                                                      "
  banner_row "${GOLD}                 ██████████████      ██████████████████               "
  banner_row "${GOLD}                ████████████████     ██████████████████               "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD_BRIGHT}               ████          ████          ██████                     "
  banner_row "${GOLD}                ████████████████           ██████                     "
  banner_row "${GOLD}                 ██████████████            ██████                     "
  banner_row "                                                                      "
  banner_row "${RED_BRIGHT}       ───────────────  S T U D Y   R O O M S  ───────────────        "
  banner_row "                                                                      "
  say "${RED}${BOLD}╚$(repeat '═' 70)╝${RESET}"
  printf '\n'
}

is_setup_done() {
  [[ -x "$ROOT/venv/bin/python3" ]]
}

account_count() {
  if [[ ! -d "$ROOT/data/accounts" ]]; then
    echo 0
    return
  fi
  find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' ! -name 'example.env' ! -name '*.example' 2>/dev/null | wc -l | tr -d ' '
}

onboarding_needed() {
  [[ ! -f "$ROOT/config/service-account.json" ]] \
    || [[ "$(account_count)" -lt 1 ]] \
    || ! launchd_installed
}

prompt_onboard() {
  if ! is_setup_done || ! onboarding_needed; then
    return 0
  fi

  line '─'
  say " ${WHITE}First-time setup? Run the guided wizard (calendar + accounts + schedule).${RESET}"
  printf "%b" "${PAD} ${GOLD}Run ./onboard.sh now? [Y/n]${RESET} "
  read -r ans
  if [[ -z "$ans" || "$ans" =~ ^[Yy]$ ]]; then
    "$ROOT/onboard.sh" || true
    printf '\n'
    printf "%b" "${PAD} ${DIM}Press Enter to continue...${RESET}"
    read -r
  else
    say " ${DIM}Run ./onboard.sh anytime, or use menu [ 9 ].${RESET}"
    printf '\n'
  fi
}

status_ok() {
  say " ${GREEN}●${RESET} $1"
}

status_warn() {
  say " ${RED}●${RESET} $1"
}

show_schedule_status() {
  section_title "AUTO-BOOKING SCHEDULE"

  if launchd_installed; then
    status_ok "LaunchAgent installed"
    say "   ${GOLD}$(launchd_plist_path)${RESET}"
    printf '\n'
    if [[ -f "$ROOT/config/schedule.env" ]]; then
      # shellcheck disable=SC1090
      source "$ROOT/config/schedule.env"
      local end_min=$((SCHEDULE_BASE_MINUTE + SCHEDULE_JITTER_MINUTES))
      local end_hour=${SCHEDULE_BASE_HOUR:-7}
      if (( end_min >= 60 )); then
        end_min=$((end_min % 60))
        end_hour=$((end_hour + 1))
      fi
      say " ${DIM}Random window: ~$(printf '%02d:%02d' "$SCHEDULE_BASE_HOUR" "$SCHEDULE_BASE_MINUTE")–$(printf '%02d:%02d' "$end_hour" "$end_min") (varies daily)${RESET}"
    fi
    say " ${DIM}Fri–Tue trigger → books Mon–Fri (3 days ahead)${RESET}"
    say " ${DIM}Logs: ${GOLD_DIM}logs/study_room_bot.log${RESET}"
  else
    status_warn "No LaunchAgent installed"
    say " ${DIM}→ Use ${GOLD}[ 4 ]${DIM} to install (randomized morning window)${RESET}"
  fi
}

list_accounts() {
  section_title "ACCOUNTS"

  local ids
  ids="$(
    {
      if [[ -d "$ROOT/data/accounts" ]]; then
        find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' ! -name 'example.env' ! -name '*.example' -exec basename {} .env \; 2>/dev/null
      fi
      if [[ -d "$ROOT/data/profiles" ]]; then
        find "$ROOT/data/profiles" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null
      fi
    } | sort -u
  )"
  if [[ -n "$ids" ]]; then
    while IFS= read -r id; do
      [[ -n "$id" ]] && say " ${GOLD}▸${RESET} ${WHITE}${BOLD}${id}${RESET}"
    done <<< "$ids"
  else
    status_warn "No accounts yet"
    say " ${DIM}→ Use ${GOLD}[ 2 ]${DIM} to add an account${RESET}"
  fi
}

show_status() {
  compute_pad
  section_title "SYSTEM STATUS"

  if is_setup_done; then
    status_ok "Setup complete — venv ready"
  else
    status_warn "Dependencies missing — run ./setup.sh"
  fi

  if [[ -f "$ROOT/config/service-account.json" ]]; then
    status_ok "Google Calendar service account found"
  else
    status_warn "Missing config/service-account.json"
    say " ${DIM}→ Place SA JSON, share calendar, set STUDY_ROOMS_CALENDAR_ID${RESET}"
  fi

  if [[ -f "$ROOT/config/ucf_credentials.env" ]] \
    && grep -q '^STUDY_ROOMS_CALENDAR_ID=.' "$ROOT/config/ucf_credentials.env" 2>/dev/null; then
    status_ok "STUDY_ROOMS_CALENDAR_ID set"
  else
    status_warn "STUDY_ROOMS_CALENDAR_ID not set in ucf_credentials.env"
  fi

  list_accounts
  show_schedule_status
}

prompt_setup() {
  if is_setup_done; then
    return 0
  fi

  line '─'
  say " ${WHITE}First-time setup has not been run yet.${RESET}"
  printf "%b" "${PAD} ${GOLD}Run ./setup.sh now? [Y/n]${RESET} "
  read -r ans
  if [[ -z "$ans" || "$ans" =~ ^[Yy]$ ]]; then
    "$ROOT/setup.sh" || true
    printf '\n'
    printf "%b" "${PAD} ${DIM}Press Enter to continue...${RESET}"
    read -r
  else
    say " ${DIM}Skipping setup — some options won't work until you run ./setup.sh${RESET}"
    printf '\n'
  fi
}

show_menu() {
  printf '\n'
  say "${RED}${BOLD}╔$(repeat '═' 70)╗${RESET}"
  say "${RED}${BOLD}║${GOLD_BRIGHT}${BOLD}$(pad_center 'M A I N   M E N U' 70)${RED}${BOLD}║${RESET}"
  say "${RED}${BOLD}╚$(repeat '═' 70)╝${RESET}"
  printf '\n'

  menu_item "1" "SHOW STATUS" "accounts, schedule, auth"
  menu_item "2" "IMPORT COOKIES" "LibCal storageState JSON (or use intake site)"
  menu_item "3" "REMOVE ACCOUNT" "delete account + cookies"
  menu_item "4" "INSTALL SCHEDULE" "LaunchAgent morning window"
  menu_item "5" "UNINSTALL SCHEDULE" "remove LaunchAgent"
  menu_item "6" "RUN BOT NOW" "book rooms (live output)"
  menu_item "7" "GOOGLE CALENDAR" "verify service account access"
  menu_item "8" "SCRAPE OUTLOOK" "board Inbox → calendar check-in codes"
  menu_item "9" "INTAKE API" "start API on :8790 (UI is chapter site)"
  say "  ${RED}┃${RESET}"
  menu_item "0" "EXIT" ""

  printf '\n'
  line '─'
  printf "%b" "${PAD} ${GOLD_BRIGHT}${BOLD}▶${RESET}  ${WHITE}Choose an option:${RESET} "
}

run_choice() {
  local choice="$1"

  case "$choice" in
    1)
      show_status
      ;;
    2)
      "$ROOT/import-cookies.sh" || true
      ;;
    3)
      "$ROOT/remove-account.sh" || true
      ;;
    4)
      "$ROOT/install-launchd.sh" || true
      ;;
    5)
      "$ROOT/uninstall-launchd.sh" || true
      ;;
    6)
      "$ROOT/run-bot.sh" --now || true
      ;;
    7)
      if ! is_setup_done; then
        status_warn "Dependencies missing — run ./setup.sh"
      else
        "$ROOT/venv/bin/python3" "$ROOT/bot/auth_google_calendar.py" || true
      fi
      ;;
    8)
      if ! is_setup_done; then
        status_warn "Dependencies missing — run ./setup.sh"
      else
        "$ROOT/scrape-outlook.sh" --once || true
      fi
      ;;
    9)
      "$ROOT/start-intake.sh" || true
      ;;
    0|q|Q)
      printf '\n'
      line '═'
      say "${GOLD_BRIGHT}${BOLD}$(pad_center 'See you in the study room.' "$UI_WIDTH")${RESET}"
      line '═'
      printf '\n'
      exit 0
      ;;
    *)
      say " ${RED}Invalid choice.${RESET} Pick 0–9."
      ;;
  esac
}

main() {
  # Reattach the terminal when piped in (curl | bash) so prompts still work.
  # The subshell probe avoids aborting where there is no controlling terminal.
  if [[ ! -t 0 ]] && (exec < /dev/tty) 2>/dev/null; then
    exec < /dev/tty
  fi

  show_banner
  prompt_setup
  prompt_onboard

  while true; do
    show_status
    show_menu
    read -r choice || { printf '\n'; exit 0; }
    printf '\n'
    run_choice "$choice"
    printf '\n'
    printf "%b" "${PAD} ${DIM}Press Enter to continue...${RESET}"
    read -r || { printf '\n'; exit 0; }
    clear 2>/dev/null || printf '\033[2J\033[H'
    show_banner
  done
}

main
