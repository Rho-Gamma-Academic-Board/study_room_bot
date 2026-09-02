#!/bin/bash
# First-time setup on macOS.
# Creates the venv, installs Python dependencies, Playwright, and Chromium.
# Safe to run repeatedly (idempotent). Usage: ./setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$1"; }
die()  { printf 'error: %s\n' "$1" >&2; exit 1; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "setup.sh is macOS only"
fi

ensure_python() {
  if python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    step "Installing Python via Homebrew"
    brew install python3
    return 0
  fi
  die "Python 3 with venv is required. Run: xcode-select --install (or install Homebrew)"
}

step "Checking Python"
command -v python3 >/dev/null 2>&1 || ensure_python
ensure_python
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

step "Installing Playwright Chromium browser"
./venv/bin/playwright install chromium

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

step "Verifying Chromium launches"
if ! chromium_launches; then
  echo "    Chromium failed — reinstalling and retrying..."
  ./venv/bin/playwright install chromium
  chromium_launches || die "Chromium still will not launch. Check logs above."
fi
echo "    Chromium launches OK"

if [[ ! -f config/ucf_credentials.env ]]; then
  step "Creating config/ucf_credentials.env"
  mkdir -p config data/accounts data/profiles logs
  cp config/ucf_credentials.env.example config/ucf_credentials.env
  chmod 600 config/ucf_credentials.env
  echo "    using org defaults (Academic Board - Study Rooms)"
fi

chmod +x ./*.sh scripts/*.sh 2>/dev/null || true

cat <<'EOF'

Setup complete. Next steps:
  ./start.sh                              # interactive menu
  ./onboard.sh                            # guided wizard
  ./import-google-credentials.sh          # paste Google OAuth JSON
  ./add-account.sh                        # browser sign-in (iMessage 2FA)
  ./install-launchd.sh                    # schedule auto-booking
EOF
