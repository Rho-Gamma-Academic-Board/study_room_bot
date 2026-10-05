#!/usr/bin/env python3
"""
Verify Google Calendar access for the study room bot.

Preferred: IAM service account
  1. Create a service account in Google Cloud → download JSON
  2. Save as config/service-account.json
  3. Share calendar "Academic Board - Study Rooms" with the SA email
     (Make changes to events)
  4. Set STUDY_ROOMS_CALENDAR_ID in config/ucf_credentials.env

Fallback: Desktop OAuth via config/credentials.json (rare).

Usage:
  venv/bin/python3 bot/auth_google_calendar.py
"""

import _bootstrap  # noqa: F401

from shared.accounts import mask_email
from shared.config import BOOKING_EMAIL, STUDY_ROOMS_CALENDAR_ID, STUDY_ROOMS_CALENDAR_NAME
from shared.google_auth import (
    SERVICE_ACCOUNT_FILE,
    build_calendar_service,
    resolve_study_rooms_calendar_id,
    service_account_email,
)


def main() -> None:
    print(f"Board Outlook inbox: {mask_email(BOOKING_EMAIL) or '(set BOOKING_EMAIL)'}")
    print(f"Target calendar: {STUDY_ROOMS_CALENDAR_NAME}")
    print()

    sa_email = service_account_email()
    if sa_email:
        print(f"Service account found: {sa_email}")
        print(f"  File: {SERVICE_ACCOUNT_FILE}")
        print("  Share the study-rooms calendar with this email (Make changes to events).")
    else:
        print("No config/service-account.json — will try user OAuth fallback.")
    print()

    try:
        cal = build_calendar_service(interactive=True)
        if STUDY_ROOMS_CALENDAR_ID:
            print(f"STUDY_ROOMS_CALENDAR_ID set ({STUDY_ROOMS_CALENDAR_ID[:24]}...)")
        calendar_id = resolve_study_rooms_calendar_id(cal)
        if calendar_id:
            meta = cal.calendars().get(calendarId=calendar_id).execute()
            print(
                f"OK: calendar '{meta.get('summary', STUDY_ROOMS_CALENDAR_NAME)}' "
                f"(id={calendar_id})"
            )
        else:
            print(f"WARNING: calendar '{STUDY_ROOMS_CALENDAR_NAME}' not found.")
            if sa_email:
                print(f"  Share it with: {sa_email}")
                print("  And set STUDY_ROOMS_CALENDAR_ID in config/ucf_credentials.env")
    except Exception as exc:
        print(f"Calendar auth error: {exc}")


if __name__ == "__main__":
    main()
