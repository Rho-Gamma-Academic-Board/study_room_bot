# Script by: Joshua Perez
# UCF LibCal large study room booking bot (Linux / Raspberry Pi / macOS).
# Uses Playwright, multi-account rotation, and Google Calendar.



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
    RUN_HEADLESS,
    RUN_HEADLESS_TEST,
    USE_IMESSAGE_2FA,
    STUDY_ROOMS_CALENDAR_NAME,
    STUDY_ROOMS_CALENDAR_DESCRIPTION,
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
    """
    rooms = cap10_rooms_on_grid(page)
    if not rooms:
        print("No capacity-10 rooms on the grid for this date.")
        return None, []

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


def discover_target_room_for_account(account, windows: list[tuple]) -> tuple[str | None, list[tuple]]:
    """Open LibCal on the target date and discover the best cap-10 room."""
    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=RUN_HEADLESS,
            args=["--start-maximized"] if not RUN_HEADLESS else [],
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        ensure_logged_in(page, account)
        advance_days(page, DAYS_AHEAD)
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        result = discover_target_room(page, windows)
        context.close()
    return result

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
    """Prompt for a 6-digit SMS code (Linux/Pi sign-in over SSH or RDP)."""
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


def extract_checkin_link_from_email_text(text: str) -> str:
    """Pull a LibCal check-in URL from confirmation email text or HTML."""
    if not text:
        return ""

    urls = re.findall(r'https?://[^\s<>"\']+', text, re.IGNORECASE)
    libcal_urls = []
    for url in urls:
        cleaned = url.rstrip(".,);]>\"'")
        if "libcal.com" in cleaned.lower():
            libcal_urls.append(cleaned)

    preferred_patterns = ("checkin", "check-in", "checkedin", "/booking/", "/reserve/")
    for pattern in preferred_patterns:
        for url in libcal_urls:
            if pattern in url.lower():
                return url

    return libcal_urls[0] if libcal_urls else ""


def add_booking_to_calendar(
    room_name: str,
    date_str: str,
    checkin_code: str = "",
    checkin_link: str = "",
    start_hhmm: str = "12:00",
    end_hhmm: str = "14:00",
    time_label: str = "12:00pm–2:00pm",
    include_checkin_description: bool = False,
) -> bool:
    """
    Create a Google Calendar event for the study room booking.
    Requires credentials.json and one-time OAuth (token.json) in the project folder.
    """
    print("Attempting to add event to Google Calendar...")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        print("Google Calendar skipped: install optional packages: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        return False

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = None
    token_path = GOOGLE_TOKEN_FILE
    creds_path = GOOGLE_CREDENTIALS_FILE

    if not os.path.exists(creds_path):
        print(f"Google Calendar skipped: credentials.json not found at {creds_path}")
        return False

    try:
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        service = build("calendar", "v3", credentials=creds)

        calendar_id = None
        page_token = None
        while True:
            calendar_list = service.calendarList().list(pageToken=page_token).execute()
            for cal in calendar_list.get("items", []):
                if cal.get("summary") == STUDY_ROOMS_CALENDAR_NAME:
                    calendar_id = cal["id"]
                    break
            else:
                page_token = calendar_list.get("nextPageToken")
                if not page_token:
                    break
                continue
            break

        if not calendar_id:
            print(f"Google Calendar skipped: calendar '{STUDY_ROOMS_CALENDAR_NAME}' not found.")
            return False

        service.calendars().patch(
            calendarId=calendar_id,
            body={
                "summary": STUDY_ROOMS_CALENDAR_NAME,
                "description": STUDY_ROOMS_CALENDAR_DESCRIPTION,
            },
        ).execute()

        # UCF is in Eastern; let the timeZone field handle EST/EDT automatically
        start = f"{date_str}T{start_hhmm}:00"
        end = f"{date_str}T{end_hhmm}:00"
        summary = f"Study room: {room_name}"
        if checkin_code:
            summary += f" ({checkin_code})"
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "America/New_York"},
            "end": {"dateTime": end, "timeZone": "America/New_York"},
        }
        if checkin_link:
            event["location"] = unwrap_checkin_link(checkin_link)
        if include_checkin_description:
            desc_parts = []
            if checkin_code:
                desc_parts.append(f"Check-in code: {checkin_code}")
            link = unwrap_checkin_link(checkin_link)
            if link:
                desc_parts.append(f"Check-in link: {link}")
            if desc_parts:
                event["description"] = "\n".join(desc_parts)
        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"Google Calendar event created: {created.get('htmlLink', created.get('id', 'ok'))}")
        return True
    except Exception as e:
        print(f"Google Calendar error: {e}")
        return False


def send_booking_email(room_name: str, date_str: str) -> bool:
    """Send a booking reminder to BOOKING_EMAIL. Set GMAIL_APP_PASSWORD (and optionally GMAIL_FROM) in env."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        return False
    from_addr = os.environ.get("GMAIL_FROM", BOOKING_EMAIL)

    msg = MIMEMultipart()
    msg["Subject"] = f"Study room booked: {room_name} – {date_str} 12:00–2:00pm"
    msg["From"] = from_addr
    msg["To"] = BOOKING_EMAIL
    body = f"You have a study room booking:\n\nRoom: {room_name}\nDate: {date_str}\nTime: 12:00pm – 2:00pm\n\n(UCF LibCal)"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(from_addr, password)
            s.sendmail(from_addr, BOOKING_EMAIL, msg.as_string())
        return True
    except Exception:
        return False


