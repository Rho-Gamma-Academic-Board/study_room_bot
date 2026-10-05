# Script by: Joshua Perez
# UCF LibCal large study room booking bot (macOS).
# Uses Playwright, multi-account rotation, and Google Calendar.

import _bootstrap  # noqa: F401

import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import sync_playwright

from shared.accounts import (
    booking_hours_from_window,
    load_accounts,
    mask_email,
    pick_account,
    record_booking,
)
from shared.config import (
    BOOKING_EMAIL,
    CLOSE_AFTER_SECONDS,
    DAYS_AHEAD,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
    LIBCAL_CONFIRMATION_SUBJECT,
    LIBCAL_RESERVE_URL,
    LIBCAL_SENDER,
    OUTLOOK_INBOX_URL,
    OUTLOOK_WAIT_SECONDS,
    PIPELINE_TEST,
    SCHEDULED_RUN,
    RUN_HEADLESS,
    RUN_HEADLESS_TEST,
    USE_IMESSAGE_2FA,
    STUDY_ROOMS_CALENDAR_NAME,
    STUDY_ROOMS_CALENDAR_DESCRIPTION,
    STUDY_ROOMS_CALENDAR_ID,
    UCF_2FA_SENDER,
)

# LibCal base URL — Large Study Rooms (John C. Hitt)
BASE_URL = LIBCAL_RESERVE_URL
PREFERRED_ROOMS = ["360H", "360F"]
# Large study rooms with capacity 10 on LibCal (360H/360F tried first via PREFERRED_ROOMS).
CAPACITY_10_ROOMS = ["360H", "360F", "370A", "370B", "381", "172"]
# Use private Chrome (no saved profile) for testing; set False for normal runs with saved login
USE_PRIVATE_CHROME = False
# (title fragment, start HH:MM 24h, end HH:MM 24h, human label)
# Full-day coverage: 12pm–10pm in three blocks (4h + 4h + 2h = 10h, one account per block).
FULL_DAY_WINDOWS = [
    ("12:00pm", "12:00", "16:00", "12:00pm–4:00pm"),
    ("4:00pm", "16:00", "20:00", "4:00pm–8:00pm"),
    ("8:00pm", "20:00", "22:00", "8:00pm–10:00pm"),
]
DEFAULT_BOOKING_WINDOW = FULL_DAY_WINDOWS[0]
PIPELINE_TEST_WINDOWS = [
    ("9:00am", "09:00", "11:00", "9:00am–11:00am"),
    ("10:00am", "10:00", "12:00", "10:00am–12:00pm"),
    ("11:00am", "11:00", "13:00", "11:00am–1:00pm"),
    ("12:00pm", "12:00", "14:00", "12:00pm–2:00pm"),
    ("1:00pm", "13:00", "15:00", "1:00pm–3:00pm"),
    ("2:00pm", "14:00", "16:00", "2:00pm–4:00pm"),
    ("3:00pm", "15:00", "17:00", "3:00pm–5:00pm"),
    ("4:00pm", "16:00", "18:00", "4:00pm–6:00pm"),
]

