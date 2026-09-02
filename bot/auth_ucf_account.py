#!/usr/bin/env python3
"""
Sign in a UCF booking account and save browser session cookies for the bot.

Each account gets its own Playwright profile under playwright-profiles/<id>/.
After a successful run, the study room bot can book using that account without
logging in again (until the session expires).

Before running:
  1. Copy accounts/example.env to accounts/<name>.env
  2. Fill in UCF_EMAIL, UCF_PASSWORD, UCF_ID
  3. PUBLIC_NAME is asked during sign-in

Usage:
  venv/bin/python3 auth_ucf_account.py <account_id>
  venv/bin/python3 auth_ucf_account.py josh

  ACCOUNT_ID=bob venv/bin/python3 auth_ucf_account.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import replace

from playwright.sync_api import sync_playwright

import study_room_bot as bot
from shared.accounts import ACCOUNTS_DIR, load_accounts
from shared.config import LIBCAL_RESERVE_URL, OUTLOOK_INBOX_URL


def find_account(account_id: str):
    for account in load_accounts():
        if account.id == account_id:
            return account
    return None


def save_public_name(account_id: str, public_name: str) -> None:
    env_path = os.path.join(ACCOUNTS_DIR, f"{account_id}.env")
    lines: list[str] = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("PUBLIC_NAME="):
                    lines.append(f"PUBLIC_NAME={public_name}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"PUBLIC_NAME={public_name}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.chmod(env_path, 0o600)


def prompt_public_name(account) -> str:
    existing = (account.public_name or "").strip()
    if existing and existing != "Student":
        return existing

    print()
    while True:
        name = input("Your public name (shown on LibCal bookings): ").strip()
        if name:
            save_public_name(account.id, name)
            return name
        print("Public name cannot be empty.")


def wait_for_enter(prompt: str) -> None:
    try:
        input(prompt)
    except EOFError:
        print("[non-interactive] continuing...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sign in a UCF account and save Playwright cookies for the study room bot."
    )
    parser.add_argument(
        "account_id",
        nargs="?",
        default=os.environ.get("ACCOUNT_ID", "").strip(),
        help="Account id (accounts/<id>.env), e.g. josh",
    )
    args = parser.parse_args()

    if not args.account_id:
        accounts = load_accounts()
        print("Usage: venv/bin/python3 auth_ucf_account.py <account_id>")
        print()
        if accounts:
            print("Available accounts:")
            for account in accounts:
                print(f"  - {account.id} ({account.masked_email})")
        else:
            print("No accounts found. Create data/accounts/<name>.env from data/accounts/example.env")
        raise SystemExit(1)

    account = find_account(args.account_id)
    if not account:
        env_path = os.path.join(ACCOUNTS_DIR, f"{args.account_id}.env")
        print(f"Account '{args.account_id}' not found.")
        print(f"Create {env_path} first (see data/accounts/example.env).")
        raise SystemExit(1)

    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    public_name = prompt_public_name(account)
    account = replace(account, public_name=public_name)

    print(f"Account:  {account.id} ({account.masked_email})")
    print(f"Profile:  {profile_dir}")
    print()
    print("A browser window will open (not headless).")
    print("1. Complete UCF SSO + 2FA on LibCal if prompted.")
    print("   On Linux/Pi: enter the SMS code in the browser or terminal.")
    print("2. The script will open Outlook so that session is saved too.")
    print("3. Press Enter here when both sites look logged in.")
    print()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            args=["--start-maximized"],
        )
        page = context.new_page()

        print(f"Opening LibCal: {LIBCAL_RESERVE_URL}")
        page.goto(LIBCAL_RESERVE_URL, wait_until="networkidle")
        bot.ensure_logged_in(page, account, redirect_after_login=True)
        time.sleep(2)

        if bot.is_login_page(page):
            print("Still on a login page — finish signing in in the browser.")
            wait_for_enter("Press Enter when LibCal loads and you are logged in... ")
            page.goto(LIBCAL_RESERVE_URL, wait_until="networkidle")
            time.sleep(2)

        if "largestudyrooms" in page.url.lower() or "libcal.com" in page.url.lower():
            print("LibCal session saved.")
        else:
            print(f"LibCal URL: {page.url}")

        print(f"Opening Outlook: {OUTLOOK_INBOX_URL}")
        page.goto(OUTLOOK_INBOX_URL, wait_until="networkidle")
        time.sleep(3)

        if bot.is_login_page(page):
            print("Outlook needs login — complete it in the browser.")
            wait_for_enter("Press Enter when Outlook inbox loads... ")
        else:
            print("Outlook session saved.")

        print()
        print(f"Done. Cookies stored in: {profile_dir}")
        print(f"Run bookings with: ACCOUNT_ID={account.id} RUN_HEADLESS=1 venv/bin/python3 bot/study_room_bot.py")
        wait_for_enter("Press Enter to close the browser... ")
        context.close()


if __name__ == "__main__":
    main()
