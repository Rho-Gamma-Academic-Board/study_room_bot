#!/bin/bash
# Create data/accounts/<id>.env and sign in to save browser cookies.
# Usage: ./add-account.sh [account_id]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNTS_DIR="$ROOT/data/accounts"
ACCOUNT_ID="${1:-}"

if [[ -z "$ACCOUNT_ID" ]]; then
  printf '\n'
  while [[ -z "$ACCOUNT_ID" ]]; do
    read -r -p "Nickname: " ACCOUNT_ID
    if [[ -z "$ACCOUNT_ID" ]]; then
      echo "Nickname is required."
    fi
  done
fi

if [[ -z "$ACCOUNT_ID" ]]; then
  echo "Account id is required."
  exit 1
fi

if [[ ! "$ACCOUNT_ID" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
  echo "Account id must start with a letter and use only letters, numbers, _ or -"
  exit 1
fi

if [[ "$ACCOUNT_ID" == "example" ]]; then
  echo "Pick a different id than 'example'"
  exit 1
fi

ENV_FILE="$ACCOUNTS_DIR/${ACCOUNT_ID}.env"

if [[ -f "$ENV_FILE" ]]; then
  read -r -p "Overwrite ${ACCOUNT_ID}? [y/N] " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    exec "$ROOT/sign-in.sh" "$ACCOUNT_ID"
  fi
fi

read -r -p "UCF email: " UCF_EMAIL
read -r -s -p "UCF password: " UCF_PASSWORD
echo
read -r -p "UCF ID: " UCF_ID

if [[ -z "$UCF_EMAIL" || -z "$UCF_PASSWORD" || -z "$UCF_ID" ]]; then
  echo "All fields are required."
  exit 1
fi

mkdir -p "$ACCOUNTS_DIR"
cat > "$ENV_FILE" <<EOF
UCF_EMAIL=${UCF_EMAIL}
UCF_PASSWORD=${UCF_PASSWORD}
UCF_ID=${UCF_ID}
EOF

chmod 600 "$ENV_FILE"

exec "$ROOT/sign-in.sh" "$ACCOUNT_ID"
