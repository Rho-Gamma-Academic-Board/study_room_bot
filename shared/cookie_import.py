"""Import Playwright storageState JSON as a session-only booking account.

No UCF passwords are stored — only LibCal cookies + booking metadata.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from shared.paths import ACCOUNTS_DIR, STORAGE_STATES_DIR, as_str, ensure_data_dirs

_NICK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


@dataclass
class ImportResult:
    nickname: str
    email: str
    nid: str
    public_name: str
    storage_state_path: str
    env_path: str


class CookieImportError(ValueError):
    """Invalid nickname or storageState payload."""


def validate_nickname(nickname: str) -> str:
    nick = (nickname or "").strip()
    if not _NICK_RE.match(nick):
        raise CookieImportError(
            "Nickname must start with a letter and use only letters, numbers, _ or -."
        )
    if nick.lower() == "example":
        raise CookieImportError("Pick a different nickname than 'example'.")
    return nick


def validate_storage_state(data: Any) -> dict:
    if not isinstance(data, dict) or "cookies" not in data:
        raise CookieImportError(
            "File does not look like a Playwright storageState (missing 'cookies' key)."
        )
    if not isinstance(data["cookies"], list):
        raise CookieImportError("storageState 'cookies' must be a list.")
    return data


def assert_authenticated_storage_state(data: dict) -> None:
    """
    Reject cookie jars grabbed before UCF SSO finishes.

    A usable LibCal session must include libauth.com cookies. Analytics-only
    (.libcal.com _ga, youtube, etc.) means the calendar was loaded without login.
    Mid-SSO jars that only have microsoftonline cookies are also rejected.
    """
    validate_storage_state(data)
    cookies = data.get("cookies") or []
    if not cookies:
        raise CookieImportError("No cookies in storageState — sign in first.")

    domains = [(c.get("domain") or "").lower() for c in cookies]
    names = [(c.get("name") or "") for c in cookies]

    has_libauth = any("libauth.com" in d for d in domains)
    has_ms = any(
        "microsoftonline.com" in d or "login.live.com" in d for d in domains
    )
    # Ignore junk-only jars (pre-auth calendar page).
    meaningful = [
        c
        for c in cookies
        if (c.get("name") or "") not in ("_ga", "_gid", "_gat")
        and "youtube.com" not in (c.get("domain") or "")
        and "google.com" not in (c.get("domain") or "")
    ]
    if len(meaningful) < 3:
        raise CookieImportError(
            "Cookies look pre-login (mostly analytics). "
            "Submit Times → finish MFA → wait for the booking form, then save."
        )
    if not has_libauth:
        if has_ms:
            raise CookieImportError(
                "Still mid Microsoft / Duo login — finish MFA until the LibCal "
                "booking form (name field) appears, then save."
            )
        raise CookieImportError(
            "Missing libauth.com session cookies. "
            "Submit Times → complete UCF MFA → booking form, then save."
        )


def parse_storage_state_bytes(raw: bytes | str) -> dict:
    try:
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = raw
        data = json.loads(text)
    except Exception as exc:
        raise CookieImportError(f"Invalid JSON: {exc}") from exc
    return validate_storage_state(data)


def import_storage_state(
    nickname: str,
    storage_state: dict | str | bytes,
    *,
    email: str = "",
    nid: str = "",
    public_name: str = "",
    require_authenticated: bool = True,
) -> ImportResult:
    """
    Persist storageState + account .env. Overwrites existing files for nickname.
    """
    nick = validate_nickname(nickname)
    if isinstance(storage_state, (str, bytes)):
        data = parse_storage_state_bytes(storage_state)
    else:
        data = validate_storage_state(storage_state)

    if require_authenticated:
        assert_authenticated_storage_state(data)

    ensure_data_dirs()
    dest = os.path.join(as_str(STORAGE_STATES_DIR), f"{nick}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(dest, 0o600)

    resolved_nid = (nid or nick).strip()
    resolved_email = (email or f"{resolved_nid}@ucf.edu").strip()
    resolved_name = (public_name or nick).strip()

    env_path = os.path.join(as_str(ACCOUNTS_DIR), f"{nick}.env")
    lines = [
        f"UCF_EMAIL={resolved_email}",
        f"UCF_NID={resolved_nid}",
        f"UCF_ID={resolved_nid}",
        f"PUBLIC_NAME={resolved_name}",
        f"STORAGE_STATE=data/storage_states/{nick}.json",
        "",
    ]
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(env_path, 0o600)

    return ImportResult(
        nickname=nick,
        email=resolved_email,
        nid=resolved_nid,
        public_name=resolved_name,
        storage_state_path=dest,
        env_path=env_path,
    )


def remove_account(nickname: str) -> bool:
    """Delete account env + storage state. Returns True if anything was removed."""
    nick = validate_nickname(nickname)
    removed = False
    for path in (
        os.path.join(as_str(ACCOUNTS_DIR), f"{nick}.env"),
        os.path.join(as_str(STORAGE_STATES_DIR), f"{nick}.json"),
    ):
        if os.path.exists(path):
            os.remove(path)
            removed = True
    return removed


def account_summaries() -> list[dict]:
    """Safe public summaries for the intake dashboard (no cookies/passwords)."""
    from shared.accounts import load_accounts, mask_email

    out = []
    for acct in load_accounts():
        out.append(
            {
                "id": acct.id,
                "public_name": acct.public_name,
                "email_masked": mask_email(acct.ucf_email),
                "has_cookies": acct.uses_storage_state(),
            }
        )
    return out
