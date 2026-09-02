#!/bin/bash
# Save Google OAuth Desktop client JSON to config/credentials.json.
# Usage:
#   ./import-google-credentials.sh          # paste JSON at the prompt
#   ./import-google-credentials.sh /path/to/client_secret.json

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/config/credentials.json"

mkdir -p "$ROOT/config"

validate_json() {
  python3 -c '
import json
import sys

raw = sys.stdin.read().strip()
if not raw:
    print("error: empty input", file=sys.stderr)
    sys.exit(1)

try:
    data = json.loads(raw)
except json.JSONDecodeError as exc:
    print(f"error: invalid JSON ({exc})", file=sys.stderr)
    sys.exit(1)

if "installed" in data:
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    inst = data["installed"]
    missing = [key for key in required if not inst.get(key)]
    if missing:
        print(
            "error: missing Desktop OAuth fields: " + ", ".join(missing),
            file=sys.stderr,
        )
        sys.exit(1)
elif "web" in data:
    print(
        "error: this is a Web OAuth client — create a Desktop app client in Google Cloud Console",
        file=sys.stderr,
    )
    sys.exit(1)
else:
    print(
        "error: unrecognized OAuth JSON (expected a Desktop client with an installed key)",
        file=sys.stderr,
    )
    sys.exit(1)

sys.stdout.write(json.dumps(data, separators=(",", ":")))
'
}

write_credentials() {
  local content="$1"
  printf '%s\n' "$content" > "$OUT"
  chmod 600 "$OUT"
}

confirm_replace() {
  if [[ ! -f "$OUT" ]]; then
    return 0
  fi
  read -r -p "credentials.json already exists. Replace it? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

paste_json() {
  local line body=""

  echo
  echo "Paste your Google OAuth Desktop client JSON below."
  echo "Download it from: Google Cloud Console → APIs & Services → Credentials"
  echo "Create OAuth 2.0 Client ID → Desktop app → Download JSON."
  echo
  echo "When finished, press Enter on an empty line."
  echo

  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      [[ -n "$body" ]] && break
      continue
    fi
    body+="$line"
  done

  if [[ -z "$body" ]]; then
    echo "error: no JSON pasted" >&2
    return 1
  fi

  validate_json <<<"$body"
}

import_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "error: file not found: $path" >&2
    return 1
  fi
  validate_json <"$path"
}

main() {
  local content=""

  if [[ $# -gt 0 ]]; then
    if [[ "$1" == "-h" || "$1" == "--help" ]]; then
      echo "Usage: $0 [path-to-credentials.json]"
      echo "  With no arguments, prompts to paste JSON from the terminal."
      exit 0
    fi
    content="$(import_file "$1")" || exit 1
  else
    if ! confirm_replace; then
      echo "Keeping existing $OUT"
      exit 0
    fi
    while true; do
      if content="$(paste_json)"; then
        break
      fi
      read -r -p "Try again? [Y/n] " retry
      [[ -z "$retry" || "$retry" =~ ^[Yy]$ ]] || exit 1
      echo
    done
  fi

  write_credentials "$content"
  echo
  echo "Saved $OUT"
}

main "$@"
