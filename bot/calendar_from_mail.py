#!/usr/bin/env python3
"""Parse LibCal confirmation mail and upsert Google Calendar events."""

from __future__ import annotations

import re
from datetime import datetime

import study_room_bot as bot
from shared.google_auth import resolve_study_rooms_calendar_id


def parse_date_from_email(text: str) -> str:
    """Return YYYY-MM-DD if present in LibCal confirmation text."""
    collapsed = re.sub(r"\s+", " ", bot.flatten_confirmation_text(text))
    m = re.search(
        r"Date:\s*([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})",
        collapsed,
        re.IGNORECASE,
    )
    if m:
        try:
            return datetime.strptime(m.group(1), "%A, %B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", collapsed)
    return m.group(1) if m else ""


def parse_times_from_email(text: str) -> tuple[str, str]:
    """Return (start_hhmm, end_hhmm) 24h from 'Time: 12:00pm - 4:00pm'."""
    collapsed = re.sub(r"\s+", " ", bot.flatten_confirmation_text(text))
    m = re.search(
        r"Time:\s*(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)",
        collapsed,
        re.IGNORECASE,
    )
    if not m:
        return ("", "")

    def to_hhmm(label: str) -> str:
        label = label.strip().lower().replace(" ", "")
        dt = datetime.strptime(label, "%I:%M%p")
        return dt.strftime("%H:%M")

    try:
        return (to_hhmm(m.group(1)), to_hhmm(m.group(2)))
    except ValueError:
        return ("", "")


def find_calendar_id(service) -> str | None:
    try:
        return resolve_study_rooms_calendar_id(service)
    except Exception:
        return None


def upsert_event(
    cal,
    calendar_id: str,
    room: str,
    date_str: str,
    start_hhmm: str,
    end_hhmm: str,
    code: str,
    link: str,
) -> bool:
    """Create calendar event from emailed check-in details (or patch if it exists)."""
    if not (code or link):
        print("  Skip: email has no check-in code/link.")
        return False
    if not start_hhmm or not end_hhmm:
        start_hhmm = start_hhmm or "12:00"
        end_hhmm = end_hhmm or "14:00"

    summary = bot.parse_room_name_from_title(room)
    time_min = f"{date_str}T00:00:00-04:00"
    time_max = f"{date_str}T23:59:59-04:00"
    events = (
        cal.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
        )
        .execute()
        .get("items", [])
    )

    def matches(ev: dict) -> bool:
        if (ev.get("summary") or "") != summary:
            return False
        start = (ev.get("start") or {}).get("dateTime", "")
        if not start.startswith(date_str):
            return False
        if start_hhmm and f"T{start_hhmm}" not in start:
            if start_hhmm.replace(":", "") not in start.replace(":", ""):
                return False
        return True

    # Match only same room + same start time. Do NOT fall back to "any Room 381
    # that day" — that overwrites earlier blocks (e.g. 12–4) when 4–8 arrives.
    match = next((ev for ev in events if matches(ev)), None)

    clean_link = bot.unwrap_checkin_link(link)
    if clean_link and not bot.is_valid_checkin_link(clean_link):
        clean_link = ""
    if not code and not clean_link:
        print("  Skip: no usable check-in code/link after filtering.")
        return False

    desc_parts = []
    if code:
        desc_parts.append(f"Check-in Code: {code}")
    if clean_link:
        desc_parts.append(f"Check-in link: {clean_link}")
    body = {
        "summary": summary,
        "start": {
            "dateTime": f"{date_str}T{start_hhmm}:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": f"{date_str}T{end_hhmm}:00",
            "timeZone": "America/New_York",
        },
        "description": "\n".join(desc_parts),
    }

    if match:
        cal.events().patch(
            calendarId=calendar_id, eventId=match["id"], body=body
        ).execute()
        print(
            f"  Updated calendar: {summary} {date_str} "
            f"code={code or '?'} link={link or '?'}"
        )
    else:
        created = cal.events().insert(calendarId=calendar_id, body=body).execute()
        print(
            f"  Created calendar: {summary} {date_str} "
            f"code={code or '?'} — {created.get('htmlLink', created.get('id', 'ok'))}"
        )
    return True
