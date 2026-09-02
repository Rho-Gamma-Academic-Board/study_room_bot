#!/bin/bash
# Create data/accounts/<id>.env and sign in to save browser cookies.
# Usage: ./add-account.sh [account_id]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNTS_DIR="$ROOT/data/accounts"
ACCOUNT_ID="${1:-}"

random_nickname() {
  local names=(atlas cedar ember maple nova pigeon ripple summit willow)
  local pick="${names[$((RANDOM % ${#names[@]}))]}"
  echo "${pick}$((10 + RANDOM % 90))"
}

if [[ -z "$ACCOUNT_ID" ]]; then
  echo
  echo "Add a UCF account. You'll need:"
  echo "  • UCF email, password, and ID"
  echo "  • A nickname (anything — doesn't have to be a real name)"
  echo "  • Browser access for SMS 2FA during sign-in"
  echo
  read -r -p "Nickname (Enter for random): " ACCOUNT_ID
  if [[ -z "$ACCOUNT_ID" ]]; then
    ACCOUNT_ID="$(random_nickname)"
    echo "Using nickname: $ACCOUNT_ID"
  fi
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
  read -r -p "data/accounts/${ACCOUNT_ID}.env already exists. Overwrite? [y/N] " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "Keeping existing file. Opening sign-in..."
    exec "$ROOT/sign-in.sh" "$ACCOUNT_ID"
  fi
fi

echo "Creating account: $ACCOUNT_ID"
echo

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

echo
echo "Wrote $ENV_FILE"
echo "They'll enter their public name during sign-in."
echo "Starting sign-in..."
echo

exec "$ROOT/sign-in.sh" "$ACCOUNT_ID"
