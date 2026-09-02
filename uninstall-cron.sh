#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/scripts/uninstall-cron.sh" "$@"
