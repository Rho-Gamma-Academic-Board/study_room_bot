#!/bin/bash
# Remove a booking account (credentials + saved browser session).
# Usage: ./remove-account.sh [account_id]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNTS_DIR="$ROOT/data/accounts"
PROFILES_DIR="$ROOT/data/profiles"
USAGE_FILE="$ROOT/data/account_usage.json"
ACCOUNT_ID="${1:-}"

list_account_ids() {
  {
    if [[ -d "$ACCOUNTS_DIR" ]]; then
      find "$ACCOUNTS_DIR" -maxdepth 1 -name '*.env' ! -name 'example.env' -exec basename {} .env \; 2>/dev/null
    fi
    if [[ -d "$PROFILES_DIR" ]]; then
      find "$PROFILES_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null
    fi
  } | sort -u
}

print_accounts() {
  local ids
  ids="$(list_account_ids)"
  if [[ -n "$ids" ]]; then
    echo "Accounts:"
    while IFS= read -r id; do
      [[ -n "$id" ]] && echo "  - $id"
    done <<< "$ids"
    echo
  else
    echo "No accounts found."
    echo
  fi
}

print_accounts

if [[ -z "$ACCOUNT_ID" ]]; then
  read -r -p "Account id to remove: " ACCOUNT_ID
fi

if [[ -z "$ACCOUNT_ID" ]]; then
  echo "Account id is required."
  exit 1
fi

if [[ "$ACCOUNT_ID" == "example" ]]; then
  echo "Cannot remove the example account template."
  exit 1
fi

ENV_FILE="$ACCOUNTS_DIR/${ACCOUNT_ID}.env"
PROFILE_DIR="$PROFILES_DIR/${ACCOUNT_ID}"

if [[ ! -f "$ENV_FILE" && ! -d "$PROFILE_DIR" ]]; then
  echo "No account found for '${ACCOUNT_ID}'."
  exit 1
fi

echo "This will remove:"
[[ -f "$ENV_FILE" ]] && echo "  - $ENV_FILE"
[[ -d "$PROFILE_DIR" ]] && echo "  - $PROFILE_DIR/"
echo "  - usage entry in data/account_usage.json (if present)"
echo
read -r -p "Remove account '${ACCOUNT_ID}'? [y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

if [[ -f "$ENV_FILE" ]]; then
  rm -f "$ENV_FILE"
  echo "Removed $ENV_FILE"
fi

if [[ -d "$PROFILE_DIR" ]]; then
  rm -rf "$PROFILE_DIR"
  echo "Removed $PROFILE_DIR"
fi

if [[ -f "$USAGE_FILE" ]]; then
  "$ROOT/venv/bin/python3" - "$ACCOUNT_ID" "$USAGE_FILE" <<'PY'
import json
import sys
from pathlib import Path

account_id = sys.argv[1]
path = Path(sys.argv[2])
data = json.loads(path.read_text(encoding="utf-8"))
if account_id in data:
    del data[account_id]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Cleared usage for {account_id}")
PY
fi

echo "Done."
