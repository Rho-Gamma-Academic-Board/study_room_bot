#!/usr/bin/env bash
# Scrape board Outlook → Google Calendar (check-in codes).
# Usage: ./scrape-outlook.sh [--once] [--wait N]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$ROOT/venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

# Default to a single pass when no flags given.
if [[ $# -eq 0 ]]; then
  set -- --once
fi

exec "$ROOT/venv/bin/python3" bot/outlook_watcher.py "$@"