def navigate_libcal(page, url: str | None = None, label: str = "LibCal") -> bool:
    """Navigate to LibCal with commit-level waits — networkidle often times out."""
    target = url or BASE_URL
    for attempt in range(1, 4):
        try:
            page.goto(target, wait_until="commit", timeout=90000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            return True
        except Exception as exc:
            print(f"{label}: load attempt {attempt}/3 failed — {exc}")
            time.sleep(3)
    return False


def wait_for_user(prompt: str = "Press Enter to continue..."):
    """Prompt user to press Enter, or skip if running headless or non-interactive."""
    if RUN_HEADLESS:
        print(f"[headless] Skipping prompt: {prompt}")
        return
    try:
        input(prompt)
    except EOFError:
        print(f"[non-interactive] Skipping prompt: {prompt}")
        return


def parse_room_name_from_title(title: str) -> str:
    """Pull room label from a LibCal slot title, e.g. 'Room 360H'."""
    if not title:
        return "Study room"
    m = re.search(r"Room\s+(\d+[A-Za-z]*)", title, re.IGNORECASE)
    if m:
        return f"Room {m.group(1).upper()}"
    if " - " in title:
        return title.split(" - ")[1].strip()
    return "Study room"


def normalize_room_key(room_name: str) -> str:
    """Normalize 'Room 360H' -> '360H' for comparisons."""
    m = re.search(r"(\d+[A-Z]?)", (room_name or "").upper().replace(" ", ""))
    return m.group(1) if m else (room_name or "").upper().replace(" ", "")


def rooms_match(room_a: str, room_b: str) -> bool:
    return normalize_room_key(room_a) == normalize_room_key(room_b)


def is_capacity_10_room(room_name: str) -> bool:
    return normalize_room_key(room_name) in {r.upper() for r in CAPACITY_10_ROOMS}


def room_preference_rank(room_name: str) -> int:
    """
    Lower = try first among capacity-10 rooms: 360H, 360F, then other cap-10, then others.
    """
    key = normalize_room_key(room_name)
    for i, pref in enumerate(PREFERRED_ROOMS):
        if key == pref.upper():
            return i
    preferred_keys = {p.upper() for p in PREFERRED_ROOMS}
    other_cap10 = [r for r in CAPACITY_10_ROOMS if r.upper() not in preferred_keys]
    offset = len(PREFERRED_ROOMS)
    for i, room in enumerate(other_cap10):
        if key == room.upper():
            return offset + i
    return offset + len(other_cap10)


def room_sort_key(room_name: str, preferred_room: str | None = None, index: int = 0) -> tuple:
    """Sort key: same room as earlier slot, then cap-10, then 360H/360F, then others."""
    same_room = 0 if preferred_room and rooms_match(room_name, preferred_room) else 1
    cap10 = 0 if is_capacity_10_room(room_name) else 1
    return (same_room, cap10, room_preference_rank(room_name), index)


def cap10_rooms_on_grid(page) -> list[str]:
    """Unique capacity-10 room names currently on the large study rooms grid."""
    availability = list_timeline_availability(page) or []
    rooms = {
        a.get("room")
        for a in availability
        if a.get("room") and is_capacity_10_room(a.get("room"))
    }
    return sorted(rooms, key=lambda r: (room_preference_rank(r), r))


def room_supports_window(page, room_name: str, title_frag: str, end_hhmm: str) -> bool:
    """Return True if room can be booked for start title_frag through end_hhmm."""
    availability = list_timeline_availability(page) or []
    hit = next(
        (
            a
            for a in availability
            if rooms_match(a.get("room") or "", room_name)
            and (a.get("time_label") or "").lower() == title_frag.lower()
        ),
        None,
    )
    if hit is None:
        return False

    try:
        slot = page.locator("a.s-lc-eq-avail").nth(hit["index"])
        slot.scroll_into_view_if_needed()
        slot.wait_for(state="visible", timeout=3000)
        slot.click()
        time.sleep(0.4)

        end_select = page.locator("select.b-end-date")
        end_select.wait_for(state="visible", timeout=3000)
        end_value = end_select.evaluate(
            """(sel, want) => {
                for (let i = 0; i < sel.options.length; i++) {
                    const v = (sel.options[i].value || '');
                    if (v.indexOf(want) !== -1) return v;
                }
                return null;
            }""",
            end_hhmm,
        )
        ok = bool(end_value and end_hhmm in end_value)
    except Exception:
        ok = False
    finally:
        clear_selected_slot(page)
        time.sleep(0.2)

    return ok


def room_supports_all_windows(page, room_name: str, windows: list[tuple]) -> bool:
    for title_frag, _, end_hhmm, time_label in windows:
        if not room_supports_window(page, room_name, title_frag, end_hhmm):
            print(f"    {room_name}: missing {time_label}")
            return False
    return True


def discover_target_room(page, windows: list[tuple]) -> tuple[str | None, list[tuple]]:
    """
    Pick the best capacity-10 room for 12pm–10pm coverage.
    Returns (room_name, windows_to_book) where windows_to_book is a subset of windows.

    TARGET_ROOM env (e.g. 360H) is tried first for a full-day book before other rooms.
    """
    rooms = cap10_rooms_on_grid(page)
    if not rooms:
        print("No capacity-10 rooms on the grid for this date.")
        return None, []

    forced = os.environ.get("TARGET_ROOM", "").strip()
    if forced:
        forced_match = next((r for r in rooms if rooms_match(r, forced)), None)
        if forced_match:
            print(f"TARGET_ROOM={forced} — checking {forced_match} first...")
            if room_supports_all_windows(page, forced_match, windows):
                print(f"Selected {forced_match} — full 12pm–10pm available.")
                return forced_match, list(windows)
            available = [
                w
                for w in windows
                if room_supports_window(page, forced_match, w[0], w[2])
            ]
            if available:
                print(
                    f"Selected {forced_match} — {len(available)}/{len(windows)} "
                    "window(s) available (partial)."
                )
                return forced_match, available
            print(f"{forced_match} has no open 12pm–10pm windows; falling back.")
        else:
            print(f"TARGET_ROOM={forced} not on grid; falling back to preference order.")

    print(f"Scanning {len(rooms)} cap-10 room(s) for full 12pm–10pm availability...")
    print(f"Priority: {', '.join(PREFERRED_ROOMS)}, then other cap-10 large study rooms.")
    for room in rooms:
        print(f"  Checking {room}...")
        if room_supports_all_windows(page, room, windows):
            print(f"Selected {room} — full 12pm–10pm available.")
            return room, list(windows)

    print("No cap-10 room has full 12pm–10pm. Picking room with the most slots...")
    best_room = None
    best_count = 0
    best_windows: list[tuple] = []
    for room in rooms:
        available = [
            w
            for w in windows
            if room_supports_window(page, room, w[0], w[2])
        ]
        count = len(available)
        if count == 0:
            continue
        if (
            best_room is None
            or count > best_count
            or (
                count == best_count
                and room_preference_rank(room) < room_preference_rank(best_room)
            )
        ):
            best_room, best_count, best_windows = room, count, available

    if best_room:
        print(f"Selected {best_room} — {best_count}/{len(windows)} window(s) available.")
        return best_room, best_windows

    return None, []


def prepare_libcal_grid(page, account) -> bool:
    """Navigate to LibCal, sign in if needed, advance to target date, wait for grid."""
    if not navigate_libcal(page):
        return False
    ensure_logged_in(page, account)
    if is_login_page(page):
        print(f"Session not authenticated for {account.id} — run ./sign-in.sh {account.id}")
        return False
    advance_days(page, DAYS_AHEAD)
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    if not wait_for_site_ready(page, is_libcal_ready, 60, label="LibCal"):
        print("LibCal grid did not load.")
        return False
    return True


def discover_target_room_for_account(account, windows: list[tuple]) -> tuple[str | None, list[tuple]]:
    """Open LibCal on the target date and discover the best cap-10 room."""
    from browser_session import open_account_context

    with open_account_context(account) as (_p, _browser, context):
        page = context.new_page()
        if not prepare_libcal_grid(page, account):
            return None, []
        return discover_target_room(page, windows)

def get_2fa_from_imessage(sender_filter: str = UCF_2FA_SENDER, max_age_seconds: int = 120) -> str:
    """
    Read the most recent SMS from sender_filter (e.g. '69525') in iMessage on Mac.
    Only returns a code if the message arrived within max_age_seconds (default 2 min).
    Returns a 6-digit code if found, else "".
    Requires Full Disk Access for ~/Library/Messages/chat.db on recent macOS.
    """
    code = ""
    # Try Messages SQLite DB first (macOS)
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    if os.path.exists(db_path):
        try:
            import sqlite3
            from datetime import timezone
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # Apple stores dates as nanoseconds since 2001-01-01 UTC
            apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
            cutoff_apple_ns = int((cutoff - apple_epoch).total_seconds() * 1_000_000_000)
            cur.execute("""
                SELECT m.text FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE h.id LIKE ? AND m.is_from_me = 0
                  AND m.date > ?
                ORDER BY m.date DESC LIMIT 1
            """, (f"%{sender_filter}%", cutoff_apple_ns))
            row = cur.fetchone()
            conn.close()
            if row and row["text"]:
                m = re.search(r"\b(\d{6})\b", row["text"])
                if m:
                    return m.group(1)
        except Exception as e:
            pass
    # Fallback: AppleScript to get last message (may need Accessibility permissions)
    try:
        script = f'''
        tell application "Messages"
            set lastText to ""
            repeat with aChat in chats
                if name of aChat contains "{sender_filter}" then
                    set lastMsg to last message of aChat
                    if text of lastMsg is not "" then
                        set lastText to text of lastMsg
                        exit repeat
                    end if
                end if
            end repeat
            return lastText
        end tell
        '''
        out = os.popen(f"osascript -e {repr(script)}").read().strip()
        if out:
            m = re.search(r"\b(\d{6})\b", out)
            if m:
                return m.group(1)
    except Exception:
        pass
    return code


def submit_2fa_to_page(page, code: str) -> bool:
    """Fill and submit a 6-digit UCF/Microsoft 2FA code."""
    try:
        code_input = page.locator(
            'input[type="tel"], input[name="otc" i], input[placeholder*="code" i], input[id*="idTxtBx" i]'
        ).first
        code_input.wait_for(state="visible", timeout=5000)
        code_input.fill(code)
        page.locator(
            'input[type="submit"], button:has-text("Verify"), button:has-text("Submit")'
        ).first.click()
        print("2FA code submitted, waiting for redirect...")
        time.sleep(5)
        try:
            stay = page.locator('input[value="Yes"], button:has-text("Yes")').first
            if stay.is_visible(timeout=3000):
                stay.click()
                print("Clicked 'Yes' on stay signed in prompt.")
                time.sleep(3)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"Could not submit 2FA code: {e}")
        return False


