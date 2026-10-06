"""Open a Playwright browser context for a booking account (session file or profile)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from shared.accounts import BookingAccount
from shared.config import RUN_HEADLESS


@contextmanager
def open_account_context(
    account: BookingAccount,
    *,
    headless: bool | None = None,
) -> Iterator[tuple[Playwright, Browser | None, BrowserContext]]:
    """
    Yield (playwright, browser_or_none, context).

    Prefers Playwright storageState JSON (no password). Falls back to a
    persistent Chromium profile directory.
    """
    use_headless = RUN_HEADLESS if headless is None else headless
    state_path = account.storage_state_path()

    with sync_playwright() as p:
        browser = None
        if state_path:
            browser = p.chromium.launch(headless=use_headless)
            context = browser.new_context(storage_state=state_path)
            try:
                yield p, browser, context
            finally:
                try:
                    # Refresh cookies after the run so sessions stay usable.
                    context.storage_state(path=state_path)
                except Exception:
                    pass
                context.close()
                browser.close()
            return

        profile_dir = account.profile_dir()
        os.makedirs(profile_dir, exist_ok=True)
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=use_headless,
            args=["--start-maximized"] if not use_headless else [],
        )
        try:
            yield p, None, context
        finally:
            # Also mirror profile cookies into storage_states/<id>.json when possible.
            try:
                from shared.paths import STORAGE_STATES_DIR, as_str

                os.makedirs(as_str(STORAGE_STATES_DIR), exist_ok=True)
                mirror = os.path.join(as_str(STORAGE_STATES_DIR), f"{account.id}.json")
                context.storage_state(path=mirror)
            except Exception:
                pass
            context.close()