def get_checkin_code_from_page(page) -> str:
    """
    Try to scrape the check-in code from the LibCal confirmation page.
    Returns the code string or "" if not found.
    """
    try:
        time.sleep(1)
        # Prefer visible text so we match what the user sees
        try:
            text = page.locator("body").inner_text()
        except Exception:
            text = page.content()
        # Patterns: "check-in code: XXXXX", "Your code is ABC12", "Code: 12345"
        m = re.search(r"(?:check[- ]?in\s+code|confirmation\s+code|your\s+code)[:\s]+([A-Za-z0-9]{4,12})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"\bcode[:\s]+([A-Za-z0-9]{4,12})\b", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # Look for a standalone code in a likely element
        for sel in ["[class*='checkin']", "[class*='confirmation-code']", "[class*='booking-code']", "[class*='code']"]:
            try:
                for el in page.locator(sel).all():
                    if el.is_visible():
                        t = el.inner_text()
                        if t and re.match(r"^[A-Za-z0-9]{4,12}$", t.strip()):
                            return t.strip()
            except Exception:
                continue
    except Exception:
        pass
    return ""


def get_room_and_code_from_outlook(page, account) -> tuple[str, str, str]:
    """
    Open Outlook in the same browser (same cookies/session) and get room number,
    check-in code, and check-in link from the most recent LibCal confirmation email.
    Returns (room_str, code_str, checkin_link), e.g. ("Room 174", "4B4", "https://..."), or ("", "", "") if not found.
    Email body/ICS text looks like:
      Booking: Room 174
      ...
      Enter this code: 4B4
    """
    room_str = ""
    code_str = ""
    checkin_link = ""
    try:
        # Open Outlook inbox (same browser = same UCF/Outlook session)
        page.goto(OUTLOOK_INBOX_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(4)

        # If we hit a login page, we can't proceed
        if "login" in page.url.lower() or "signin" in page.url.lower():
            print(f"Outlook: not signed in in this browser; open Outlook and sign in as {account.id} ({account.masked_outlook}) for future runs.")
            return ("", "", "")

        # Search for emails from LibCal with subject "Your booking has been submitted" (newest first)
        try:
            search = page.locator('input[aria-label*="Search"], input[placeholder*="Search"], [aria-label*="Search"]').first
            search.wait_for(state="visible", timeout=8000)
            search.fill(
                f'from:{LIBCAL_SENDER} subject:"{LIBCAL_CONFIRMATION_SUBJECT}" to:{account.ucf_email}'
            )
            search.press("Enter")
            time.sleep(5)  # let search results fully load so first = most recent
        except Exception:
            pass

        # Open the single most recent message: first result in the list (Outlook shows newest first)
        try:
            # First message in results = most recent; wait for list to have items
            msg_list = page.locator('[role="listbox"] [role="option"], [data-convid], .ms-ListItem')
            msg_list.first.wait_for(state="visible", timeout=10000)
            time.sleep(1)
            msg_list.first.click()
            time.sleep(3)
        except Exception:
            try:
                page.locator(f'text="{LIBCAL_SENDER}"').first.click()
                time.sleep(3)
            except Exception:
                try:
                    page.locator('text="Booking"').first.click()
                    time.sleep(3)
                except Exception:
                    print(f"Outlook: could not open an email with subject '{LIBCAL_CONFIRMATION_SUBJECT}'.")
                    return ("", "", "")

        # Get the message body text (same text as in ICS)
        try:
            body = page.locator('[aria-label="Message body"], [role="document"], .readingPaneContainer, .Xb2Vxb').first
            body.wait_for(state="visible", timeout=6000)
            text = body.inner_text()
            for link in body.locator('a[href*="libcal"], a[href*="safelinks"]').all():
                href = (link.get_attribute("href") or "").strip()
                if href and ("libcal" in href.lower() or "safelinks" in href.lower()):
                    checkin_link = unwrap_checkin_link(href)
                    break
        except Exception:
            text = page.locator("body").inner_text()

        if not checkin_link:
            checkin_link = unwrap_checkin_link(extract_checkin_link_from_email_text(text))

        # Parse room line, e.g. "Space: Room 360H" or "Booking: Room 174"
        m_room = re.search(r"(?:Booking|Space):\s*Room\s+(\d+[A-Za-z]*)", text, re.IGNORECASE)
        if m_room:
            room_str = f"Room {m_room.group(1).upper()}"

        # Parse check-in code: "Enter the code 4B4 to check in." or "code 4B4"
        m_code = re.search(r"Enter the code\s+([A-Za-z0-9]+)", text, re.IGNORECASE)
        if not m_code:
            m_code = re.search(r"(?:check[- ]?in with |enter )?(?:the )?code\s+([A-Za-z0-9]{3,8})\b", text, re.IGNORECASE)
        if m_code:
            code_str = m_code.group(1).strip()

        if room_str or code_str or checkin_link:
            print(
                "Outlook: from latest LibCal email -> "
                f"room={room_str or '?'}, code={code_str or '?'}, link={checkin_link or '?'}"
            )
    except Exception as e:
        print(f"Outlook: could not get room/code from email: {e}")

    return (room_str, code_str, checkin_link)


def notify_booking(
    room_name: str,
    date_str: str,
    checkin_code: str = "",
    checkin_link: str = "",
    start_hhmm: str = "12:00",
    end_hhmm: str = "14:00",
    time_label: str = "12:00pm–2:00pm",
    include_checkin_description: bool = False,
) -> None:
    """Try to add a Google Calendar event, then fallback to email to BOOKING_EMAIL."""
    print("Sending reminder (Google Calendar or email)...")
    if add_booking_to_calendar(
        room_name,
        date_str,
        checkin_code,
        checkin_link=checkin_link,
        start_hhmm=start_hhmm,
        end_hhmm=end_hhmm,
        time_label=time_label,
        include_checkin_description=include_checkin_description,
    ):
        print(f"Added event to Google Calendar: {room_name} on {date_str} {time_label}. Check your calendar/reminders.")
    elif send_booking_email(room_name, date_str):
        print(f"Sent booking reminder to {mask_email(BOOKING_EMAIL)}.")
    else:
        print(f"Booking reminder: {room_name} on {date_str} {time_label}.")
        print("")
        print(">>> No reminder was sent. To get Google Calendar sign-in and events:")
        print(">>> 1. Install: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        print(">>> 2. Put credentials.json in this folder (you already have it).")
        print(">>> 3. Run the script again; a browser will open once for you to sign in with Google.")
        print("")


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


def ensure_logged_in(page, account, redirect_after_login=True):
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
        print("Set UCF_EMAIL and UCF_PASSWORD for this account.")
        print("Log in manually in the browser, then press Enter here to continue...")
        wait_for_user()
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
        wait_for_user("Log in manually, then press Enter...")
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
        print(f"Waiting for SMS code from {UCF_2FA_SENDER} (polling iMessage for up to 60s)...")
        for _ in range(60):
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
            print("Could not get 2FA code from iMessage.")
        else:
            print("Complete 2FA in the browser (enter the SMS code on the login page).")
        wait_for_user("Press Enter when login is complete...")

    if redirect_after_login:
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
    ]

    if not matching:
        print(f"No capacity-10 rooms available at {title_frag}.")
        return None, None

    if required_room:
        matching = [a for a in matching if rooms_match(a.get("room") or "", required_room)]
        if not matching:
            print(f"{required_room} is not available for {time_label}.")
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
) -> tuple[bool, str]:
    """
    Book one time window on target_date using the given account.
    Returns (success, room_name).
    """
    title_frag, start_hhmm, end_hhmm, time_label = window
    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    booked_room = ""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=RUN_HEADLESS,
            args=["--start-maximized"] if not RUN_HEADLESS else [],
        )
        page = context.new_page()

        page.goto(BASE_URL, wait_until="networkidle")
        ensure_logged_in(page, account)
        advance_days(page, DAYS_AHEAD)
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        room, _ = try_book_window(
            page,
            title_frag,
            end_hhmm,
            time_label,
            required_room=required_room,
        )
        if not room:
            print(f"No large study room available for {time_label}.")
            context.close()
            return False, ""

        booked_room = room
        if not submit_booking_on_page(page, account):
            wait_for_user("Press Enter to close...")
            context.close()
            return False, booked_room

        room_for_calendar = booked_room
        checkin_code = ""
        checkin_link = ""
        print(f"Waiting {OUTLOOK_WAIT_SECONDS} seconds for confirmation email, then opening Outlook...")
        time.sleep(OUTLOOK_WAIT_SECONDS)
        room_from_email, code_from_email, link_from_email = get_room_and_code_from_outlook(page, account)
        if room_from_email:
            room_for_calendar = room_from_email
        if code_from_email:
            checkin_code = code_from_email
        if link_from_email:
            checkin_link = link_from_email

        notify_booking(
            room_for_calendar,
            target_date,
            checkin_code,
            checkin_link=checkin_link,
            start_hhmm=start_hhmm,
            end_hhmm=end_hhmm,
            time_label=time_label,
        )

        close_secs = 15 if PIPELINE_TEST else CLOSE_AFTER_SECONDS
        print(f"Booked {booked_room} for {time_label}. Closing in {close_secs}s...")
        time.sleep(close_secs)
        context.close()

    return True, booked_room