def read_2fa_code_from_terminal() -> str:
    """Prompt for a 6-digit SMS code when iMessage auto-read is disabled."""
    if RUN_HEADLESS:
        return ""
    try:
        line = input("2FA code (6 digits), or press Enter to finish in browser: ").strip()
    except EOFError:
        return ""
    m = re.search(r"\b(\d{6})\b", line)
    return m.group(1) if m else ""


def get_2fa_code(max_wait_seconds: int = 60) -> str:
    """Return a 6-digit 2FA code from iMessage (macOS) or an empty string."""
    if not USE_IMESSAGE_2FA:
        return ""
    for _ in range(max_wait_seconds):
        code = get_2fa_from_imessage(UCF_2FA_SENDER)
        if code:
            return code
        time.sleep(1)
    return ""


def unwrap_checkin_link(url: str) -> str:
    """Unwrap Outlook SafeLinks to the real LibCal check-in URL."""
    if not url:
        return ""
    if "safelinks.protection.outlook.com" in url.lower():
        parsed = urlparse(url)
        wrapped = parse_qs(parsed.query).get("url", [""])[0]
        if wrapped:
            return unquote(wrapped)
    return url


def is_valid_checkin_link(url: str) -> bool:
    """True only for real LibCal check-in/booking URLs (reject tracking junk)."""
    if not url:
        return False
    cleaned = unwrap_checkin_link(url).strip()
    lower = cleaned.lower()
    if "libcal.com" not in lower:
        return False
    # Tracking / marketing / privacy pages sometimes appear in the same mail.
    reject = (
        "joinhandshake.com",
        "springshare.com/privacy",
        "google.com/calendar",
        "mailto:",
    )
    if any(bad in lower for bad in reject):
        return False
    preferred = ("checkin", "check-in", "checkedin", "/r/checkin", "/booking/", "/reserve/")
    return any(p in lower for p in preferred)


def extract_checkin_link_from_email_text(text: str) -> str:
    """Pull a LibCal check-in URL from confirmation email text or HTML."""
    if not text:
        return ""

    urls = re.findall(r'https?://[^\s<>"\']+', text, re.IGNORECASE)
    candidates = []
    for url in urls:
        cleaned = unwrap_checkin_link(url.rstrip(".,);]>\"'"))
        if is_valid_checkin_link(cleaned):
            candidates.append(cleaned)

    preferred_patterns = ("checkin", "check-in", "checkedin", "/booking/", "/reserve/")
    for pattern in preferred_patterns:
        for url in candidates:
            if pattern in url.lower():
                return url

    return candidates[0] if candidates else ""


def flatten_confirmation_text(text: str) -> str:
    """Normalize Outlook/LibCal HTML or wrapped text so regex can match the template."""
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"[ \t]+", " ", text)


def extract_checkin_code_from_email_text(text: str) -> str:
    """
    Parse LibCal confirmation body for the check-in code.

    Standard line:
      Enter the code 8E4 to check in.
    """
    collapsed = re.sub(r"\s+", " ", flatten_confirmation_text(text)).strip()
    if not collapsed:
        return ""
    patterns = [
        r"Enter the code\s+([A-Za-z0-9]{3,8})\s+to check[- ]?in",
        r"Enter this code[:\s]+([A-Za-z0-9]{3,8})",
        r"Enter the code\s+([A-Za-z0-9]{3,8})",
        r"check[- ]?in(?:\s+with)?(?:\s+code)?[:\s]+([A-Za-z0-9]{3,8})",
        r"code[:\s]+([A-Za-z0-9]{3,8})\s+to check[- ]?in",
    ]
    reject_codes = {
        "INBOX",
        "CODE",
        "CHECK",
        "ENTER",
        "WITH",
        "THIS",
        "YOUR",
        "ROOM",
        "SPACE",
        "HTTP",
        "HTTPS",
        "CANCELLA",
        "CANCEL",
        "BOOKING",
        "SUBMIT",
    }
    for pattern in patterns:
        m = re.search(pattern, collapsed, re.IGNORECASE)
        if m:
            code = m.group(1).strip().upper()
            if code in reject_codes or not re.fullmatch(r"[A-Z0-9]{3,8}", code):
                continue
            return code
    return ""


def parse_booking_confirmation(text: str, expected_room: str = "") -> tuple[str, str, str]:
    """
    Parse room, check-in code, and check-in link from a LibCal confirmation
    (page or email). Returns (room_str, code_str, checkin_link).
    """
    if not text:
        return ("", "", "")

    flattened = flatten_confirmation_text(text)
    collapsed = re.sub(r"\s+", " ", flattened)

    labeled = re.findall(
        r"(?:Booking|Space|Location):\s*Room\s+(\d+[A-Za-z]*)",
        collapsed,
        re.IGNORECASE,
    )
    unlabeled = re.findall(r"\bRoom\s+(\d+[A-Za-z]*)\b", collapsed, re.IGNORECASE)
    candidates = [f"Room {r.upper()}" for r in (labeled or unlabeled)]

    room_str = ""
    if expected_room:
        expected_key = normalize_room_key(expected_room)
        for candidate in candidates:
            if rooms_match(candidate, expected_room):
                room_str = candidate
                break
        if not room_str and expected_key and expected_key in re.sub(r"\s+", "", collapsed).upper():
            room_str = parse_room_name_from_title(expected_room)
    elif candidates:
        room_str = candidates[0]

    code_str = extract_checkin_code_from_email_text(flattened)
    checkin_link = unwrap_checkin_link(extract_checkin_link_from_email_text(text or flattened))
    return (room_str, code_str, checkin_link)


