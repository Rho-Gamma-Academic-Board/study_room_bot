"""Shared Google Calendar auth (service account preferred).

Place config/service-account.json and share the study-rooms calendar with the
service account email (Make changes to events). Set STUDY_ROOMS_CALENDAR_ID.

Optional fallback: Desktop OAuth client as config/credentials.json + token.json
when no service account is present.
"""

from __future__ import annotations

import os

from shared.config import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)
from shared.paths import CONFIG_DIR, as_str

SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    as_str(CONFIG_DIR / "service-account.json"),
)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _service_account_creds(scopes: list[str]):
    from google.oauth2 import service_account

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return None
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )


def _user_oauth_creds(scopes: list[str], interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None

    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, scopes)

    if creds and creds.valid and creds.has_scopes(scopes):
        return creds

    if creds and creds.expired and creds.refresh_token and creds.has_scopes(scopes):
        creds.refresh(Request())
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    if not interactive:
        return None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            os.remove(GOOGLE_TOKEN_FILE)
        except OSError:
            pass
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, scopes)
    creds = flow.run_local_server(port=0, prompt="consent")
    with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def get_calendar_credentials(interactive: bool = True):
    """Prefer IAM service account; fall back to user OAuth."""
    sa = _service_account_creds(CALENDAR_SCOPES)
    if sa is not None:
        return sa
    creds = _user_oauth_creds(CALENDAR_SCOPES, interactive=interactive)
    if creds is None:
        raise RuntimeError(
            "No Google Calendar credentials. Add config/service-account.json "
            "(share the calendar with that SA email) or run auth_google_calendar.py."
        )
    return creds


def build_calendar_service(interactive: bool = True):
    from googleapiclient.discovery import build

    return build(
        "calendar", "v3", credentials=get_calendar_credentials(interactive=interactive)
    )


def service_account_email() -> str:
    """Return the SA client_email if service-account.json exists."""
    import json

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return ""
    try:
        data = json.loads(open(SERVICE_ACCOUNT_FILE, encoding="utf-8").read())
        return data.get("client_email", "")
    except Exception:
        return ""


def resolve_study_rooms_calendar_id(service) -> str | None:
    """
    Resolve the study-rooms calendar.
    Prefer STUDY_ROOMS_CALENDAR_ID (needed for service accounts); else match by name.
    """
    from shared.config import STUDY_ROOMS_CALENDAR_ID, STUDY_ROOMS_CALENDAR_NAME

    if STUDY_ROOMS_CALENDAR_ID:
        service.calendars().get(calendarId=STUDY_ROOMS_CALENDAR_ID).execute()
        try:
            service.calendarList().insert(
                body={"id": STUDY_ROOMS_CALENDAR_ID}
            ).execute()
        except Exception:
            pass
        return STUDY_ROOMS_CALENDAR_ID

    page_token = None
    while True:
        result = service.calendarList().list(pageToken=page_token).execute()
        for cal in result.get("items", []):
            if cal.get("summary") == STUDY_ROOMS_CALENDAR_NAME:
                return cal["id"]
        page_token = result.get("nextPageToken")
        if not page_token:
            return None