def book_room():
    target_date, _ = compute_target_date_and_window()
    windows = PIPELINE_TEST_WINDOWS if PIPELINE_TEST else FULL_DAY_WINDOWS

    accounts = load_accounts()
    if not accounts:
        print("No booking accounts found. Add accounts/*.env files (see accounts/example.env).")
        return

    forced_id = os.environ.get("ACCOUNT_ID", "").strip() or None
    used_account_ids: set[str] = set()

    print(f"Target date: {target_date} (today + {DAYS_AHEAD} days)")
    if not PIPELINE_TEST and not target_is_weekday(target_date):
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
        ok, room = book_one_window(
            account,
            target_date,
            (title_frag, start_hhmm, end_hhmm, time_label),
            required_room=target_room,
        )
        if ok:
            record_booking(account, target_date, hours)
            used_account_ids.add(account.id)
            booked_count += 1
            print(f"Recorded {hours:g}h for {account.id} on {target_date}.")
        else:
            print(f"Failed to book {time_label} on {target_room}.")

    print(f"\nDone. {booked_count}/{len(windows_to_book)} window(s) booked for {target_date} in {target_room}.")
    if booked_count < len(windows) and len(accounts) < 3:
        print(f"Note: full 12pm–10pm coverage needs 3 accounts (you have {len(accounts)}).")


def _headless_test():
    """Quick test: launch headless, load booking page, exit. Use RUN_HEADLESS_TEST=1."""
    print("Headless test: launching browser...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="playwright-profile",
            headless=True,
            args=[],
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        print("Headless test OK: browser launched and page loaded.")
        context.close()
    print("Done.")

if __name__ == "__main__":
    if RUN_HEADLESS_TEST:
        _headless_test()
    else:
        book_room()


