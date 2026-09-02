#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec ./venv/bin/python3 bot/auth_ucf_account.py "$@"
