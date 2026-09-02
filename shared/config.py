"""Configuration loaded from environment and config/ucf_credentials.env."""

import os
import sys

from shared.paths import (
    CREDS_FILE,
    GOOGLE_CREDENTIALS_FILE as _GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_FILE as _GOOGLE_TOKEN_PATH,
    as_str,
)

_CREDS_PATH = as_str(CREDS_FILE)

if os.path.exists(_CREDS_PATH):
    with open(_CREDS_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value

PUBLIC_NAME = os.environ.get("PUBLIC_NAME", "Student")
UCF_ID = os.environ.get("UCF_ID", "")

UCF_EMAIL = os.environ.get("UCF_EMAIL", "")
UCF_PASSWORD = os.environ.get("UCF_PASSWORD", "")
UCF_2FA_SENDER = os.environ.get("UCF_2FA_SENDER", "69525")

OUTLOOK_EMAIL = os.environ.get("OUTLOOK_EMAIL", UCF_EMAIL)
OUTLOOK_INBOX_URL = "https://outlook.office.com/mail/inbox"
OUTLOOK_WAIT_SECONDS = int(os.environ.get("OUTLOOK_WAIT_SECONDS", "30"))

BOOKING_EMAIL = os.environ.get("BOOKING_EMAIL", "")
STUDY_ROOMS_CALENDAR_NAME = os.environ.get("STUDY_ROOMS_CALENDAR_NAME", "Academic Board - Study Rooms")
STUDY_ROOMS_CALENDAR_DESCRIPTION = os.environ.get(
    "STUDY_ROOMS_CALENDAR_DESCRIPTION", "Academic Board study rooms"
)
GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", as_str(_GOOGLE_CREDENTIALS_PATH))
GOOGLE_TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE", as_str(_GOOGLE_TOKEN_PATH))

LIBCAL_RESERVE_URL = "https://ucf.libcal.com/reserve/largestudyrooms"
LIBCAL_SENDER = "alerts@mail.libcal.com"
LIBCAL_CONFIRMATION_SUBJECT = "Your booking has been submitted"

DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", "3"))
CLOSE_AFTER_SECONDS = int(os.environ.get("CLOSE_AFTER_SECONDS", "60"))

RUN_HEADLESS = os.environ.get("RUN_HEADLESS", "").strip().lower() in ("1", "true", "yes")
RUN_HEADLESS_TEST = os.environ.get("RUN_HEADLESS_TEST", "").strip().lower() in ("1", "true", "yes")
PIPELINE_TEST = os.environ.get("PIPELINE_TEST", "").strip().lower() in ("1", "true", "yes")
BRUTE_RUN = os.environ.get("BRUTE_RUN", "").strip().lower() in ("1", "true", "yes")

# Read UCF SMS codes from iMessage on macOS (enabled by default on Darwin).
_USE_IMESSAGE_DEFAULT = "1" if sys.platform == "darwin" else "0"
USE_IMESSAGE_2FA = os.environ.get("USE_IMESSAGE_2FA", _USE_IMESSAGE_DEFAULT).strip().lower() in (
    "1",
    "true",
    "yes",
)