def add_booking_to_calendar(
    room_name: str,
    date_str: str,
    checkin_code: str = "",
    checkin_link: str = "",
    start_hhmm: str = "12:00",
    end_hhmm: str = "14:00",
    time_label: str = "12:00pm–2:00pm",
) -> bool:
    """
    Create/update a Google Calendar event only when check-in code/link exist.
    Placeholder events are not created — outlook_watcher adds the event after
    the forwarded LibCal confirmation arrives in board Outlook.
    """
    code = (checkin_code or "").strip()
    link = unwrap_checkin_link(checkin_link or "")
    if not code and not link:
        print(
            "Google Calendar skipped: no check-in code/link yet. "
            "Wait for forwarded LibCal mail, then run scrape-outlook."
        )
        return False

    print("Attempting to add event to Google Calendar...")
    try:
        from shared.google_auth import build_calendar_service, resolve_study_rooms_calendar_id
    except ImportError:
        print(
            "Google Calendar skipped: install google-auth google-auth-oauthlib "
            "google-api-python-client"
        )
        return False

    try:
        service = build_calendar_service(interactive=not RUN_HEADLESS)

        try:
            calendar_id = resolve_study_rooms_calendar_id(service)
        except Exception as exc:
            print(f"Google Calendar skipped: cannot open study-rooms calendar ({exc})")
            if STUDY_ROOMS_CALENDAR_ID:
                print(f"  STUDY_ROOMS_CALENDAR_ID={STUDY_ROOMS_CALENDAR_ID}")
            print(
                "Share the calendar with the service account "
                "(Make changes to events), or fix STUDY_ROOMS_CALENDAR_ID."
            )
            return False

        if not calendar_id:
            print(f"Google Calendar skipped: calendar '{STUDY_ROOMS_CALENDAR_NAME}' not found.")
            print(
                "Set STUDY_ROOMS_CALENDAR_ID in config/ucf_credentials.env "
                "(needed for service accounts)."
            )
            return False

        # Do not patch calendar metadata — that requires owner; SA is writer-only.

        start = f"{date_str}T{start_hhmm}:00"
        end = f"{date_str}T{end_hhmm}:00"
        summary = parse_room_name_from_title(room_name)
        desc_parts = []
        if code:
            desc_parts.append(f"Check-in Code: {code}")
        if link:
            desc_parts.append(f"Check-in link: {link}")
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "America/New_York"},
            "end": {"dateTime": end, "timeZone": "America/New_York"},
            "description": "\n".join(desc_parts),
        }

        existing = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=f"{date_str}T00:00:00-04:00",
                timeMax=f"{date_str}T23:59:59-04:00",
                singleEvents=True,
            )
            .execute()
            .get("items", [])
        )
        match = next(
            (
                item
                for item in existing
                if item.get("summary") == summary
                and (item.get("start") or {})
                .get("dateTime", "")
                .startswith(f"{date_str}T{start_hhmm}")
            ),
            None,
        )
        if match:
            created = (
                service.events()
                .patch(calendarId=calendar_id, eventId=match["id"], body=event)
                .execute()
            )
            print(
                f"Google Calendar event updated: {summary} ({time_label}) — "
                f"{created.get('htmlLink', created.get('id', 'ok'))}"
            )
        else:
            created = service.events().insert(calendarId=calendar_id, body=event).execute()
            print(
                f"Google Calendar event created: {summary} ({time_label}) — "
                f"{created.get('htmlLink', created.get('id', 'ok'))}"
            )
        return True
    except Exception as e:
        print(f"Google Calendar error: {e}")
        return False


def get_checkin_code_from_page(page) -> str:
    """Try to scrape the check-in code from the LibCal confirmation page."""
    _, code, _ = get_confirmation_from_libcal_page(page)
    return code


def _read_visible_page_text(page) -> str:
    try:
        return page.locator("body").inner_text()
    except Exception:
        try:
            return page.content()
        except Exception:
            return ""


def get_confirmation_from_libcal_page(page, expected_room: str = "") -> tuple[str, str, str]:
    """Parse room, check-in code, and link from the LibCal confirmation page."""
    try:
        time.sleep(1)
        text = _read_visible_page_text(page)
        room_str, code_str, checkin_link = parse_booking_confirmation(
            text, expected_room=expected_room
        )
        if not checkin_link:
            try:
                for link in page.locator('a[href*="libcal"], a[href*="checkin"], a[href*="safelinks"]').all():
                    href = (link.get_attribute("href") or "").strip()
                    if href:
                        checkin_link = unwrap_checkin_link(href)
                        if checkin_link:
                            break
            except Exception:
                pass
        if room_str or code_str or checkin_link:
            print(
                "LibCal confirmation page -> "
                f"room={room_str or '?'}, code={code_str or '?'}, link={checkin_link or '?'}"
            )
        return (room_str, code_str, checkin_link)
    except Exception as e:
        print(f"LibCal confirmation page: could not parse details: {e}")
        return ("", "", "")


def _read_outlook_message_body(page) -> tuple[str, str]:
    """Return (body_text, checkin_link) from the currently open Outlook message."""
    checkin_link = ""
    chunks: list[str] = []

    def collect_from(locator) -> None:
        nonlocal checkin_link
        try:
            locator.wait_for(state="visible", timeout=4000)
        except Exception:
            return
        try:
            chunks.append(locator.inner_text())
        except Exception:
            pass
        try:
            chunks.append(locator.inner_html())
        except Exception:
            pass
        try:
            for link in locator.locator(
                'a[href*="libcal"], a[href*="safelinks"], a:has-text("check in")'
            ).all():
                href = (link.get_attribute("href") or "").strip()
                if not href:
                    continue
                unwrapped = unwrap_checkin_link(href)
                if is_valid_checkin_link(unwrapped):
                    checkin_link = unwrapped
                    # Prefer an explicit check-in URL when present.
                    if "checkin" in unwrapped.lower() or "check-in" in unwrapped.lower():
                        break
        except Exception:
            pass

    try:
        page.get_by_text("Enter the code", exact=False).first.wait_for(timeout=8000)
    except Exception:
        try:
            page.get_by_text("Space:", exact=False).first.wait_for(timeout=4000)
        except Exception:
            pass

    for selector in (
        '[aria-label="Message body"]',
        '[role="document"]',
        ".readingPaneContainer",
        ".Xb2Vxb",
        '[aria-label*="Message"]',
    ):
        collect_from(page.locator(selector).first)

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            collect_from(frame.locator("body"))
        except Exception:
            continue

    if not chunks:
        try:
            chunks.append(page.locator("body").inner_text())
            chunks.append(page.locator("body").inner_html())
        except Exception:
            pass

    text = "\n".join(c for c in chunks if c)
    if not checkin_link:
        checkin_link = unwrap_checkin_link(extract_checkin_link_from_email_text(text))
    return text, checkin_link


def notify_booking(
    room_name: str,
    date_str: str,
    checkin_code: str = "",
    checkin_link: str = "",
    start_hhmm: str = "12:00",
    end_hhmm: str = "14:00",
    time_label: str = "12:00pm–2:00pm",
) -> None:
    """Add Google Calendar only when check-in code/link is known (from email)."""
    if not (checkin_code or "").strip() and not (checkin_link or "").strip():
        print(
            f"Booked {parse_room_name_from_title(room_name)} on {date_str} {time_label}. "
            f"Calendar waits for check-in code via forwarded LibCal mail → "
            f"{BOOKING_EMAIL or 'board Outlook'} (scrape-outlook)."
        )
        return
    print("Sending reminder (Google Calendar)...")
    if add_booking_to_calendar(
        room_name,
        date_str,
        checkin_code,
        checkin_link=checkin_link,
        start_hhmm=start_hhmm,
        end_hhmm=end_hhmm,
        time_label=time_label,
    ):
        print(
            f"Added event to Google Calendar: {parse_room_name_from_title(room_name)} "
            f"on {date_str} {time_label}."
        )
    else:
        print(f"Could not add calendar event for {room_name} on {date_str} {time_label}.")


def compute_target_date_and_window():
    """
    Book a room DAYS_AHEAD days from today (LibCal max advance = 3 days).

    Examples (DAYS_AHEAD=3):
      - Run on Tuesday  -> book Friday
      - Run on Friday   -> book Monday
    """
    today = datetime.today()
    target = today + timedelta(days=DAYS_AHEAD)

    date_str = target.strftime("%Y-%m-%d")
    start_time_label = "12:00"

    return date_str, start_time_label


