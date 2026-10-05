"""Email alerts when a study-room bot job fails."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from shared.config import (
    ALERT_ENABLED,
    ALERT_FROM,
    ALERT_SMTP_HOST,
    ALERT_SMTP_PASSWORD,
    ALERT_SMTP_PORT,
    ALERT_SMTP_USER,
    ALERT_TO,
    CHAPTER_SITE_URL,
)
from shared.job_status import record_job

JOB_LABELS = {
    "book": "Study room booking",
    "scrape": "Outlook → Calendar scrape",
    "test-book": "Onboarding test booking",
}


def _rerun_url() -> str:
    base = (CHAPTER_SITE_URL or "https://academic-board.vercel.app/academic").rstrip("/")
    if base.endswith("/academic"):
        return f"{base}/study-rooms"
    return f"{base}/academic/study-rooms"


def send_failure_email(job: str, error: str, detail: str = "") -> bool:
    """
    Send failure email to ALERT_TO via SMTP (Gmail app password recommended).
    Returns True if sent.
    """
    if not ALERT_ENABLED:
        print("Alert email skipped (ALERT_ENABLED=0).")
        return False
    to_addr = (ALERT_TO or "").strip()
    if not to_addr:
        print("Alert email skipped (ALERT_TO empty).")
        return False
    user = (ALERT_SMTP_USER or "").strip()
    password = (ALERT_SMTP_PASSWORD or "").strip()
    if not user or not password:
        print(
            "Alert email skipped — set ALERT_SMTP_USER and ALERT_SMTP_PASSWORD "
            "(Gmail app password) in config/ucf_credentials.env."
        )
        return False

    label = JOB_LABELS.get(job, job)
    from_addr = (ALERT_FROM or user).strip()
    rerun = _rerun_url()
    body = (
        f"Job: {label} ({job})\n"
        f"Error: {error or 'unknown'}\n"
        f"{('Detail: ' + detail + chr(10)) if detail else ''}"
        f"\nRerun from Study Rooms (Mac must be awake + intake running):\n"
        f"{rerun}\n"
        f"\nOr on the Mac:\n"
        f"  scrape → ./scrape-outlook.sh --once\n"
        f"  book   → ./run-bot.sh --now\n"
    )

    msg = EmailMessage()
    msg["Subject"] = f"[Study Rooms] {label} failed"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(ALERT_SMTP_HOST, ALERT_SMTP_PORT, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
        print(f"Alert email sent to {to_addr} for job={job}")
        return True
    except Exception as exc:
        print(f"Alert email failed: {exc}")
        return False


def report_job(
    job: str,
    *,
    ok: bool,
    detail: str = "",
    error: str = "",
    email_on_failure: bool = True,
) -> dict:
    """Record job status and email on failure."""
    entry = record_job(job, ok=ok, detail=detail, error=error)
    if not ok and email_on_failure:
        send_failure_email(job, error=error or detail or "failed", detail=detail)
    return entry
