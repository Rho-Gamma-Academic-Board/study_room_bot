#!/usr/bin/env bash
# Cloud Agent install: deps + restore secrets that live outside /workspace.
# Safe to re-run. Usage: ./scripts/cloud-install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

"$ROOT/setup.sh"
"$ROOT/scripts/restore-secrets.sh"

echo "cloud-install complete"
