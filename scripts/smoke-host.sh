#!/usr/bin/env bash
# Local smoke checks for intake + Outlook scrape wiring (no live booking).
# Usage: ./scripts/smoke-host.sh [intake-base-url]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${1:-http://127.0.0.1:8790}"
BASE="${BASE%/}"

echo "== Smoke: project files =="
test -f "$ROOT/bot/outlook_watcher.py"
test -f "$ROOT/bot/auth_board_outlook.py"
test -f "$ROOT/scrape-outlook.sh"
test -f "$ROOT/api/main.py"
echo "ok files"

echo "== Smoke: Python imports =="
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
cd "$ROOT/bot"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import outlook_watcher as ow
from shared.accounts import find_account

acct = ow.resolve_board_account()
print("board_account:", acct.id if acct else "(none — run auth_board_outlook.py)")
print("find_account('board'):", find_account("board"))
print("ok imports")
PY

echo "== Smoke: intake health =="
if curl -fsS "${BASE}/api/health" | python3 -m json.tool; then
  echo "ok health at $BASE"
else
  echo "WARN: intake not reachable at $BASE — start ./start-intake.sh"
  exit 0
fi

echo
echo "UI is the chapter site (/academic/study-rooms), not this API."
echo "Local: STUDY_ROOM_INTAKE_URL=$BASE in academic-board .env.local"
echo "Prod: Vercel STUDY_ROOM_INTAKE_URL=<Funnel HTTPS> + Mac awake"
