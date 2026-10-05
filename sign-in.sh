#!/usr/bin/env bash
# Refresh LibCal cookies for an account (headed browser + MFA).
# Usage: ./sign-in.sh <account_id>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/venv/bin/python3" ]]; then
  echo "Missing venv. Run ./setup.sh" >&2
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/venv/bin/python3" bot/auth_ucf_account.py "$@"