def target_is_weekday(date_str: str) -> bool:
    """True if date_str (YYYY-MM-DD) is Monday–Friday."""
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5


def is_login_page(page) -> bool:
    """Check if the current page is a login/SSO page."""
    url = page.url.lower()
    return (
        "ucf.edu" in url
        or "login" in url
        or "idp" in url
        or "shibboleth" in url
        or "microsoftonline.com" in url
        or ("saml2" in url and "microsoftonline" in url)
    )


def wait_for_possible_redirect(page, timeout_seconds: int = 5):
    """Wait briefly for a possible SSO redirect after a page action."""
    for _ in range(timeout_seconds):
        if is_login_page(page):
            return True
        time.sleep(1)
    return is_login_page(page)


def is_libcal_ready(page) -> bool:
    """True when the large study rooms booking grid is loaded and SSO is finished."""
    if is_login_page(page):
        return False
    url = page.url.lower()
    if "libcal.com" not in url:
        return False
    try:
        page.locator(
            ".fc-datagrid, a.s-lc-eq-avail, .s-lc-eq-avail, .fc-timeline-body"
        ).first.wait_for(state="visible", timeout=3000)
        return True
    except Exception:
        return "largestudyrooms" in url and not is_login_page(page)


def is_outlook_ready(page) -> bool:
    """True when Outlook web mail is loaded (lenient — UI changes often)."""
    url = page.url.lower()
    if "login.microsoftonline.com" in url or "login.live.com" in url:
        return False
    if "login.microsoft.com" in url:
        return False
    if is_login_page(page) and "outlook" not in url:
        return False
    outlook_hosts = (
        "outlook.office.com",
        "outlook.live.com",
        "outlook.cloud.microsoft",
        "outlook.office365.com",
    )
    if not any(h in url for h in outlook_hosts):
        return False
    if "signin" in url or "/login" in url:
        return False

    # Passkey / Windows Hello / conditional access interstitial — not inbox yet.
    try:
        body = (page.inner_text("body", timeout=2000) or "").lower()
    except Exception:
        body = ""
    mfa_markers = (
        "face, fingerprint, pin or security key",
        "security window",
        "approve sign in",
        "approve the request",
        "enter code",
        "more information required",
        "verify your identity",
        "stay signed in",
        "sign in another way",
    )
    if any(m in body for m in mfa_markers):
        # "Stay signed in?" can appear after MFA — only block hard challenges.
        hard = (
            "face, fingerprint, pin or security key",
            "security window",
            "approve sign in",
            "approve the request",
            "more information required",
            "verify your identity",
            "sign in another way",
        )
        if any(m in body for m in hard):
            return False

    # Prefer evidence of the mail UI, not just an /mail URL.
    try:
        for sel in (
            '[role="listbox"]',
            '[data-convid]',
            '#topSearchInput',
            'input[aria-label*="Search"]',
            'div[aria-label*="Message list"]',
            'div[aria-label*="Folder pane"]',
            '[role="treeitem"]',
        ):
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                return True
    except Exception:
        pass

    if "/mail" in url or "/owa/" in url:
        # URL looks right but no mail chrome yet — treat as not ready.
        return False
    return False


def wait_for_site_ready(
    page,
    ready_check,
    timeout_seconds: int = 300,
    label: str = "site",
) -> bool:
    """Poll until ready_check(page) is true for two consecutive checks."""
    deadline = time.time() + timeout_seconds
    stable = 0
    last_status = 0.0
    while time.time() < deadline:
        if ready_check(page):
            stable += 1
            if stable >= 2:
                return True
        else:
            stable = 0
            now = time.time()
            if now - last_status >= 15:
                print(f"Still waiting for {label}... ({page.url[:80]})")
                last_status = now
        time.sleep(2)
    return ready_check(page)


