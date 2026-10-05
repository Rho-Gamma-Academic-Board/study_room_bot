#!/usr/bin/env python3
"""
Scrape LibCal confirmation emails from the board Outlook Inbox
(BOOKING_EMAIL / OUTLOOK_SCRAPE_ACCOUNT) and upsert Google Calendar.

By default scrapes the normal Inbox. Set OUTLOOK_STUDY_ROOM_FOLDER only if
you still use a dedicated move-rule folder.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import os
import re
import sys
import time

from shared.accounts import find_account, load_accounts
from shared.config import (
    BOOKING_EMAIL,
    LIBCAL_CONFIRMATION_SUBJECT,
    LIBCAL_SENDER,
    OUTLOOK_INBOX_URL,
    OUTLOOK_STUDY_ROOM_FOLDER,
    OUTLOOK_WAIT_SECONDS,
    STUDY_ROOMS_CALENDAR_NAME,
)
from shared.google_auth import build_calendar_service
from shared.paths import DATA_DIR, as_str, ensure_data_dirs

import study_room_bot as bot
from browser_session import open_account_context
from calendar_from_mail import (
    find_calendar_id,
    parse_date_from_email,
    parse_times_from_email,
    upsert_event,
)

PROCESSED_FILE = as_str(DATA_DIR / "outlook_processed.json")


def resolve_board_account():
    """
    Account whose Playwright session can read the shared Outlook inbox.

    Prefer OUTLOOK_SCRAPE_ACCOUNT, then any account matching BOOKING_EMAIL
    (everyone forwards LibCal alerts there — often the same person who books).
    """
    nick = (
        os.environ.get("OUTLOOK_SCRAPE_ACCOUNT", "").strip()
        or os.environ.get("BOARD_OUTLOOK_ACCOUNT", "").strip()
    )
    if nick:
        acct = find_account(nick)
        if acct:
            return acct
        # Case-insensitive id match
        for a in load_accounts():
            if a.id.lower() == nick.lower():
                return a

    target = (BOOKING_EMAIL or "").strip().lower()
    if target:
        for a in load_accounts():
            if a.outlook.lower() == target or a.ucf_email.lower() == target:
                return a
    return None


def _load_processed() -> set[str]:
    if not os.path.exists(PROCESSED_FILE):
        return set()
    try:
        return set(json.loads(open(PROCESSED_FILE, encoding="utf-8").read()))
    except Exception:
        return set()


def _save_processed(ids: set[str]) -> None:
    ensure_data_dirs()
    trimmed = sorted(ids)[-500:]
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)


def _fingerprint(room: str, date_str: str, code: str, link: str) -> str:
    raw = f"{room}|{date_str}|{code}|{link}".strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _list_item_looks_like_libcal(msg) -> bool:
    """True if the message list row looks like LibCal (never open random mail)."""
    try:
        text = (msg.inner_text(timeout=1500) or "").lower()
    except Exception:
        return False
    if not text.strip():
        return False
    needles = (
        "libcal",
        "mail.libcal.com",
        "alerts@mail.libcal.com",
        "booking has been submitted",
        "springshare",
    )
    return any(n in text for n in needles)


def _is_libcal_confirmation_body(text: str) -> bool:
    """
    Hard gate: only treat the open message as a LibCal booking confirmation.

    Requires LibCal sender markers and/or the standard confirmation template.
    Random campus mail that happens to mention a room number must not pass.
    """
    collapsed = re.sub(r"\s+", " ", bot.flatten_confirmation_text(text or "")).lower()
    if not collapsed:
        return False

    from_libcal = (
        "alerts@mail.libcal.com" in collapsed
        or "@mail.libcal.com" in collapsed
        or "mail.libcal.com" in collapsed
    )
    subject_ok = "your booking has been submitted" in collapsed
    template_ok = (
        "enter the code" in collapsed
        and ("space:" in collapsed or "booking:" in collapsed or "location:" in collapsed)
    )
    # Prefer sender proof; allow template+subject if Outlook strips the From line in body.
    if from_libcal and (subject_ok or template_ok):
        return True
    if from_libcal and ("check in" in collapsed or "check-in" in collapsed):
        return True
    if subject_ok and template_ok:
        return True
    return False


def _libcal_search_queries() -> list[str]:
    """
    Outlook queries for LibCal confirmations.

    Direct LibCal mail keeps from:alerts@…. Auto-forwards often rewrite From to
    the brother's UCF address, so also search by subject alone (including FW:).
    """
    subject = LIBCAL_CONFIRMATION_SUBJECT
    return [
        f'from:{LIBCAL_SENDER} subject:"{subject}"',
        f'subject:"{subject}"',
        f'subject:"FW: {subject}"',
        f'subject:"Fwd: {subject}"',
        f'"{subject}"',
    ]


def _goto_outlook_search(page, query: str) -> bool:
    """Navigate Outlook to a search results view for `query`."""
    from urllib.parse import quote

    search_urls = (
        f"https://outlook.cloud.microsoft/mail/0/search/query/{quote(query)}",
        f"https://outlook.office.com/mail/search/results?query={quote(query)}",
        f"https://outlook.office.com/mail/?path=/search/query/{quote(query)}",
    )
    for url in search_urls:
        try:
            page.goto(url, wait_until="commit", timeout=45000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(3)
            if "login" in page.url.lower() or "signin" in page.url.lower():
                continue
            print(f"Outlook: opened LibCal search URL for `{query}`")
            return True
        except Exception:
            continue

    selectors = (
        "#topSearchInput",
        'input[aria-label*="Search for email"]',
        'input[aria-label*="Search"]',
        'input[placeholder*="Search"]',
        'input[role="combobox"][placeholder*="Search"]',
    )
    for sel in selectors:
        try:
            search = page.locator(sel).first
            search.wait_for(state="visible", timeout=5000)
            search.click(timeout=5000)
            search.fill("")
            search.fill(query)
            search.press("Enter")
            time.sleep(3)
            print(f"Outlook: searching `{query}`")
            return True
        except Exception:
            continue
    return False


def _search_result_count(page) -> int:
    """How many message rows are visible after a search (0 if none/unknown)."""
    msg_list = page.locator(
        '[role="listbox"] [role="option"], [data-convid], .ms-ListItem'
    )
    try:
        msg_list.first.wait_for(state="visible", timeout=5000)
    except Exception:
        return 0
    try:
        return msg_list.count()
    except Exception:
        return 0


def _run_libcal_search(page) -> bool:
    """Search Outlook for LibCal confirmations only. Returns False if search failed."""
    last_ok_query = ""
    for query in _libcal_search_queries():
        if not _goto_outlook_search(page, query):
            continue
        last_ok_query = query
        n = _search_result_count(page)
        print(f"Outlook: search `{query}` → {n} result row(s)")
        if n > 0:
            return True

    if last_ok_query:
        # Search UI worked but every query was empty — still allow the last
        # subject-only view so callers can re-check / wait for new mail.
        print(
            f"Outlook: no rows yet; leaving last search `{last_ok_query}` open"
        )
        return True

    print(
        "Outlook: LibCal search failed — refusing to scan unfiltered Inbox"
    )
    return False


def _folder_name_candidates(folder: str) -> list[str]:
    base = (folder or "Study Rooms").strip()
    alts = [
        base,
        base.title(),
        base.lower(),
        "Study Rooms",
        "study rooms",
        "Study Room",
        "study room",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for name in alts:
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def open_study_room_folder(page, folder: str | None = None) -> bool:
    """
    Open an Outlook folder by name. Empty / 'Inbox' leaves the default Inbox.
    Returns True if a non-inbox folder click succeeded.
    """
    target = (folder if folder is not None else OUTLOOK_STUDY_ROOM_FOLDER or "").strip()
    if not target or target.casefold() in ("inbox", "mail"):
        print("Outlook: using Inbox.")
        try:
            page.get_by_role("treeitem", name=re.compile(r"^Inbox$", re.I)).first.click(
                timeout=2500
            )
            time.sleep(1.5)
        except Exception:
            pass
        return True

    print(f"Outlook: opening folder '{target}'…")

    # Ensure folder pane is visible (sometimes collapsed on narrow layouts).
    for toggle in (
        'button[aria-label*="Folder pane"]',
        'button[aria-label*="Show folder"]',
        'button[aria-label*="Navigation"]',
    ):
        try:
            btn = page.locator(toggle).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=1500)
                time.sleep(0.5)
                break
        except Exception:
            pass

    for name in _folder_name_candidates(target):
        locators = [
            page.get_by_role("treeitem", name=name),
            page.locator(f'[role="treeitem"][aria-label="{name}"]'),
            page.locator(f'[role="treeitem"][title="{name}"]'),
            page.locator(f'[aria-label="{name}"][role="treeitem"]'),
            page.get_by_role("treeitem", name=re.compile(rf"^{re.escape(name)}$", re.I)),
            page.locator('[role="treeitem"]').filter(has_text=re.compile(rf"^{re.escape(name)}$", re.I)),
        ]
        for loc in locators:
            try:
                item = loc.first
                item.wait_for(state="visible", timeout=2500)
                item.click(timeout=2500)
                time.sleep(2.5)
                print(f"Outlook: opened folder '{name}'.")
                return True
            except Exception:
                continue

    # Last resort: folder search / filter in left nav
    try:
        filt = page.locator(
            'input[aria-label*="Filter"], input[placeholder*="Filter"], input[aria-label*="Search folders"]'
        ).first
        if filt.count():
            filt.fill(target)
            time.sleep(1)
            page.get_by_role("treeitem").filter(
                has_text=re.compile(re.escape(target), re.I)
            ).first.click(timeout=3000)
            time.sleep(2.5)
            print(f"Outlook: opened folder via filter '{target}'.")
            return True
    except Exception:
        pass

    print(f"Outlook: could not find folder '{target}' — falling back to Inbox search.")
    return False


def _iter_recent_messages(page, limit: int = 15):
    msg_list = page.locator(
        '[role="listbox"] [role="option"], [data-convid], .ms-ListItem'
    )
    try:
        msg_list.first.wait_for(state="visible", timeout=8000)
    except Exception:
        return
    count = min(msg_list.count(), limit)
    for i in range(count):
        yield msg_list.nth(i)


def process_once(
    *,
    expected_room: str = "",
    expected_date: str = "",
    wait_seconds: int | None = None,
    headless: bool = True,
    interactive: bool = False,
) -> dict:
    """
    Open board Outlook Inbox, read LibCal confirmations, upsert Calendar.
    Returns {ok, updated, detail, events: [...]}.
    """
    ensure_data_dirs()
    account = resolve_board_account()
    if not account:
        return {
            "ok": False,
            "updated": 0,
            "detail": (
                "No Outlook scrape account. Set OUTLOOK_SCRAPE_ACCOUNT to the "
                "nickname that owns BOOKING_EMAIL (e.g. Josh), or ensure that "
                "account's UCF_EMAIL matches BOOKING_EMAIL."
            ),
            "events": [],
        }
    if not account.uses_storage_state() and not os.path.isdir(account.profile_dir()):
        return {
            "ok": False,
            "updated": 0,
            "detail": (
                f"No Outlook session for '{account.id}'. Run: "
                "./venv/bin/python3 bot/auth_board_outlook.py"
            ),
            "events": [],
        }

    cal = build_calendar_service(interactive=interactive)
    calendar_id = find_calendar_id(cal)
    if not calendar_id:
        return {
            "ok": False,
            "updated": 0,
            "detail": f"Calendar '{STUDY_ROOMS_CALENDAR_NAME}' not found.",
            "events": [],
        }

    wait = OUTLOOK_WAIT_SECONDS if wait_seconds is None else max(0, wait_seconds)
    if wait:
        print(f"Waiting {wait}s for LibCal mail to arrive in Outlook...")
        time.sleep(wait)

    processed = _load_processed()
    updated = 0
    events: list[dict] = []
    detail = ""
    folder = OUTLOOK_STUDY_ROOM_FOLDER  # empty → Inbox

    os.environ.setdefault("RUN_HEADLESS", "1" if headless else "0")

    with open_account_context(account, headless=headless) as (_p, _b, context):
        page = context.new_page()
        page.goto(OUTLOOK_INBOX_URL, wait_until="commit", timeout=45000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        time.sleep(3)

        # Headed runs: allow Duo/MFA to finish before giving up.
        if not bot.is_outlook_ready(page):
            if headless:
                return {
                    "ok": False,
                    "updated": 0,
                    "detail": (
                        f"Outlook session expired for {account.id}. Re-run "
                        "bot/auth_board_outlook.py and sign in again."
                    ),
                    "events": [],
                }
            print(
                f"Outlook: waiting for sign-in / MFA for {account.id} "
                "(up to 5 min)…"
            )
            mfa_deadline = time.time() + 300
            while time.time() < mfa_deadline:
                if bot.is_outlook_ready(page):
                    print(f"Outlook: inbox ready — {page.url}")
                    break
                time.sleep(2)
            else:
                return {
                    "ok": False,
                    "updated": 0,
                    "detail": (
                        f"Outlook sign-in timed out for {account.id}. "
                        "Finish Duo in the browser and retry."
                    ),
                    "events": [],
                }
        else:
            print(f"Outlook: inbox ready — {page.url}")

        in_folder = open_study_room_folder(page, folder)
        deadline = time.time() + max(wait, 45)
        found_any = False
        search_failed = False

        while time.time() < deadline:
            # Search Inbox (or optional custom folder) for LibCal mail ONLY.
            # Never fall through to scanning the unfiltered Inbox.
            # Try several queries — forwards often drop the original From:.
            any_search_ok = False
            for query in _libcal_search_queries():
                if time.time() >= deadline:
                    break
                if not _goto_outlook_search(page, query):
                    continue
                any_search_ok = True
                n = _search_result_count(page)
                print(f"Outlook: search `{query}` → {n} result row(s)")
                if n == 0:
                    continue

                for msg in _iter_recent_messages(page, limit=40):
                    if not _list_item_looks_like_libcal(msg):
                        continue
                    try:
                        msg.click(timeout=3000)
                        time.sleep(1.5)
                    except Exception:
                        continue

                    text, href_link = bot._read_outlook_message_body(page)
                    if not _is_libcal_confirmation_body(text):
                        print("Outlook: skipped non-LibCal message.")
                        continue

                    room, code, link = bot.parse_booking_confirmation(
                        text, expected_room=expected_room
                    )
                    # Prefer a validated LibCal check-in URL; never keep Handshake/tracking junk.
                    if href_link and bot.is_valid_checkin_link(href_link):
                        link = href_link
                    elif link and not bot.is_valid_checkin_link(link):
                        link = ""
                    if link and not bot.is_valid_checkin_link(link):
                        link = ""
                    date_str = parse_date_from_email(text) or expected_date
                    start_hhmm, end_hhmm = parse_times_from_email(text)

                    if expected_room and room and not bot.rooms_match(room, expected_room):
                        continue
                    if expected_date and date_str and date_str != expected_date:
                        continue
                    if not room or not date_str or not (code or link):
                        print(
                            f"Outlook: incomplete parse "
                            f"room={room or '?'} date={date_str or '?'} "
                            f"code={code or '?'} link={bool(link)}"
                        )
                        continue

                    found_any = True
                    fp = _fingerprint(room, date_str, code, link)
                    if fp in processed:
                        continue

                    if upsert_event(
                        cal,
                        calendar_id,
                        room,
                        date_str,
                        start_hhmm,
                        end_hhmm,
                        code,
                        link,
                    ):
                        updated += 1
                        events.append(
                            {
                                "room": room,
                                "date": date_str,
                                "code": code,
                                "link": link,
                                "start_hhmm": start_hhmm,
                                "end_hhmm": end_hhmm,
                            }
                        )
                        processed.add(fp)

                if expected_room and updated:
                    break

            if not any_search_ok:
                search_failed = True
                break

            if expected_room and updated:
                break
            if found_any and not expected_room:
                break
            if expected_room:
                print(
                    f"Outlook: waiting for confirmation for {expected_room} "
                    f"in Inbox..."
                )
                time.sleep(5)
            else:
                break

        where = f"folder '{folder}'" if folder else "Inbox"
        if search_failed:
            detail = (
                "Could not run LibCal-only Outlook search. "
                "Inbox was not scanned to avoid non-LibCal mail."
            )
        elif not found_any:
            detail = (
                f"No LibCal confirmation found in Outlook {where}. "
                f"Confirm alerts are forwarded to {BOOKING_EMAIL or account.outlook}."
            )
        elif updated == 0:
            detail = (
                f"Found confirmation(s) in {where} but they were already on the calendar."
            )
        else:
            detail = f"Created/updated {updated} calendar event(s) from {where}."

    _save_processed(processed)
    print(f"Outlook watcher: {detail}")
    return {
        "ok": True,
        "updated": updated,
        "detail": detail,
        "events": events,
        "folder": folder,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape board Outlook LibCal mail and update Google Calendar."
    )
    parser.add_argument("--once", action="store_true", help="Single pass (default).")
    parser.add_argument("--expected-room", default="", help="Match this room only.")
    parser.add_argument("--expected-date", default="", help="YYYY-MM-DD")
    parser.add_argument(
        "--wait",
        type=int,
        default=None,
        help="Seconds to wait before scraping (email delivery).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser (debug).",
    )
    args = parser.parse_args()
    from shared.alerts import report_job

    try:
        result = process_once(
            expected_room=args.expected_room,
            expected_date=args.expected_date,
            wait_seconds=args.wait,
            headless=not args.headed,
            interactive=True,
        )
        if not result.get("ok"):
            detail = result.get("detail") or "Outlook scrape failed"
            print(f"Outlook watcher failed: {detail}", file=sys.stderr)
            report_job(
                "scrape",
                ok=False,
                error=detail,
                detail=detail,
            )
            raise SystemExit(1)
        print(result.get("detail") or f"updated={result.get('updated', 0)}")
        report_job(
            "scrape",
            ok=True,
            detail=result.get("detail") or f"updated={result.get('updated', 0)}",
        )
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        report_job("scrape", ok=False, error=str(exc))
        raise


if __name__ == "__main__":
    main()
