#!/bin/bash
# One-line installer for macOS (always-on Mac mini).
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Rho-Gamma-Academic-Board/study_room_bot/main/install.sh)"
#
# Clones (or updates) the repo, sets up Python/Playwright, then opens the menu.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Rho-Gamma-Academic-Board/study_room_bot.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/study_room_bot}"

BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
GOLD='\033[38;5;220m'; RED='\033[38;5;196m'; GREEN='\033[38;5;82m'

info()  { printf "%b\n" "${GOLD}==>${RESET} ${BOLD}$1${RESET}"; }
ok()    { printf "%b\n" "${GREEN}  ok${RESET} ${DIM}$1${RESET}"; }
die()   { printf "%b\n" "${RED}error:${RESET} $1" >&2; exit 1; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "This installer is macOS only (use an always-on Mac mini)."
fi

# When run through a pipe, stdin is the script itself. Reattach the terminal
# so the interactive menu and password prompts still work.
if [[ ! -t 0 ]] && (exec < /dev/tty) 2>/dev/null; then
  exec < /dev/tty
fi

bootstrap_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    info "Installing git via Homebrew"
    brew install git
    return 0
  fi
  die "git is required. Install Xcode Command Line Tools: xcode-select --install"
}

info "Checking prerequisites"
bootstrap_git
command -v git >/dev/null 2>&1 || die "git is required"
ok "git found"

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
chmod +x ./*.sh scripts/*.sh 2>/dev/null || true

info "Setting up Python, Playwright, and Chromium"
./setup.sh
ok "environment ready"

# shellcheck source=scripts/launchd.sh
source "./scripts/launchd.sh"

printf '\n'
if [[ ! -f config/credentials.json || ! -f config/token.json ]] \
  || [[ "$(find data/accounts -maxdepth 1 -name '*.env' ! -name 'example.env' 2>/dev/null | wc -l | tr -d ' ')" -lt 1 ]] \
  || ! launchd_installed; then
  info "Launching setup wizard"
  exec ./onboard.sh
fi

info "Launching menu"
exec ./start.sh