def wait_for_login_complete(page, timeout_seconds: int = 300) -> bool:
    """Poll until SSO/login pages are finished."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_login_page(page):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            time.sleep(2)
            if not is_login_page(page):
                return True
        time.sleep(2)
    return not is_login_page(page)


def ensure_logged_in(page, account, redirect_after_login=True, interactive: bool = True):
    """
    If UCF SSO / Microsoft login appears:
    - If account credentials are set: fill them, submit, then handle 2FA.
    - Otherwise: prompt user to log in manually.
    - redirect_after_login: if True, after login go to BASE_URL; if False, stay on current page.
    """
    if not is_login_page(page):
        return

    print(f"Detected login page: {page.url} (account: {account.id})")

    if not (account.ucf_email and account.ucf_password):
        if interactive and not RUN_HEADLESS:
            print("No password on file — complete sign-in in the browser (session-only mode).")
            print("Log in manually, then press Enter here to continue...")
            wait_for_user()
        elif not wait_for_login_complete(page, timeout_seconds=30):
            print(
                f"Saved session expired for {account.id}. "
                f"Run ./sign-in.sh {account.id} (no password stored — browser MFA only)."
            )
            return
        if redirect_after_login:
            page.goto(BASE_URL, wait_until="networkidle")
        return

    # ── Step 1: Fill email ──
    print("Filling email...")
    try:
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        def type_into_email_input(loc):
            """Click, clear, then type so Microsoft's JS registers input (fill() often doesn't)."""
            inp = loc.first
            inp.wait_for(state="visible", timeout=8000)
            inp.click()
            time.sleep(0.2)
            inp.press("Control+a")
            time.sleep(0.1)
            inp.press_sequentially(account.ucf_email, delay=30)

        email_filled = False
        for placeholder in ["Email address, phone number", "Email, phone, or Skype", "email", "Email"]:
            try:
                type_into_email_input(page.get_by_placeholder(placeholder, exact=False))
                email_filled = True
                break
            except Exception:
                continue
        if not email_filled:
            try:
                type_into_email_input(page.get_by_label("Email", exact=False).or_(page.get_by_label("Username", exact=False)))
                email_filled = True
            except Exception:
                pass
        if not email_filled:
            for selector in [
                'input[type="email"]',
                'input[name="loginfmt"]',
                'input[id="i0116"]',
                'input[aria-label*="email" i]',
            ]:
                try:
                    type_into_email_input(page.locator(selector))
                    email_filled = True
                    break
                except Exception:
                    continue
        if not email_filled:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    type_into_email_input(frame.get_by_placeholder("Email address, phone number", exact=False))
                    email_filled = True
                    break
                except Exception:
                    try:
                        type_into_email_input(frame.locator('input[type="email"], input[name="loginfmt"]'))
                        email_filled = True
                        break
                    except Exception:
                        continue
        if not email_filled:
            raise RuntimeError("Could not find email input on login page.")

        page.locator('input[type="submit"], input[value="Next" i], button:has-text("Next")').first.click()
        time.sleep(3)

        # ── Step 2: Fill password ──
        print("Filling password...")
        pw_filled = False
        for selector in [
            'input[type="password"]',
            'input[name="passwd"]',
            'input[id="i0118"]',
            'input[placeholder*="password" i]',
            'input[aria-label*="password" i]',
        ]:
            try:
                el = page.locator(selector).first
                el.wait_for(state="visible", timeout=5000)
                el.click()
                time.sleep(0.3)
                el.fill(account.ucf_password)
                pw_filled = True
                break
            except Exception:
                continue
        if not pw_filled:
            try:
                page.get_by_label("Password", exact=False).first.click()
                time.sleep(0.2)
                page.get_by_label("Password", exact=False).first.fill(account.ucf_password)
                pw_filled = True
            except Exception:
                pass
        if not pw_filled:
            raise RuntimeError("Could not find password input on login page.")

        page.locator('input[type="submit"], input[value="Sign in" i], input[value="Log in" i], button:has-text("Sign in")').first.click()
        print("Signed in, waiting for 2FA page...")
        time.sleep(4)
    except Exception as e:
        print(f"Could not complete email/password step: {e}")
        if interactive:
            wait_for_user("Log in manually, then press Enter...")
        elif not wait_for_login_complete(page):
            print("Login timed out — finish sign-in and run ./sign-in.sh again.")
            return
        if redirect_after_login:
            page.goto(BASE_URL, wait_until="networkidle")
        return

    # ── Step 3: Handle 2FA ──
    # Click "I can't use my Outlook mobile app right now"
    print("Looking for 'I can't use my Outlook mobile app right now' link...")
    try:
        outlook_link = page.get_by_text("I can't use my Outlook mobile app right now", exact=False).first
        outlook_link.wait_for(state="visible", timeout=8000)
        outlook_link.click()
        print("Clicked 'I can't use my Outlook mobile app right now'.")
        time.sleep(3)
    except Exception as e:
        print(f"Could not find Outlook mobile link (may not be needed): {e}")

    # Click the "Text" SMS option to trigger the code
    print("Looking for 'Text' (SMS) option...")
    try:
        text_clicked = False
        for getter in [
            lambda: page.get_by_text("Text", exact=True).first,
            lambda: page.get_by_role("link", name="Text").first,
            lambda: page.get_by_role("button", name="Text").first,
            lambda: page.locator('[data-value="PhoneAppOTP"], [data-value="OneWaySMS"]').first,
        ]:
            try:
                el = getter()
                if el.is_visible(timeout=3000):
                    el.click()
                    text_clicked = True
                    print("Clicked 'Text' — SMS code requested.")
                    break
            except Exception:
                continue
        if not text_clicked:
            print("Could not find 'Text' option; 2FA method may already be selected.")
    except Exception as e:
        print(f"Error selecting SMS 2FA: {e}")

    time.sleep(2)

    # ── Step 4: Submit 2FA code ──
    code_submitted = False
    if USE_IMESSAGE_2FA:
        print(f"Waiting for SMS code from {UCF_2FA_SENDER} (polling iMessage for up to 180s)...")
        for _ in range(180):
            code = get_2fa_from_imessage(UCF_2FA_SENDER)
            if code:
                print(f"Got 2FA code from iMessage: {code}")
                code_submitted = submit_2fa_to_page(page, code)
                break
            time.sleep(1)

    if not code_submitted and not RUN_HEADLESS:
        print("Enter the SMS code in the browser, or type it in this terminal.")
        code = read_2fa_code_from_terminal()
        if code:
            print(f"Submitting 2FA code from terminal.")
            code_submitted = submit_2fa_to_page(page, code)

    if not code_submitted:
        if USE_IMESSAGE_2FA:
            print("Waiting for 2FA — complete sign-in in the browser if needed.")
        else:
            print("Complete 2FA in the browser (enter the SMS code on the login page).")
        if interactive:
            wait_for_user("Press Enter when login is complete...")

    if redirect_after_login and interactive:
        page.goto(BASE_URL, wait_until="networkidle")
    elif redirect_after_login and not interactive and not is_login_page(page):
        page.goto(BASE_URL, wait_until="networkidle")


def clear_selected_slot(page) -> bool:
    """Click the remove/trash control to clear the current LibCal selection."""
    for selector in [
        'button[title*="Remove"], button[title*="remove"]',
        'button[aria-label*="Remove"], button[aria-label*="remove"]',
        'a[title*="Remove"], a[title*="remove"]',
        '.fa-trash, .glyphicon-trash, [class*="trash"]',
        'button.btn-default:has(svg), .s-lc-eq-remove, [class*="remove"]',
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible():
                btn.click()
                time.sleep(0.4)
                return True
        except Exception:
            continue
    return False


def list_timeline_availability(page):
    """
    Large Study Rooms uses FullCalendar timeline: available cells have no title.
    Returns list of {room, resource_id, time_label, index} for a.s-lc-eq-avail slots.
    """
    return page.evaluate(
        """() => {
          const labels = [...document.querySelectorAll('.fc-datagrid-body .fc-datagrid-cell')]
            .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(t => /Room\\s+\\d+/i.test(t));
          const lanes = [...document.querySelectorAll('td.fc-timeline-lane.fc-resource')];
          const idToRoom = {};
          for (let i = 0; i < Math.min(labels.length, lanes.length); i++) {
            const id = lanes[i].getAttribute('data-resource-id');
            const m = labels[i].match(/Room\\s+(\\d+)([A-Za-z]*)/i);
            if (id && m) idToRoom[id] = 'Room ' + m[1] + (m[2] || '').toUpperCase();
          }
          const headers = [...document.querySelectorAll('th.fc-timeline-slot-label')].map(th => {
            const r = th.getBoundingClientRect();
            return { text: (th.innerText || '').trim(), mid: r.left + r.width / 2 };
          }).filter(h => h.text);
          const avail = [...document.querySelectorAll('a.s-lc-eq-avail')];
          const out = [];
          avail.forEach((a, index) => {
            const lane = a.closest('td.fc-timeline-lane.fc-resource');
            const rid = lane ? lane.getAttribute('data-resource-id') : null;
            const room = rid ? (idToRoom[rid] || null) : null;
            const rect = a.getBoundingClientRect();
            const mid = rect.left + rect.width / 2;
            let best = null, bestDist = Infinity;
            for (const h of headers) {
              const d = Math.abs(h.mid - mid);
              if (d < bestDist) { bestDist = d; best = h.text; }
            }
            if (room && best) out.push({ room, resource_id: rid, time_label: best, index });
          });
          return out;
        }"""
    )


def try_book_window(
    page,
    title_frag: str,
    end_hhmm: str,
    time_label: str,
    preferred_room: str | None = None,
    required_room: str | None = None,
):
    """
    Book a cap-10 large study room for a start time through end_hhmm (24h HH:MM).
    If required_room is set, only that room is attempted.
    Returns (room_name, time_label) on success, or (None, None).
    """
    availability = list_timeline_availability(page) or []
    matching = [
        a for a in availability
        if (a.get("time_label") or "").lower() == title_frag.lower()
    ]

    # Fallback for classic titled grids (regular study rooms page)
    if not matching:
        slots = page.locator(f'a.s-lc-eq-avail[title*="{title_frag}"]')
        if slots.count() == 0:
            print(f"No available {title_frag} slots on large study rooms grid.")
            return None, None
        matching = []
        for i in range(slots.count()):
            title = slots.nth(i).get_attribute("title") or ""
            matching.append({
                "room": parse_room_name_from_title(title),
                "time_label": title_frag,
                "index": i,
                "titled": True,
            })

    matching = [
        a for a in matching
        if is_capacity_10_room(a.get("room") or "")
        or (required_room and rooms_match(a.get("room") or "", required_room))
    ]

    if required_room:
        matching = [a for a in matching if rooms_match(a.get("room") or "", required_room)]
        if not matching:
            print(f"{required_room} is not available for {time_label}.")
            return None, None
    elif not matching:
        print(f"No capacity-10 rooms available at {title_frag}.")
        return None, None

    candidates = sorted(
        matching,
        key=lambda a: room_sort_key(
            a.get("room") or "",
            preferred_room=preferred_room or required_room,
            index=a.get("index", 0),
        ),
    )
    seen = set()
    unique = []
    for c in candidates:
        r = c.get("room") or ""
        if r in seen:
            continue
        seen.add(r)
        unique.append(c)

    priority_note = (
        f"only {required_room}"
        if required_room
        else (
            f"keep {preferred_room}"
            if preferred_room
            else f"cap-10 ({', '.join(PREFERRED_ROOMS)} first)"
        )
    )
    print(f"Checking {len(unique)} room(s) for {time_label} (priority: {priority_note})...")
    for c in unique:
        room = c.get("room") or ""
        tags = []
        if preferred_room and rooms_match(room, preferred_room):
            tags.append("same-room")
        if is_capacity_10_room(room):
            tags.append("cap-10")
        if room_preference_rank(room) < len(PREFERRED_ROOMS):
            tags.append("preferred")
        label = ", ".join(tags) if tags else "other"
        print(f"  - {room} [{label}]")

    for c in unique:
        room_for_this_slot = c.get("room") or "Study room"
        print(f"Trying {room_for_this_slot} at {title_frag}...")

        slot = None
        if c.get("titled"):
            slots_now = page.locator(f'a.s-lc-eq-avail[title*="{title_frag}"]')
            idx = c.get("index", 0)
            if idx < slots_now.count():
                slot = slots_now.nth(idx)
        else:
            now = list_timeline_availability(page) or []
            hit = next(
                (
                    x for x in now
                    if x.get("room") == room_for_this_slot
                    and (x.get("time_label") or "").lower() == title_frag.lower()
                ),
                None,
            )
            if hit is not None:
                slot = page.locator("a.s-lc-eq-avail").nth(hit["index"])

        if slot is None:
            print(f"Skipping {room_for_this_slot}: {title_frag} slot no longer in grid.")
            continue

        try:
            slot.scroll_into_view_if_needed()
            slot.wait_for(state="visible", timeout=3000)
        except Exception:
            continue
        slot.click()
        time.sleep(0.5)

        try:
            end_select = page.locator("select.b-end-date")
            end_select.wait_for(state="visible", timeout=3000)
        except Exception:
            continue

        end_value = end_select.evaluate(
            """(sel, want) => {
                for (let i = 0; i < sel.options.length; i++) {
                    const v = (sel.options[i].value || '');
                    if (v.indexOf(want) !== -1) return v;
                }
                return null;
            }""",
            end_hhmm,
        )

        if end_value:
            end_select.select_option(value=end_value)
            time.sleep(0.3)
            selected = end_select.evaluate(
                "sel => (sel.options[sel.selectedIndex] && sel.options[sel.selectedIndex].value) || ''"
            )
            if end_hhmm in (selected or ""):
                print(f"Selected {room_for_this_slot} for {time_label}.")
                return room_for_this_slot, time_label

        if not clear_selected_slot(page):
            print("Could not find the remove/garbage button; cannot try next room.")
            return None, None

    return None, None


def advance_days(page, days: int):
    """
    Click the date "next" button a given number of times
    to move forward in the LibCal grid.
    """
    for i in range(days):
        print(f"Advancing to day +{i + 1}...")
        clicked = False
        # Try a few different selectors that LibCal commonly uses
        try_selectors = [
            # Button with accessible name like "Next Day"
            lambda: page.get_by_role("button", name="Next Day"),
            lambda: page.get_by_role("button", name="Next"),
            # Fallback to common class used by FullCalendar
            lambda: page.locator("button.fc-next-button").first,
        ]
        for getter in try_selectors:
            try:
                btn = getter()
                if btn.is_visible():
                    btn.click()
                    clicked = True
                    page.wait_for_load_state("networkidle")
                    break
            except Exception:
                continue

        if not clicked:
            print("Could not find a 'next day' button to advance the date.")
            print("You may need to inspect the date navigation button and update the selectors.")
            break


def submit_booking_on_page(page, account) -> bool:
    """Click through LibCal submit flow after a time slot is selected."""
    print("Submitting times...")
    try:
        page.get_by_role("button", name="Submit Times").click()
    except Exception as e:
        print("Could not click 'Submit Times'. Adjust the button text/role selector.")
        print(f"Error: {e}")
        return False

    page.wait_for_load_state("networkidle")
    time.sleep(2)
    print(f"After Submit Times, URL: {page.url}")

    if wait_for_possible_redirect(page, timeout_seconds=8):
        print("SSO login required after Submit Times.")
        ensure_logged_in(page, account, redirect_after_login=False)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

    print("Looking for Continue button...")
    continue_clicked = False
    for cont_selector in [
        lambda: page.get_by_role("button", name="Continue"),
        lambda: page.locator("input[value='Continue']").first,
        lambda: page.locator("button:has-text('Continue')").first,
        lambda: page.locator("a:has-text('Continue')").first,
    ]:
        try:
            el = cont_selector()
            if el.is_visible(timeout=3000):
                el.click()
                continue_clicked = True
                print("Clicked Continue.")
                break
        except Exception:
            continue
    if not continue_clicked:
        print("No Continue button found; may have been skipped by auth redirect.")

    page.wait_for_load_state("networkidle")
    time.sleep(2)

    if wait_for_possible_redirect(page, timeout_seconds=5):
        print("SSO login required after Continue.")
        ensure_logged_in(page, account, redirect_after_login=False)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

    print("Filling booking form...")
    try:
        page.locator("input#nick").fill(account.public_name)
        page.locator("select#q2613").select_option(label="Undergraduate Student")
        page.locator("input#q2614").fill(account.ucf_id)
    except Exception as e:
        print("Could not fill some form fields; you may need to complete manually.")
        print(f"Error: {e}")

    try:
        print("Submitting booking...")
        page.get_by_role("button", name="Submit My Booking").click()
    except Exception:
        try:
            page.get_by_role("button", name="Submit").click()
        except Exception:
            page.locator("button:has-text('Submit'), input[value='Submit']").first.click()

    page.wait_for_load_state("networkidle")
    time.sleep(0.5)
    return True


def book_one_window(
    account,
    target_date: str,
    window: tuple,
    required_room: str | None = None,
    page=None,
    keep_session_open: bool = False,
) -> tuple[bool, str]:
    """
    Book one time window on target_date using the given account.
    Returns (success, room_name).

    If page is provided, uses the existing browser session (grid must already be loaded).
    """
    title_frag, start_hhmm, end_hhmm, time_label = window
    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    owns_browser = page is None
    booked_room = ""

    def run_booking(target_page) -> tuple[bool, str]:
        nonlocal booked_room
        if not wait_for_site_ready(target_page, is_libcal_ready, 30, label="LibCal"):
            print("LibCal grid not ready for booking.")
            return False, ""

        room, _ = try_book_window(
            target_page,
            title_frag,
            end_hhmm,
            time_label,
            required_room=required_room,
        )
        if not room:
            print(f"No large study room available for {time_label}.")
            return False, ""

        booked_room = room
        if not submit_booking_on_page(target_page, account):
            if not keep_session_open:
                wait_for_user("Press Enter to close...")
            return False, booked_room

        _, page_code, page_link = get_confirmation_from_libcal_page(
            target_page, expected_room=booked_room
        )
        # Calendar events only after check-in details from forwarded LibCal email
        # (outlook_watcher). Do not publish placeholders or page-scraped codes.
        checkin_code = ""
        checkin_link = ""
        if page_code or page_link:
            print(
                f"LibCal page had code={page_code or '?'} (not written to calendar; "
                f"waiting for forward → {BOOKING_EMAIL or 'board Outlook'})."
            )
        print(
            "Check-in codes come from forwarded LibCal mail → "
            f"{BOOKING_EMAIL or 'board Outlook'} (./scrape-outlook.sh)."
        )

        calendar_title = parse_room_name_from_title(booked_room)
        print(f"Calendar title for {time_label}: {calendar_title}")
        notify_booking(
            calendar_title,
            target_date,
            checkin_code,
            checkin_link=checkin_link,
            start_hhmm=start_hhmm,
            end_hhmm=end_hhmm,
            time_label=time_label,
        )

        if keep_session_open:
            print(f"Booked {booked_room} for {time_label}.")
        else:
            close_secs = 15 if PIPELINE_TEST else CLOSE_AFTER_SECONDS
            print(f"Booked {booked_room} for {time_label}. Closing in {close_secs}s...")
            time.sleep(close_secs)

        return True, booked_room

    if owns_browser:
        from browser_session import open_account_context

        with open_account_context(account) as (_p, _browser, context):
            target_page = context.new_page()
            if not prepare_libcal_grid(target_page, account):
                return False, ""
            return run_booking(target_page)

    return run_booking(page)


def book_room():
    target_date, _ = compute_target_date_and_window()
    windows = PIPELINE_TEST_WINDOWS if PIPELINE_TEST else FULL_DAY_WINDOWS

    accounts = load_accounts()
    if not accounts:
        print("No booking accounts found. Add data/accounts/*.env files (see data/accounts/example.env).")
        return

    forced_id = os.environ.get("ACCOUNT_ID", "").strip() or None
    used_account_ids: set[str] = set()

    print(f"Target date: {target_date} (today + {DAYS_AHEAD} days)")
    if SCHEDULED_RUN and not PIPELINE_TEST and not target_is_weekday(target_date):
        print(f"Skipping {target_date} — weekend study rooms are disabled (Mon–Fri only).")
        return
    if PIPELINE_TEST:
        print("PIPELINE_TEST=1: searching multiple time windows on large study rooms...")
    else:
        print("Full-day booking: 12pm–10pm on one cap-10 room, rotating accounts.")

    scan_account = accounts[0]
    if forced_id:
        for account in accounts:
            if account.id == forced_id:
                scan_account = account
                break

    print(f"\nDiscovering best cap-10 room ({scan_account.id})...")
    target_room, windows_to_book = discover_target_room_for_account(scan_account, windows)
    if not target_room or not windows_to_book:
        print("No capacity-10 large study room available for this date.")
        return

    print(f"Booking {target_room} for: {', '.join(w[3] for w in windows_to_book)}")

    from browser_session import open_account_context

    booked_count = 0
    for title_frag, start_hhmm, end_hhmm, time_label in windows_to_book:
        hours = booking_hours_from_window(start_hhmm, end_hhmm)
        account = pick_account(
            accounts,
            target_date,
            hours,
            forced_id=forced_id,
            exclude_ids=None if forced_id else used_account_ids,
        )
        if not account:
            print(f"Skipping {time_label}: no account with {hours:g}h capacity remaining.")
            continue

        print(f"\n=== {target_room} {time_label} — account: {account.id} ===")
        with open_account_context(account) as (_p, _browser, context):
            page = context.new_page()
            if not prepare_libcal_grid(page, account):
                print(f"Could not load LibCal for {account.id}.")
                continue

            book_title, book_start, book_end, book_label = (
                title_frag,
                start_hhmm,
                end_hhmm,
                time_label,
            )
            book_room_name = target_room
            if not room_supports_window(page, target_room, title_frag, end_hhmm):
                print(f"{target_room} no longer available for {time_label} — re-scanning...")
                found_room, rescanned = discover_target_room(page, windows)
                match = next((w for w in rescanned if w[3] == time_label), None)
                if not found_room or not match:
                    print(f"No room available for {time_label} on the current grid.")
                    continue
                book_room_name = found_room
                book_title, book_start, book_end, book_label = match

            ok, room = book_one_window(
                account,
                target_date,
                (book_title, book_start, book_end, book_label),
                required_room=book_room_name,
                page=page,
                keep_session_open=False,
            )
            if ok:
                record_booking(account, target_date, hours)
                used_account_ids.add(account.id)
                booked_count += 1
                print(f"Recorded {hours:g}h for {account.id} on {target_date}.")
            else:
                print(f"Failed to book {book_label} on {book_room_name}.")

    print(
        f"\nDone. {booked_count}/{len(windows_to_book)} window(s) booked for {target_date} in {target_room}."
    )
    if booked_count < len(windows) and len(accounts) < 3:
        print(f"Note: full 12pm–10pm coverage needs 3 accounts (you have {len(accounts)}).")


def _headless_test():
    """Quick test: launch headless, load booking page, exit. Use RUN_HEADLESS_TEST=1."""
    from shared.paths import PROFILES_DIR, as_str

    print("Headless test: launching browser...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=as_str(PROFILES_DIR / "_headless_test"),
            headless=True,
            args=[],
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        print("Headless test OK: browser launched and page loaded.")
        context.close()
    print("Done.")


if __name__ == "__main__":
    from shared.alerts import report_job

    if RUN_HEADLESS_TEST:
        try:
            _headless_test()
            report_job("book", ok=True, detail="headless test ok")
        except Exception as exc:
            report_job("book", ok=False, error=str(exc))
            raise
    else:
        try:
            book_room()
            report_job("book", ok=True, detail="booking run finished")
        except Exception as exc:
            report_job("book", ok=False, error=str(exc))
            raise


