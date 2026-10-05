#!/usr/bin/env python3
"""
Sign in a UCF booking account and save a Playwright storage session (no password).

Opens LibCal (and Outlook) for manual sign-in including 2FA, then saves cookies
to data/storage_states/<id>.json and closes the browser.

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
from shared.accounts import ACCOUNTS_DIR, find_account, load_accounts
from shared.config import LIBCAL_RESERVE_URL, OUTLOOK_INBOX_URL
from shared.paths import STORAGE_STATES_DIR, as_str, ensure_data_dirs

COOKIE_SETTLE_SECONDS = 2
MANUAL_AUTH_TIMEOUT_SECONDS = 600
OUTLOOK_URLS = (
    "https://outlook.office.com/mail/",
    OUTLOOK_INBOX_URL,
    "https://outlook.office.com/owa/",
)


def navigate_with_retry(page, urls, label: str, attempts: int = 3) -> bool:
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


def ensure_storage_state_key(account_id: str) -> str:
    ensure_data_dirs()
    rel = f"data/storage_states/{account_id}.json"
    env_path = os.path.join(ACCOUNTS_DIR, f"{account_id}.env")
    lines: list[str] = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("STORAGE_STATE="):
                    lines.append(f"STORAGE_STATE={rel}\n")
                    found = True
                elif line.strip().startswith("UCF_PASSWORD="):
                    # Session-only mode: never keep passwords on disk.
                    continue
                else:
                    lines.append(line)
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"STORAGE_STATE={rel}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.chmod(env_path, 0o600)
    return os.path.join(as_str(STORAGE_STATES_DIR), f"{account_id}.json")


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


def wait_for_manual_sign_in(page, ready_check, label: str) -> bool:
    print(f"\n{label}: sign in in the browser (including 2FA if prompted).")
    bot.wait_for_user(f"Press Enter when {label} is signed in and fully loaded...")
    if ready_check(page):
        return True
    print(f"Checking {label}...")
    return bot.wait_for_site_ready(
        page, ready_check, MANUAL_AUTH_TIMEOUT_SECONDS, label=label
    )


def save_libcal_session(page) -> bool:
    print("\nStep 1/2: LibCal")
    if not navigate_with_retry(page, LIBCAL_RESERVE_URL, "LibCal"):
        return False
    time.sleep(2)
    if not wait_for_manual_sign_in(page, bot.is_libcal_ready, "LibCal"):
        return False
    if "largestudyrooms" not in page.url.lower():
        navigate_with_retry(page, LIBCAL_RESERVE_URL, "LibCal", attempts=2)
        if not bot.wait_for_site_ready(page, bot.is_libcal_ready, 60, label="LibCal"):
            return False
    time.sleep(COOKIE_SETTLE_SECONDS)
    print("LibCal session ready.")
    return True


def save_outlook_session(page) -> bool:
    print("\nStep 2/2: Outlook")
    if not navigate_with_retry(page, OUTLOOK_URLS, "Outlook"):
        print("Outlook navigation failed — check the browser and try again.")
        return False
    time.sleep(3)
    if not wait_for_manual_sign_in(page, bot.is_outlook_ready, "Outlook"):
        return False
    time.sleep(COOKIE_SETTLE_SECONDS)
    print("Outlook session ready.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sign in a UCF account and save a Playwright session (no password stored)."
    )
    parser.add_argument(
        "account_id",
        nargs="?",
        default=os.environ.get("ACCOUNT_ID", "").strip(),
        help="Account id (accounts/<id>.env)",
    )
    args = parser.parse_args()

    if not args.account_id:
        accounts = load_accounts()
        print("Usage: venv/bin/python3 auth_ucf_account.py <account_id>")
        if accounts:
            print("Available:", ", ".join(a.id for a in accounts))
        else:
            print("No accounts found. Run ./import-cookies.sh or the intake site first.")

        raise SystemExit(1)

    account = find_account(args.account_id)
    if not account:
        env_path = os.path.join(ACCOUNTS_DIR, f"{args.account_id}.env")
        print(f"Account '{args.account_id}' not found. Create {env_path} first.")
        raise SystemExit(1)

    public_name = prompt_public_name(account)
    account = replace(account, public_name=public_name)
    state_path = ensure_storage_state_key(account.id)
    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    release_profile_lock(profile_dir)

    print(f"\nSigning in {account.id} — browser opens for manual sign-in.")
    print("No password is saved. Complete 2FA in the browser, then press Enter per step.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
        )
        page = context.new_page()
        try:
            if not save_libcal_session(page):
                print("LibCal sign-in did not finish in time.")
                raise SystemExit(1)
            if not save_outlook_session(page):
                print("Outlook sign-in did not finish in time.")
                print("LibCal session may still be usable — re-run for Outlook when ready.")
            context.storage_state(path=state_path)
            print(f"\nDone — saved session to {state_path}")
        finally:
            try:
                page.close()
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
