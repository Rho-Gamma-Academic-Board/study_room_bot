#!/usr/bin/env bash
# Restore study-room secrets into /workspace after a Cloud Agent git checkout.
# Secrets live outside the repo at ~/.study_room_bot so they survive clone/reset.
# Usage: ./scripts/restore-secrets.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${STUDY_ROOM_SECRETS_CACHE:-$HOME/.study_room_bot}"

if [[ ! -d "$CACHE" ]]; then
  echo "error: secrets cache missing: $CACHE" >&2
  echo "Populate it once on a working VM, then snapshot the environment." >&2
  exit 1
fi

mkdir -p "$ROOT/config" "$ROOT/data/accounts" "$ROOT/data/storage_states"

copied=0
if [[ -f "$CACHE/config/service-account.json" ]]; then
  cp -a "$CACHE/config/service-account.json" "$ROOT/config/service-account.json"
  chmod 600 "$ROOT/config/service-account.json"
  copied=$((copied + 1))
fi
if [[ -f "$CACHE/config/ucf_credentials.env" ]]; then
  cp -a "$CACHE/config/ucf_credentials.env" "$ROOT/config/ucf_credentials.env"
  chmod 600 "$ROOT/config/ucf_credentials.env"
  copied=$((copied + 1))
fi

if [[ -d "$CACHE/data/accounts" ]]; then
  shopt -s nullglob
  for f in "$CACHE/data/accounts"/*.env; do
    base="$(basename "$f")"
    [[ "$base" == example.env || "$base" == *.example ]] && continue
    cp -a "$f" "$ROOT/data/accounts/$base"
    chmod 600 "$ROOT/data/accounts/$base"
    copied=$((copied + 1))
  done
  shopt -u nullglob
fi

if [[ -d "$CACHE/data/storage_states" ]]; then
  shopt -s nullglob
  for f in "$CACHE/data/storage_states"/*.json; do
    base="$(basename "$f")"
    cp -a "$f" "$ROOT/data/storage_states/$base"
    chmod 600 "$ROOT/data/storage_states/$base"
    copied=$((copied + 1))
  done
  shopt -u nullglob
fi

echo "Restored $copied secret file(s) from $CACHE → $ROOT"

# Hard-fail if the essentials for book+scrape are missing.
missing=0
for req in \
  "$ROOT/config/service-account.json" \
  "$ROOT/config/ucf_credentials.env" \
  "$ROOT/data/accounts/Josh.env" \
  "$ROOT/data/storage_states/Josh.json"
do
  if [[ ! -f "$req" ]]; then
    echo "MISSING: $req" >&2
    missing=1
  fi
done
if (( missing )); then
  exit 1
fi
