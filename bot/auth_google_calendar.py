#!/usr/bin/env python3
"""
Sign in to Google Calendar for the study room bot.

Run this after updating BOOKING_EMAIL and STUDY_ROOMS_CALENDAR_NAME in ucf_credentials.env.
A browser window opens — sign in with the Google account that owns the target calendar.

Usage:
  venv/bin/python3 auth_google_calendar.py
"""

import _bootstrap  # noqa: F401

from shared.accounts import mask_email
from shared.config import (
    BOOKING_EMAIL,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
    STUDY_ROOMS_CALENDAR_NAME,
)


def main() -> None:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("Install: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        raise SystemExit(1)

    import os

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"Missing {GOOGLE_CREDENTIALS_FILE}")
        print("Download OAuth client JSON from Google Cloud Console and save as credentials.json")
        raise SystemExit(1)

    scopes = ["https://www.googleapis.com/auth/calendar"]
    print(f"Booking email: {mask_email(BOOKING_EMAIL)}")
    print(f"Target calendar: {STUDY_ROOMS_CALENDAR_NAME}")
    print(f"Token will be saved to: {GOOGLE_TOKEN_FILE}")
    print()
    print("A browser will open. Sign in with the Google account that has that calendar.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, scopes)
    creds = flow.run_local_server(port=0)
    with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    calendars = service.calendarList().list().execute().get("items", [])
    names = [c.get("summary", "") for c in calendars]
    if STUDY_ROOMS_CALENDAR_NAME in names:
        print(f"OK: found calendar '{STUDY_ROOMS_CALENDAR_NAME}' on this account.")
    else:
        print(f"WARNING: calendar '{STUDY_ROOMS_CALENDAR_NAME}' not found on this account.")
        print("Available calendars:")
        for name in sorted(names):
            print(f"  - {name}")


if __name__ == "__main__":
    main()
