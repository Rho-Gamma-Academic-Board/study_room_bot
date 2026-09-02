#!/bin/bash
# Ensure config/ucf_credentials.env exists with org defaults (no prompts).
# Usage: ./scripts/write-config.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/config/ucf_credentials.env"
EXAMPLE="$ROOT/config/ucf_credentials.env.example"

mkdir -p "$ROOT/config"

if [[ -f "$ENV_FILE" ]]; then
  exit 0
fi

if [[ ! -f "$EXAMPLE" ]]; then
  echo "error: missing $EXAMPLE" >&2
  exit 1
fi

cp "$EXAMPLE" "$ENV_FILE"
chmod 600 "$ENV_FILE"
