#!/usr/bin/env python3
"""
Sign into the shared Outlook inbox (BOOKING_EMAIL) and save Playwright cookies.

Everyone forwards LibCal alerts here. This is usually the same account that also
books rooms (e.g. Josh / jo564454@ucf.edu). Existing LibCal cookies are kept and
Outlook cookies are merged into the same storageState.

Usage:
  ./venv/bin/python3 bot/auth_board_outlook.py
  OUTLOOK_SCRAPE_ACCOUNT=Josh ./venv/bin/python3 bot/auth_board_outlook.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from shared.accounts import find_account, load_accounts
from shared.config import BOOKING_EMAIL, OUTLOOK_INBOX_URL
from shared.paths import ACCOUNTS_DIR, STORAGE_STATES_DIR, as_str, ensure_data_dirs

import study_room_bot as bot
from auth_ucf_account import (
    OUTLOOK_URLS,
    ensure_storage_state_key,
    navigate_with_retry,
    release_profile_lock,
    wait_for_manual_sign_in,
)

COOKIE_SETTLE_SECONDS = 3


def _resolve_account_id() -> str:
    nick = (
        os.environ.get("ACCOUNT_ID", "").strip()
        or os.environ.get("OUTLOOK_SCRAPE_ACCOUNT", "").strip()
    )
    if nick and find_account(nick):
        return nick

    target = (BOOKING_EMAIL or "").strip().lower()
    if target:
        for a in load_accounts():
            if a.outlook.lower() == target or a.ucf_email.lower() == target:
                return a.id

    if nick:
        return nick
    return "Josh"


def _ensure_account_env(account_id: str) -> None:
    path = os.path.join(as_str(ACCOUNTS_DIR), f"{account_id}.env")
    if os.path.exists(path):
        return
    ensure_data_dirs()
    email = BOOKING_EMAIL or "jo564454@ucf.edu"
    nid = email.split("@")[0] if "@" in email else account_id
    lines = [
        f"UCF_EMAIL={email}",
        f"OUTLOOK_EMAIL={email}",
        f"UCF_NID={nid}",
        f"UCF_ID={nid}",
        f"PUBLIC_NAME={account_id}",
        f"STORAGE_STATE=data/storage_states/{account_id}.json",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(path, 0o600)
    print(f"Created {path}")


def _merge_storage_states(existing_path: str, new_path: str) -> None:
    """Keep prior LibCal cookies; overlay Outlook cookies from new_path."""
    if not os.path.exists(new_path):
        return
    with open(new_path, encoding="utf-8") as f:
        fresh = json.load(f)
    merged = {"cookies": [], "origins": []}
    seen: set[tuple] = set()

    def add_cookie(c: dict) -> None:
        key = (c.get("name"), c.get("domain"), c.get("path", "/"))
        if key in seen:
            return
        seen.add(key)
        merged["cookies"].append(c)

    if os.path.exists(existing_path) and os.path.abspath(existing_path) != os.path.abspath(
        new_path
    ):
        try:
            with open(existing_path, encoding="utf-8") as f:
                old = json.load(f)
            for c in old.get("cookies") or []:
                add_cookie(c)
            merged["origins"] = list(old.get("origins") or [])
        except Exception:
            pass

    for c in fresh.get("cookies") or []:
        key = (c.get("name"), c.get("domain"), c.get("path", "/"))
        # Prefer fresh cookie for same key
        merged["cookies"] = [
            x
            for x in merged["cookies"]
            if (x.get("name"), x.get("domain"), x.get("path", "/")) != key
        ]
        seen.discard(key)
        add_cookie(c)

    # Prefer fresh origins for same origin URL
    by_origin = {o.get("origin"): o for o in merged["origins"] if o.get("origin")}
    for o in fresh.get("origins") or []:
        if o.get("origin"):
            by_origin[o["origin"]] = o
    merged["origins"] = list(by_origin.values())

    Path(existing_path).parent.mkdir(parents=True, exist_ok=True)
    with open(existing_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    os.chmod(existing_path, 0o600)


def main() -> None:
    account_id = _resolve_account_id()
    _ensure_account_env(account_id)
    account = find_account(account_id)
    if not account:
        print(f"Account '{account_id}' not found after creating env.")
        print("Available:", ", ".join(a.id for a in load_accounts()) or "(none)")
        raise SystemExit(1)

    state_path = ensure_storage_state_key(account.id)
    profile_dir = account.profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    release_profile_lock(profile_dir)

    email = account.outlook or BOOKING_EMAIL or "jo564454@ucf.edu"
    print(f"\nOutlook sign-in for {account.id} ({email})")
    print("This inbox receives everyone's forwarded LibCal alerts.")
    print("A browser window will open. Sign in with Duo if asked.")
    print("When you can see the Outlook inbox, return here and press Enter.\n")

    with sync_playwright() as p:
        # Seed with existing LibCal cookies when present.
        launch_kwargs: dict = {
            "user_data_dir": profile_dir,
            "headless": False,
        }
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        if account.uses_storage_state():
            try:
                with open(account.storage_state_path(), encoding="utf-8") as f:
                    prior = json.load(f)
                cookies = prior.get("cookies") or []
                if cookies:
                    context.add_cookies(cookies)
                    print(f"Loaded {len(cookies)} existing cookie(s) from LibCal session.")
            except Exception as exc:
                print(f"Could not preload LibCal cookies: {exc}")

        page = context.new_page()
        try:
            if not navigate_with_retry(page, OUTLOOK_URLS, "Outlook"):
                print("Could not open Outlook.")
                raise SystemExit(1)
            time.sleep(2)
            if not wait_for_manual_sign_in(page, bot.is_outlook_ready, "Outlook"):
                print("Outlook sign-in did not finish.")
                raise SystemExit(1)
            time.sleep(COOKIE_SETTLE_SECONDS)
            os.makedirs(as_str(STORAGE_STATES_DIR), exist_ok=True)
            tmp = state_path + ".outlook-tmp.json"
            context.storage_state(path=tmp)
            _merge_storage_states(state_path, tmp)
            try:
                os.remove(tmp)
            except OSError:
                pass
            print(f"\nSaved merged session → {state_path}")
            print("LibCal booking cookies kept; Outlook cookies added.")
            print("Scrape with: ./scrape-outlook.sh --once")
        finally:
            try:
                page.close()
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
