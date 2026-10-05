#!/usr/bin/env python3
"""
Import a Playwright storageState JSON (LibCal cookies) as a booking account.

No passwords are stored. The patron should forward LibCal mail
(from alerts@mail.libcal.com) to jo564454@ucf.edu so check-in
codes can be scraped into Google Calendar.

Usage:
  ./import-cookies.sh <nickname> /path/to/authState.json
  ./venv/bin/python3 bot/import_cookies.py <nickname> /path/to/authState.json
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import sys

from shared.cookie_import import CookieImportError, import_storage_state


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import LibCal Playwright cookies (storageState) — no password stored."
    )
    parser.add_argument("nickname", help="Account id, e.g. josh or ca833033")
    parser.add_argument("cookie_file", help="Path to Playwright storageState JSON")
    parser.add_argument("--email", default="", help="UCF email (default: <nickname>@ucf.edu)")
    parser.add_argument("--nid", default="", help="NID / UCF ID for the booking form")
    parser.add_argument("--name", default="", help="Public name on LibCal bookings")
    args = parser.parse_args()

    nickname = args.nickname.strip()
    nid = args.nid.strip()
    email = args.email.strip()
    name = args.name.strip()

    if not name and sys.stdin.isatty():
        entered = input(f"Public name [{nickname}]: ").strip()
        if entered:
            name = entered
    if not nid and sys.stdin.isatty():
        entered = input(f"UCF ID / NID [{nickname}]: ").strip()
        if entered:
            nid = entered
            if not email:
                email = f"{nid}@ucf.edu"

    try:
        with open(args.cookie_file, "rb") as f:
            raw = f.read()
        result = import_storage_state(
            nickname,
            raw,
            email=email,
            nid=nid,
            public_name=name,
        )
    except CookieImportError as exc:
        print(exc)
        raise SystemExit(1) from exc
    except FileNotFoundError:
        print(f"Cookie file not found: {args.cookie_file}")
        raise SystemExit(1)

    print(f"Imported cookies -> {result.storage_state_path}")
    print(f"Account file    -> {result.env_path}")
    print()
    print("Ask this person to forward LibCal mail to jo564454@ucf.edu:")
    print("  Outlook rule: From alerts@mail.libcal.com → forward to jo564454@ucf.edu")
    print()
    print("No password stored. Book with: ./run-bot.sh --now")


if __name__ == "__main__":
    main()
