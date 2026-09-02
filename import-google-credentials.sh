#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/scripts/import-google-credentials.sh" "$@"
