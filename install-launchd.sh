#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/scripts/install-launchd.sh" "$@"
