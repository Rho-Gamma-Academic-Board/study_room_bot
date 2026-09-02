#!/bin/bash
# First-time setup on Linux (Raspberry Pi) or macOS.
# Creates the venv, installs Python dependencies, Playwright, and Chromium.
# Safe to run repeatedly (idempotent). Usage: ./setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/ensure-system.sh
source "$ROOT/scripts/ensure-system.sh"

step() { printf '\n==> %s\n' "$1"; }
die()  { printf 'error: %s\n' "$1" >&2; exit 1; }

step "Checking system packages"
ensure_system_packages
echo "    $(python3 --version)"

step "Creating virtual environment"
if [[ -x "venv/bin/python3" ]]; then
  echo "    venv already exists — reusing it"
else
  rm -rf venv
  python3 -m venv venv || die "Failed to create venv"
  echo "    created ./venv"
fi

step "Installing Python dependencies"
./venv/bin/python3 -m pip install --upgrade pip --quiet
./venv/bin/python3 -m pip install -r requirements.txt --quiet
grep -v '^\s*#' requirements.txt | grep -v '^\s*$' | sed 's/^/    /'

step "Verifying Python packages"
./venv/bin/python3 - <<'PY' || exit 1
import importlib.util
import sys

missing = [
    name
    for name in ("playwright", "googleapiclient", "google_auth_oauthlib")
    if importlib.util.find_spec(name) is None
]
if missing:
    print("error: missing packages after install: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
print("    all Python packages present")
PY

install_chromium_stack() {
  if [[ "$(uname -s)" == "Linux" ]]; then
    step "Installing Chromium system libraries (sudo may prompt)"
    run_privileged ./venv/bin/playwright install-deps chromium
  fi

  step "Installing Playwright Chromium browser"
  ./venv/bin/playwright install chromium
}

chromium_launches() {
  ./venv/bin/python3 - <<'PY'
import sys
from playwright.sync_api import sync_playwright

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser.close()
except Exception as exc:
    print(f"error: Chromium launch failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
}

install_chromium_stack

step "Verifying Chromium launches"
if ! chromium_launches; then
  echo "    Chromium failed — reinstalling browser stack and retrying..."
  install_chromium_stack
  chromium_launches || die "Chromium still will not launch. Check logs above."
fi
echo "    Chromium launches OK"

if [[ ! -f config/ucf_credentials.env ]]; then
  step "Creating config/ucf_credentials.env"
  mkdir -p config data/accounts data/profiles logs
  cp config/ucf_credentials.env.example config/ucf_credentials.env
  echo "    created from example — edit before running"
fi

chmod +x ./*.sh scripts/*.sh 2>/dev/null || true

cat <<'EOF'

Setup complete. Next steps:
  ./start.sh                              # interactive menu
  1. Edit config/ucf_credentials.env
  2. Add config/credentials.json (Google OAuth)
  3. ./add-account.sh                     # browser sign-in, SMS 2FA on Pi
  4. ./venv/bin/python3 bot/auth_google_calendar.py
  5. ./install-cron.sh
EOF
