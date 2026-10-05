"""Onboarding verify flow: test book, scrape, calendar check, cleanup.

Uses the member's saved LibCal cookies only (no passwords).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from shared.accounts import load_accounts
from shared.config import BOOKING_EMAIL, DAYS_AHEAD, STUDY_ROOMS_CALENDAR_NAME
from shared.google_auth import build_calendar_service, resolve_study_rooms_calendar_id
from shared.paths import BOT_DIR, DATA_DIR, PROJECT_ROOT, as_str, ensure_data_dirs

# bot/ modules (study_room_bot, browser_session, outlook_watcher)
for _p in (str(PROJECT_ROOT), str(BOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VERIFY_DIR = DATA_DIR / "verify"
# Short window to limit hour usage during onboarding.
VERIFY_WINDOW = ("12:00pm", "12:00", "14:00", "12:00pm–2:00pm")


@dataclass
class VerifyBooking:
    nickname: str
    date: str
    room: str
    start_hhmm: str
    end_hhmm: str
    time_label: str
    calendar_event_id: str = ""
    phase: str = ""  # first | second
    created_at: float = 0.0


def _state_path(nickname: str) -> str:
    return as_str(VERIFY_DIR / f"{nickname}.json")


def load_state(nickname: str) -> dict[str, Any]:
    path = _state_path(nickname)
    if not os.path.exists(path):
        return {"nickname": nickname, "bookings": []}
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return {"nickname": nickname, "bookings": []}


def save_state(nickname: str, state: dict[str, Any]) -> None:
    ensure_data_dirs()
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(nickname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.chmod(path, 0o600)


def _get_account(nickname: str):
    for acct in load_accounts():
        if acct.id == nickname:
            return acct
    raise ValueError(f"Account '{nickname}' not found. Save cookies first.")


def run_test_book(nickname: str, *, phase: str = "first") -> dict[str, Any]:
    """
    Book a short 12–2pm-style slot DAYS_AHEAD for this account.
    Does not create a calendar event — that happens after the board mail
    watcher finds the check-in code in the shared inbox.
    """
    from shared.alerts import report_job

    try:
        result = _run_test_book_inner(nickname, phase=phase)
        report_job(
            "test-book",
            ok=True,
            detail=f"{result.get('room')} on {result.get('date')} ({result.get('time_label')})",
        )
        return result
    except Exception as exc:
        report_job("test-book", ok=False, error=str(exc))
        raise


def _run_test_book_inner(nickname: str, *, phase: str = "first") -> dict[str, Any]:
    import study_room_bot as bot
    from browser_session import open_account_context

    account = _get_account(nickname)
    if not account.uses_storage_state():
        raise ValueError("No LibCal cookies on this account yet.")

    target_date, _ = bot.compute_target_date_and_window()
    # Prefer the fixed verify window; fall back across pipeline windows.
    windows = [VERIFY_WINDOW] + [
        w for w in bot.PIPELINE_TEST_WINDOWS if w != VERIFY_WINDOW
    ]

    booked_room = ""
    used_window = VERIFY_WINDOW
    os.environ["RUN_HEADLESS"] = "1"

    with open_account_context(account, headless=True) as (_p, _b, context):
        page = context.new_page()
        if not bot.prepare_libcal_grid(page, account):
            raise RuntimeError("Could not load LibCal with saved cookies (session expired?).")

        for window in windows:
            title_frag, start_hhmm, end_hhmm, time_label = window
            room, _ = bot.try_book_window(
                page, title_frag, end_hhmm, time_label, required_room=None
            )
            if not room:
                continue
            if not bot.submit_booking_on_page(page, account):
                raise RuntimeError("LibCal submit failed for test booking.")
            booked_room = room
            used_window = window
            break

        if not booked_room:
            raise RuntimeError(
                f"No open large-room slot found on {target_date} for a short test booking."
            )

    title_frag, start_hhmm, end_hhmm, time_label = used_window
    booking = VerifyBooking(
        nickname=nickname,
        date=target_date,
        room=booked_room,
        start_hhmm=start_hhmm,
        end_hhmm=end_hhmm,
        time_label=time_label,
        calendar_event_id="",
        phase=phase,
        created_at=time.time(),
    )

    state = load_state(nickname)
    bookings = [b for b in state.get("bookings", []) if b.get("phase") != phase]
    bookings.append(asdict(booking))
    state["bookings"] = bookings
    state["last_phase"] = phase
    state["updated_at"] = time.time()
    save_state(nickname, state)

    return {
        "ok": True,
        "phase": phase,
        "date": target_date,
        "room": booked_room,
        "time_label": time_label,
        "start_hhmm": start_hhmm,
        "end_hhmm": end_hhmm,
        # Calendar events are created later by the board mail → Calendar watcher
        # (Outlook scrape / personal script), not at book time.
        "calendar_event_id": "",
        "booking_email": BOOKING_EMAIL or "jo564454@ucf.edu",
        "days_ahead": DAYS_AHEAD,
        "note": (
            "LibCal emailed the member’s Outlook. After the alert reaches "
            f"{BOOKING_EMAIL or 'jo564454@ucf.edu'}, the board mail watcher "
            "adds the check-in code to the study rooms calendar."
        ),
    }


def _find_event_id(summary: str, date_str: str, start_hhmm: str) -> str:
    try:
        cal = build_calendar_service(interactive=False)
        calendar_id = resolve_study_rooms_calendar_id(cal)
        if not calendar_id:
            return ""
        events = (
            cal.events()
            .list(
                calendarId=calendar_id,
                timeMin=f"{date_str}T00:00:00-04:00",
                timeMax=f"{date_str}T23:59:59-04:00",
                singleEvents=True,
            )
            .execute()
            .get("items", [])
        )
        for ev in events:
            if ev.get("summary") != summary:
                continue
            start = (ev.get("start") or {}).get("dateTime", "")
            if start.startswith(f"{date_str}T{start_hhmm}"):
                return ev.get("id", "")
    except Exception:
        return ""
    return ""


def run_scrape(nickname: str | None = None) -> dict[str, Any]:
    """
    Scrape board Outlook for LibCal confirmations and upsert Google Calendar.
    When nickname is set, match the latest verify booking room/date and wait
    briefly for the confirmation email to arrive.
    """
    from shared.alerts import report_job
    import outlook_watcher

    expected_room = ""
    expected_date = ""
    wait_seconds = 0
    if nickname:
        state = load_state(nickname)
        booking = next(iter(reversed(state.get("bookings", []))), None)
        if booking:
            expected_room = booking.get("room") or ""
            expected_date = booking.get("date") or ""
            wait_seconds = int(os.environ.get("OUTLOOK_VERIFY_WAIT_SECONDS", "20"))

    try:
        result = outlook_watcher.process_once(
            expected_room=expected_room,
            expected_date=expected_date,
            wait_seconds=wait_seconds,
            headless=True,
            interactive=False,
        )
        if not result.get("ok"):
            report_job(
                "scrape",
                ok=False,
                error=result.get("detail") or "Outlook scrape failed",
                detail=result.get("detail") or "",
            )
            return result
        report_job(
            "scrape",
            ok=True,
            detail=result.get("detail") or f"updated={result.get('updated', 0)}",
        )
        if nickname and result.get("events"):
            state = load_state(nickname)
            bookings = state.get("bookings", [])
            if bookings:
                bookings[-1]["scrape_detail"] = result.get("detail", "")
                bookings[-1]["scraped_at"] = time.time()
                save_state(nickname, state)
        return result
    except Exception as exc:
        report_job("scrape", ok=False, error=str(exc))
        raise


def calendar_status(nickname: str, phase: str = "first") -> dict[str, Any]:
    state = load_state(nickname)
    booking = next(
        (b for b in reversed(state.get("bookings", [])) if b.get("phase") == phase),
        None,
    )
    if not booking:
        booking = next(iter(reversed(state.get("bookings", []))), None)
    if not booking:
        return {"ok": False, "found": False, "detail": "No verify booking on record."}

    cal = build_calendar_service(interactive=False)
    calendar_id = resolve_study_rooms_calendar_id(cal)
    if not calendar_id:
        return {"ok": False, "found": False, "detail": "Study rooms calendar not found."}

    summary = booking["room"]
    # Normalize like the bot does
    import study_room_bot as bot

    summary = bot.parse_room_name_from_title(summary)
    date_str = booking["date"]
    start_hhmm = booking["start_hhmm"]

    events = (
        cal.events()
        .list(
            calendarId=calendar_id,
            timeMin=f"{date_str}T00:00:00-04:00",
            timeMax=f"{date_str}T23:59:59-04:00",
            singleEvents=True,
        )
        .execute()
        .get("items", [])
    )
    match = None
    for ev in events:
        if ev.get("summary") != summary:
            continue
        start = (ev.get("start") or {}).get("dateTime", "")
        if start.startswith(f"{date_str}T{start_hhmm}"):
            match = ev
            break

    if not match:
        return {
            "ok": True,
            "found": False,
            "calendar_name": STUDY_ROOMS_CALENDAR_NAME,
            "booking": booking,
        }

    desc = match.get("description") or ""
    has_code = "Check-in Code:" in desc and "pending" not in desc.lower()
    return {
        "ok": True,
        "found": True,
        "has_checkin_code": has_code,
        "summary": match.get("summary"),
        "html_link": match.get("htmlLink", ""),
        "description": desc,
        "calendar_name": STUDY_ROOMS_CALENDAR_NAME,
        "booking": booking,
    }


def cleanup_calendar(nickname: str) -> dict[str, Any]:
    """Delete calendar events created during verify for this nickname."""
    state = load_state(nickname)
    bookings = state.get("bookings", [])
    if bookings:
        phase = bookings[-1].get("phase") or "first"
        status = calendar_status(nickname, phase=phase)
        if not status.get("found"):
            raise ValueError(
                "Google Calendar has not posted this booking yet. "
                "Wait for the shared calendar event before cleaning up."
            )
    cal = build_calendar_service(interactive=False)
    calendar_id = resolve_study_rooms_calendar_id(cal)
    if not calendar_id:
        raise RuntimeError("Study rooms calendar not found.")

    deleted = 0
    for booking in state.get("bookings", []):
        eid = booking.get("calendar_event_id") or ""
        if eid:
            try:
                cal.events().delete(calendarId=calendar_id, eventId=eid).execute()
                deleted += 1
                continue
            except Exception:
                pass
        # Fallback match by room/date/time
        status = calendar_status(nickname, phase=booking.get("phase", ""))
        # Re-find and delete
        import study_room_bot as bot

        summary = bot.parse_room_name_from_title(booking["room"])
        date_str = booking["date"]
        start_hhmm = booking["start_hhmm"]
        events = (
            cal.events()
            .list(
                calendarId=calendar_id,
                timeMin=f"{date_str}T00:00:00-04:00",
                timeMax=f"{date_str}T23:59:59-04:00",
                singleEvents=True,
            )
            .execute()
            .get("items", [])
        )
        for ev in events:
            start = (ev.get("start") or {}).get("dateTime", "")
            if ev.get("summary") == summary and start.startswith(
                f"{date_str}T{start_hhmm}"
            ):
                try:
                    cal.events().delete(
                        calendarId=calendar_id, eventId=ev["id"]
                    ).execute()
                    deleted += 1
                except Exception:
                    pass

    state["cleaned_at"] = time.time()
    save_state(nickname, state)
    return {"ok": True, "deleted": deleted}


def cancel_libcal_booking(nickname: str, phase: str | None = None) -> dict[str, Any]:
    """
    Best-effort cancel of the verify booking in LibCal using saved cookies.
    LibCal UI varies — if this fails, the member should cancel manually.

    Blocked until the booking appears on Google Calendar so onboarding can
    confirm the Outlook → Calendar path before the room is released.
    """
    import re

    from browser_session import open_account_context

    account = _get_account(nickname)
    state = load_state(nickname)
    bookings = state.get("bookings", [])
    if phase:
        booking = next((b for b in reversed(bookings) if b.get("phase") == phase), None)
    else:
        booking = bookings[-1] if bookings else None
    if not booking:
        raise ValueError("No verify booking to cancel.")

    cal = calendar_status(nickname, phase=phase or booking.get("phase") or "first")
    if not cal.get("found"):
        raise ValueError(
            "Google Calendar has not posted this booking yet. "
            "Wait for the shared calendar event before cancelling."
        )

    room = booking["room"]
    date_str = booking["date"]
    # LibCal often shows like "Monday, September 15, 2026"
    try:
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0"," ")
    except Exception:
        pretty_date = date_str

    cancelled = False
    detail = ""
    with open_account_context(account, headless=True) as (_p, _b, context):
        page = context.new_page()
        # Common Springshare bookings endpoints
        for url in (
            "https://ucf.libcal.com/r/new",
            "https://ucf.libcal.com/booking",
            "https://ucf.libcal.com/",
        ):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                continue
            # Look for My Bookings / Upcoming
            for sel in (
                "text=My Bookings",
                "text=View Bookings",
                "a:has-text('Bookings')",
                "#s-lc-public-bs-mybookings",
            ):
                try:
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=3000)
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

            body = page.content()
            if room.replace("Room ", "") not in body and room not in body:
                continue

            # Try cancel/delete buttons near the room text
            candidates = page.locator(
                "button:has-text('Cancel'), a:has-text('Cancel'), "
                "button:has-text('Delete'), a:has-text('Delete'), "
                "button:has-text('Remove')"
            )
            count = candidates.count()
            for i in range(count):
                try:
                    btn = candidates.nth(i)
                    # Prefer a cancel near matching room row if possible
                    btn.click(timeout=3000)
                    page.wait_for_timeout(800)
                    # Confirm dialogs
                    for conf in (
                        "button:has-text('Confirm')",
                        "button:has-text('Yes')",
                        "button:has-text('OK')",
                        "input[value='Confirm']",
                    ):
                        try:
                            c = page.locator(conf).first
                            if c.count() and c.is_visible():
                                c.click(timeout=2000)
                                page.wait_for_timeout(800)
                        except Exception:
                            pass
                    cancelled = True
                    detail = f"Clicked cancel control on {url}"
                    break
                except Exception:
                    continue
            if cancelled:
                break

            # Regex hint for debugging
            if re.search(re.escape(pretty_date.split(",")[0]), body, re.I):
                detail = "Found bookings page but no Cancel control matched."

    booking["cancelled"] = cancelled
    booking["cancel_detail"] = detail
    save_state(nickname, state)

    return {
        "ok": True,
        "cancelled": cancelled,
        "detail": detail
        or (
            "Could not auto-cancel. Open LibCal → My Bookings and cancel the test booking, "
            "then continue."
        ),
        "booking": booking,
    }
