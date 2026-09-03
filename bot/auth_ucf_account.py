#!/usr/bin/env python3
"""
Sign in a UCF booking account and save browser session cookies for the bot.

Usage:
  venv/bin/python3 auth_ucf_account.py <account_id>
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import os
import subprocess
import sys
import time
from dataclasses import replace

from playwright.sync_api import sync_playwright

import study_room_bot as bot
from shared.accounts import ACCOUNTS_DIR, load_accounts
from shared.config import LIBCAL_RESERVE_URL, OUTLOOK_INBOX_URL

AUTH_TIMEOUT_SECONDS = 180
COOKIE_SETTLE_SECONDS = 2
OUTLOOK_URLS = (
    "https://outlook.office.com/mail/",
    OUTLOOK_INBOX_URL,
    "https://outlook.office.com/owa/",
)


def navigate_with_retry(page, urls, label: str, attempts: int = 3) -> bool:
    """Navigate with commit-level waits — Outlook often never reaches domcontentloaded."""
    if isinstance(urls, str):
        urls = (urls,)
    for url in urls:
        for attempt in range(1, attempts + 1):
            try:
                page.goto(url, wait_until="commit", timeout=90000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                return True
            except Exception as exc:
                print(f"{label}: load attempt {attempt}/{attempts} failed — {exc}")
                time.sleep(3)
    return False


def release_profile_lock(profile_dir: str) -> None:
    """Close a stuck Chromium using this profile so sign-in can start cleanly."""
    marker = f"user-data-dir={profile_dir}"
    try:
        subprocess.run(
            ["pkill", "-f", marker],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    lock = os.path.join(profile_dir, "SingletonLock")
    try:
        if os.path.lexists(lock):
            os.unlink(lock)
    except OSError:
        pass
    time.sleep(1)


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

    while True:
        name = input("Public name (LibCal bookings): ").strip()
        if name:
            save_public_name(account.id, name)
            return name
        print("Public name cannot be empty.")


def save_libcal_session(page, account) -> bool:
    print("Step 1/2: LibCal — complete 2FA in the browser if prompted.")
    if not navigate_with_retry(page, LIBCAL_RESERVE_URL, "LibCal"):
        return False
    time.sleep(2)

    if bot.is_login_page(page) or not bot.is_libcal_ready(page):
        bot.ensure_logged_in(page, account, redirect_after_login=False, interactive=True)

    if not bot.wait_for_site_ready(
        page, bot.is_libcal_ready, AUTH_TIMEOUT_SECONDS, label="LibCal"
    ):
        return False

    if "largestudyrooms" not in page.url.lower():
        navigate_with_retry(page, LIBCAL_RESERVE_URL, "LibCal", attempts=2)

    if not bot.wait_for_site_ready(page, bot.is_libcal_ready, 60, label="LibCal"):
        return False

    time.sleep(COOKIE_SETTLE_SECONDS)
    print("LibCal session saved.")
    return True


def save_outlook_session(page, account) -> bool:
    print("Step 2/2: Outlook — loading inbox.")
    if not navigate_with_retry(page, OUTLOOK_URLS, "Outlook"):
        print("Outlook navigation failed — checking if inbox loaded anyway...")
        if not bot.is_outlook_ready(page):
            return False

    time.sleep(3)

    if bot.is_login_page(page):
        print("Outlook sign-in — complete 2FA in the browser if prompted.")
        bot.ensure_logged_in(page, account, redirect_after_login=False, interactive=True)

    if bot.wait_for_site_ready(
        page, bot.is_outlook_ready, AUTH_TIMEOUT_SECONDS, label="Outlook"
    ):
        time.sleep(COOKIE_SETTLE_SECONDS)
        print("Outlook session saved.")
        return True

    # Lenient fallback: inbox URL without an active login redirect is good enough.
    url = page.url.lower()
    if "outlook.office.com" in url and not bot.is_login_page(page) and "signin" not in url:
        time.sleep(COOKIE_SETTLE_SECONDS)
        print("Outlook session saved.")
        return True

    return False


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
        if accounts:
            print("Available:", ", ".join(a.id for a in accounts))
        else:
            print("No accounts found. Run ./add-account.sh first.")
        raise SystemExit(1)

    account = find_account(args.account_id)
    if not account:
        env_path = os.path.join(ACCOUNTS_DIR, f"{args.account_id}.env")
        print(f"Account '{args.account_id}' not found. Create {env_path} first.")
        raise SystemExit(1)

    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)

    public_name = prompt_public_name(account)
    account = replace(account, public_name=public_name)

    print(f"Signing in {account.id} — browser closes when both steps finish.")

    context = None
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
            )
            page = context.new_page()
            try:
                if not save_libcal_session(page, account):
                    print("LibCal sign-in did not finish in time.")
                    raise SystemExit(1)

                if not save_outlook_session(page, account):
                    print("Outlook sign-in did not finish in time.")
                    print("LibCal cookies were saved — run ./sign-in.sh <id> to retry Outlook.")
                    raise SystemExit(1)

                print(f"Done — saved session for {account.id}.")
            except SystemExit:
                raise
            except Exception as exc:
                print(f"Sign-in error: {exc}")
                raise SystemExit(1) from exc
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                context = None
    except SystemExit:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
