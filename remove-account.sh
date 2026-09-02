#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/scripts/remove-account.sh" "$@"
