#!/bin/bash
# Interactive launcher — run after git clone or pull.
# Usage: ./start.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RUN_BOT="$ROOT/run-bot.sh"

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
  find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' ! -name 'example.env' 2>/dev/null | wc -l | tr -d ' '
}

onboarding_needed() {
  [[ ! -f "$ROOT/config/credentials.json" ]] \
    || [[ ! -f "$ROOT/config/token.json" ]] \
    || [[ "$(account_count)" -lt 1 ]] \
    || ! crontab -l 2>/dev/null | grep -qF "$RUN_BOT"
}

prompt_onboard() {
  if ! is_setup_done || ! onboarding_needed; then
    return 0
  fi

  line '─'
  say " ${WHITE}First-time setup? Run the guided wizard (calendar + accounts + cron).${RESET}"
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

show_cron_status() {
  section_title "CRON SCHEDULE"

  if ! crontab -l >/dev/null 2>&1; then
    status_warn "No crontab for this user"
    say " ${DIM}→ Use ${GOLD}[ 4 ]${DIM} to install (randomized morning window)${RESET}"
    return
  fi

  local cron_lines
  cron_lines="$(crontab -l 2>/dev/null | grep -F "$RUN_BOT" || true)"
  if [[ -n "$cron_lines" ]]; then
    status_ok "Study room bot scheduled"
    while IFS= read -r entry; do
      say "   ${GOLD}${entry}${RESET}"
    done <<< "$cron_lines"
    printf '\n'
    if [[ -f "$ROOT/config/cron.env" ]]; then
      # shellcheck disable=SC1090
      source "$ROOT/config/cron.env"
      local end_min=$((CRON_BASE_MINUTE + CRON_JITTER_MINUTES))
      local end_hour=${CRON_BASE_HOUR:-7}
      if (( end_min >= 60 )); then
        end_min=$((end_min % 60))
        end_hour=$((end_hour + 1))
      fi
      say " ${DIM}Random window: ~$(printf '%02d:%02d' "$CRON_BASE_HOUR" "$CRON_BASE_MINUTE")–$(printf '%02d:%02d' "$end_hour" "$end_min") (varies daily)${RESET}"
    fi
    say " ${DIM}Fri–Tue trigger → books Mon–Fri (3 days ahead)${RESET}"
    say " ${DIM}Logs: ${GOLD_DIM}logs/study_room_bot.log${RESET}"
  else
    status_warn "No study room cron job installed"
    say " ${DIM}→ Use ${GOLD}[ 4 ]${DIM} to install (randomized morning window)${RESET}"
  fi

  local other
  other="$(crontab -l 2>/dev/null | grep -v -F "$RUN_BOT" | grep -v '^#' | grep -v '^[[:space:]]*$' || true)"
  if [[ -n "$other" ]]; then
    printf '\n'
    say " ${GOLD_DIM}Other cron jobs:${RESET}"
    while IFS= read -r entry; do
      say "   ${DIM}${entry}${RESET}"
    done <<< "$other"
  fi
}

list_accounts() {
  section_title "ACCOUNTS"

  local ids
  ids="$(
    {
      if [[ -d "$ROOT/data/accounts" ]]; then
        find "$ROOT/data/accounts" -maxdepth 1 -name '*.env' ! -name 'example.env' -exec basename {} .env \; 2>/dev/null
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

  if [[ -f "$ROOT/config/credentials.json" ]]; then
    status_ok "Google OAuth credentials found"
  else
    status_warn "Missing config/credentials.json"
  fi

  if [[ -f "$ROOT/config/token.json" ]]; then
    status_ok "Google Calendar signed in"
  else
    status_warn "Google Calendar not signed in"
  fi

  list_accounts
  show_cron_status
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

  menu_item "1" "SHOW STATUS" "accounts, cron, auth"
  menu_item "2" "ADD ACCOUNT" "new UCF login + browser sign-in"
  menu_item "3" "REMOVE ACCOUNT" "delete credentials + profile"
  menu_item "4" "INSTALL CRON" "randomized morning window"
  menu_item "5" "UNINSTALL CRON" "remove scheduled runs"
  menu_item "6" "RUN BOT ONCE" "test booking now"
  menu_item "7" "GOOGLE CALENDAR" "OAuth sign-in"
  menu_item "8" "RE-SIGN IN UCF" "refresh browser session"
  menu_item "9" "SETUP WIZARD" "first-time: calendar, accounts, cron"
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
      "$ROOT/add-account.sh" || true
      ;;
    3)
      "$ROOT/remove-account.sh" || true
      ;;
    4)
      "$ROOT/install-cron.sh" || true
      ;;
    5)
      "$ROOT/uninstall-cron.sh" || true
      ;;
    6)
      "$ROOT/run-bot.sh" || true
      say " ${GREEN}Done.${RESET} Check ${GOLD_DIM}logs/study_room_bot.log${RESET} for output."
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
        printf "%b" "${PAD} ${GOLD}Account id to sign in:${RESET} "
        read -r account_id
        if [[ -n "$account_id" ]]; then
          "$ROOT/sign-in.sh" "$account_id" || true
        fi
      fi
      ;;
    9)
      "$ROOT/onboard.sh" || true
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
