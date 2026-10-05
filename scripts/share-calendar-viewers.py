#!/usr/bin/env python3
"""Share Academic Board - Study Rooms calendar with viewers (See all event details).

Requires the service account (or OAuth user) to have permission to manage sharing
on the calendar (Google Calendar → Settings → Share with specific people →
service account → "Make changes and manage sharing").

Usage:
  ./venv/bin/python3 scripts/share-calendar-viewers.py data/calendar_viewers.txt
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from googleapiclient.errors import HttpError  # noqa: E402

from shared.config import STUDY_ROOMS_CALENDAR_ID  # noqa: E402
from shared.google_auth import build_calendar_service, resolve_study_rooms_calendar_id  # noqa: E402


def parse_emails(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
        email = m.strip().lower()
        if email not in seen:
            seen.add(email)
            out.append(email)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: share-calendar-viewers.py <emails.txt|->", file=sys.stderr)
        return 2

    src = sys.argv[1]
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    emails = parse_emails(text)
    if not emails:
        print("No emails found.", file=sys.stderr)
        return 1

    cal = build_calendar_service()
    cid = resolve_study_rooms_calendar_id(cal) or STUDY_ROOMS_CALENDAR_ID
    if not cid:
        print("No STUDY_ROOMS_CALENDAR_ID.", file=sys.stderr)
        return 1

    existing: set[str] = set()
    page_token = None
    while True:
        resp = cal.acl().list(calendarId=cid, pageToken=page_token).execute()
        for it in resp.get("items", []):
            scope = it.get("scope", {})
            if scope.get("type") == "user" and scope.get("value"):
                existing.add(scope["value"].lower())
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    added = skipped = failed = 0
    for email in emails:
        if email in existing:
            print(f"= already shared: {email}")
            skipped += 1
            continue
        try:
            cal.acl().insert(
                calendarId=cid,
                body={"role": "reader", "scope": {"type": "user", "value": email}},
                sendNotifications=True,
            ).execute()
            print(f"+ reader: {email}")
            added += 1
            time.sleep(0.15)
        except HttpError as exc:
            print(f"! fail {email}: {getattr(exc.resp, 'status', '?')} {exc}")
            failed += 1
            if getattr(exc.resp, "status", None) == 403:
                print(
                    "\nService account cannot manage sharing. In Google Calendar "
                    "(as rg.academicboard@gmail.com), set the service account to "
                    "'Make changes and manage sharing', then re-run.",
                    file=sys.stderr,
                )
                return 1
        except Exception as exc:
            print(f"! fail {email}: {exc}")
            failed += 1

    print(f"\nDone. added={added} skipped={skipped} failed={failed} total={len(emails)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
