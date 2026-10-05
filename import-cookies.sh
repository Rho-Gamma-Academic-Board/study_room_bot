#!/usr/bin/env bash
# Import Playwright LibCal cookies (storageState JSON). No passwords stored.
# Usage:
#   ./import-cookies.sh <nickname> /path/to/authState.json
#   ./import-cookies.sh   # prompts for nickname + path
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ACCOUNT_ID="${1:-}"
COOKIE_FILE="${2:-}"
EXTRA=()
if [[ $# -gt 2 ]]; then
  EXTRA=("${@:3}")
fi

if [[ -z "$ACCOUNT_ID" ]]; then
  while [[ -z "$ACCOUNT_ID" ]]; do
    read -r -p "Nickname: " ACCOUNT_ID
  done
fi

if [[ -z "$COOKIE_FILE" ]]; then
  while [[ -z "$COOKIE_FILE" ]]; do
    read -r -p "Path to cookie JSON (Playwright storageState): " COOKIE_FILE
  done
fi

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/venv/bin/python3" bot/import_cookies.py "$ACCOUNT_ID" "$COOKIE_FILE" "${EXTRA[@]}"
