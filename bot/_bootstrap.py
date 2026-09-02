"""Add project root and bot/ to sys.path for CLI entry points."""

from __future__ import annotations

import sys
from pathlib import Path

_BOT_DIR = Path(__file__).resolve().parent
_ROOT = _BOT_DIR.parent

for path in (_ROOT, _BOT_DIR):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
