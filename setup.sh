#!/bin/bash
# First-time setup on Linux (Raspberry Pi) or macOS.
# Creates the venv, installs Python dependencies, and installs Chromium.
# Usage: ./setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$1"; }
die()  { printf 'error: %s\n' "$1" >&2; exit 1; }

APT_HINT="sudo apt update && sudo apt install -y python3 python3-venv python3-pip"

step "Checking Python"
command -v python3 >/dev/null 2>&1 || die "python3 is required. Install it with: $APT_HINT"

# python3-venv is a separate package on Debian/Raspberry Pi OS and its absence
# is the most common setup failure, so check for it up front.
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  die "python3 venv module is missing. Install it with: $APT_HINT"
fi
echo "    $(python3 --version)"

step "Creating virtual environment"
if [[ -x "venv/bin/python3" ]]; then
  echo "    venv already exists — reusing it"
else
  rm -rf venv
  python3 -m venv venv || die "Failed to create venv. Try: $APT_HINT"
  echo "    created ./venv"
fi

step "Installing Python dependencies"
./venv/bin/python3 -m pip install --upgrade pip --quiet
./venv/bin/python3 -m pip install -r requirements.txt --quiet
grep -v '^\s*#' requirements.txt | grep -v '^\s*$' | sed 's/^/    /'

step "Verifying dependencies"
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

if [[ "$(uname -s)" == "Linux" ]]; then
  step "Installing Chromium system libraries (needs sudo)"
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null || [[ -t 0 ]]; then
      sudo ./venv/bin/playwright install-deps chromium || {
        echo "    could not install system libraries automatically"
        echo "    run manually: sudo ./venv/bin/playwright install-deps chromium"
      }
    else
      echo "    skipped (no terminal for the sudo prompt)"
      echo "    run manually: sudo ./venv/bin/playwright install-deps chromium"
    fi
  else
    echo "    sudo not found — run as root: ./venv/bin/playwright install-deps chromium"
  fi
fi

step "Installing Playwright Chromium"
./venv/bin/playwright install chromium

if [[ ! -f ucf_credentials.env ]]; then
  step "Creating ucf_credentials.env"
  cp ucf_credentials.env.example ucf_credentials.env
  echo "    created from example — edit before running"
fi

chmod +x ./*.sh 2>/dev/null || true

cat <<'EOF'

Setup complete. Next steps:
  ./start.sh                              # interactive menu
  1. Edit ucf_credentials.env
  2. Add credentials.json (Google OAuth)
  3. ./add-account.sh                     # browser sign-in, SMS 2FA on Pi
  4. ./venv/bin/python3 auth_google_calendar.py
  5. ./install-cron.sh
EOF
