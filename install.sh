#!/bin/bash
# One-line installer.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Rho-Gamma-Academic-Board/study_room_bot/main/install.sh)"
#
# Clones (or updates) the repo, runs setup, then opens the menu.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Rho-Gamma-Academic-Board/study_room_bot.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/study_room_bot}"

BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
GOLD='\033[38;5;220m'; RED='\033[38;5;196m'; GREEN='\033[38;5;82m'

info()  { printf "%b\n" "${GOLD}==>${RESET} ${BOLD}$1${RESET}"; }
ok()    { printf "%b\n" "${GREEN}  ok${RESET} ${DIM}$1${RESET}"; }
die()   { printf "%b\n" "${RED}error:${RESET} $1" >&2; exit 1; }

# When run through a pipe, stdin is the script itself. Reattach the terminal
# so the interactive menu and password prompts still work. The subshell probe
# keeps this from aborting where there is no controlling terminal (cron, CI).
if [[ ! -t 0 ]] && (exec < /dev/tty) 2>/dev/null; then
  exec < /dev/tty
fi

info "Checking prerequisites"
command -v git >/dev/null 2>&1 || die "git is required. On Raspberry Pi OS: sudo apt install git"
command -v python3 >/dev/null 2>&1 || die "python3 is required. On Raspberry Pi OS: sudo apt install python3 python3-venv"
ok "git and python3 found"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
  ok "up to date"
elif [[ -e "$INSTALL_DIR" ]]; then
  die "$INSTALL_DIR already exists and is not a git checkout. Move it or set INSTALL_DIR."
else
  info "Cloning into $INSTALL_DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  ok "cloned"
fi

cd "$INSTALL_DIR"
chmod +x ./*.sh 2>/dev/null || true

# Run setup unless a working venv with the dependencies is already in place.
venv_ready() {
  [[ -x ./venv/bin/python3 ]] || return 1
  ./venv/bin/python3 - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

sys.exit(0 if all(importlib.util.find_spec(m) for m in
    ("playwright", "googleapiclient", "google_auth_oauthlib")) else 1)
PY
}

if venv_ready; then
  ok "venv and dependencies already installed"
else
  info "Installing venv, Python dependencies, and Chromium"
  ./setup.sh
  venv_ready || die "setup finished but dependencies are still missing"
  ok "dependencies installed"
fi

printf '\n'
info "Launching menu"
printf '\n'
exec ./start.sh
