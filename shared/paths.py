"""Project directory layout — single source of truth for all paths."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
ACCOUNTS_DIR = DATA_DIR / "accounts"
PROFILES_DIR = DATA_DIR / "profiles"
USAGE_FILE = DATA_DIR / "account_usage.json"

CONFIG_DIR = PROJECT_ROOT / "config"
CREDS_FILE = CONFIG_DIR / "ucf_credentials.env"
CREDS_EXAMPLE = CONFIG_DIR / "ucf_credentials.env.example"
GOOGLE_CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = CONFIG_DIR / "token.json"

LOGS_DIR = PROJECT_ROOT / "logs"
BOT_LOG = LOGS_DIR / "study_room_bot.log"
BOT_ERROR_LOG = LOGS_DIR / "study_room_bot_error.log"

BOT_DIR = PROJECT_ROOT / "bot"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def ensure_data_dirs() -> None:
    """Create runtime directories if missing."""
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def as_str(path: Path) -> str:
    return os.fspath(path)
