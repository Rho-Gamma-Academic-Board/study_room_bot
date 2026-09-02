"""Load UCF booking accounts and rotate based on LibCal hour limits."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_DIR = os.path.join(_SCRIPT_DIR, "accounts")
USAGE_FILE = os.path.join(_SCRIPT_DIR, "account_usage.json")
PROFILES_DIR = os.path.join(_SCRIPT_DIR, "playwright-profiles")

# LibCal large study room limits (per patron)
MAX_HOURS_PER_DAY = 4
MAX_HOURS_PER_MONTH = 16


@dataclass
class BookingAccount:
    """One UCF identity that can make LibCal reservations."""

    id: str
    ucf_email: str
    ucf_password: str
    ucf_id: str
    public_name: str
    outlook_email: str = ""

    @property
    def outlook(self) -> str:
        return self.outlook_email or self.ucf_email

    def profile_dir(self) -> str:
        return os.path.join(PROFILES_DIR, self.id)


def _parse_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and value:
                values[key] = value
    return values


def _account_from_env(path: str) -> BookingAccount | None:
    data = _parse_env_file(path)
    email = data.get("UCF_EMAIL", "")
    password = data.get("UCF_PASSWORD", "")
    ucf_id = data.get("UCF_ID", "")
    if not email or not password or not ucf_id:
        return None
    account_id = os.path.splitext(os.path.basename(path))[0]
    if account_id.startswith("example"):
        return None
    return BookingAccount(
        id=account_id,
        ucf_email=email,
        ucf_password=password,
        ucf_id=ucf_id,
        public_name=data.get("PUBLIC_NAME", "Student"),
        outlook_email=data.get("OUTLOOK_EMAIL", ""),
    )


def load_accounts() -> list[BookingAccount]:
    """
    Load all accounts from accounts/*.env.
    Falls back to a single account from ucf_credentials.env if accounts/ is empty.
    """
    accounts: list[BookingAccount] = []
    if os.path.isdir(ACCOUNTS_DIR):
        for name in sorted(os.listdir(ACCOUNTS_DIR)):
            if not name.endswith(".env"):
                continue
            account = _account_from_env(os.path.join(ACCOUNTS_DIR, name))
            if account:
                accounts.append(account)

    if accounts:
        return accounts

    legacy = os.path.join(_SCRIPT_DIR, "ucf_credentials.env")
    if os.path.exists(legacy):
        account = _account_from_env(legacy)
        if account:
            account.id = "default"
            return [account]

    from shared.config import PUBLIC_NAME, UCF_EMAIL, UCF_ID, UCF_PASSWORD

    if UCF_EMAIL and UCF_PASSWORD and UCF_ID:
        return [
            BookingAccount(
                id="default",
                ucf_email=UCF_EMAIL,
                ucf_password=UCF_PASSWORD,
                ucf_id=UCF_ID,
                public_name=PUBLIC_NAME,
            )
        ]
    return []


def _load_usage() -> dict:
    if not os.path.exists(USAGE_FILE):
        return {}
    with open(USAGE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_usage(data: dict) -> None:
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _month_key(when: datetime | None = None) -> str:
    when = when or datetime.today()
    return when.strftime("%Y-%m")


def hours_on_date(usage: dict, account_id: str, date_str: str) -> float:
    entry = usage.get(account_id, {})
    return float(entry.get("daily", {}).get(date_str, 0))


def hours_this_month(usage: dict, account_id: str, when: datetime | None = None) -> float:
    entry = usage.get(account_id, {})
    month = _month_key(when)
    if entry.get("month") != month:
        return 0.0
    return float(entry.get("monthly_hours", 0))


def can_book(usage: dict, account: BookingAccount, date_str: str, hours: float) -> bool:
    if hours > MAX_HOURS_PER_DAY:
        return False
    if hours_on_date(usage, account.id, date_str) + hours > MAX_HOURS_PER_DAY:
        return False
    if hours_this_month(usage, account.id) + hours > MAX_HOURS_PER_MONTH:
        return False
    return True


def pick_account(
    accounts: list[BookingAccount],
    date_str: str,
    hours: float,
    forced_id: str | None = None,
    exclude_ids: set[str] | frozenset[str] | None = None,
) -> BookingAccount | None:
    """
    Choose the account with the most remaining monthly capacity that can book `hours`
    on `date_str`. Tie-break: fewest hours used today, then round-robin via last_used.
 
    Pass exclude_ids to rotate across accounts within a single run (e.g. 12–4, 4–8, 8–10).
    """
    if not accounts:
        return None

    usage = _load_usage()

    if forced_id:
        for account in accounts:
            if account.id == forced_id:
                if can_book(usage, account, date_str, hours):
                    return account
                print(f"Account '{forced_id}' cannot book {hours}h on {date_str} (limits).")
                return None

    eligible = [a for a in accounts if can_book(usage, a, date_str, hours)]
    if exclude_ids:
        eligible = [a for a in eligible if a.id not in exclude_ids]
    if not eligible:
        return None

    def sort_key(account: BookingAccount) -> tuple:
        monthly = hours_this_month(usage, account.id)
        daily = hours_on_date(usage, account.id, date_str)
        last_used = usage.get(account.id, {}).get("last_used", "")
        return (monthly, daily, last_used)

    return sorted(eligible, key=sort_key)[0]


def record_booking(account: BookingAccount, date_str: str, hours: float) -> None:
    """Track hours after a successful reservation."""
    usage = _load_usage()
    month = _month_key()
    entry = usage.setdefault(account.id, {"month": month, "monthly_hours": 0, "daily": {}})

    if entry.get("month") != month:
        entry["month"] = month
        entry["monthly_hours"] = 0
        entry["daily"] = {}

    entry["monthly_hours"] = float(entry.get("monthly_hours", 0)) + hours
    entry["daily"][date_str] = float(entry["daily"].get(date_str, 0)) + hours
    entry["last_used"] = datetime.now().isoformat()
    _save_usage(usage)


def booking_hours_from_window(start_hhmm: str, end_hhmm: str) -> float:
    start_h, start_m = map(int, start_hhmm.split(":"))
    end_h, end_m = map(int, end_hhmm.split(":"))
    return (end_h * 60 + end_m - start_h * 60 - start_m) / 60.0
