"""Persist last job outcomes for the Study Rooms UI + email alerts."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from shared.paths import DATA_DIR, as_str, ensure_data_dirs

STATUS_FILE = as_str(DATA_DIR / "job_status.json")


def _load() -> dict[str, Any]:
    if not os.path.exists(STATUS_FILE):
        return {"jobs": {}}
    try:
        return json.loads(open(STATUS_FILE, encoding="utf-8").read())
    except Exception:
        return {"jobs": {}}


def _save(data: dict[str, Any]) -> None:
    ensure_data_dirs()
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(STATUS_FILE, 0o600)
    except OSError:
        pass


def record_job(
    job: str,
    *,
    ok: bool,
    detail: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Save outcome for job name (book | scrape | test-book)."""
    data = _load()
    jobs = data.setdefault("jobs", {})
    entry = {
        "job": job,
        "ok": ok,
        "detail": (detail or "")[:2000],
        "error": (error or "")[:2000],
        "at": time.time(),
        "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    jobs[job] = entry
    data["last"] = entry
    if not ok:
        data["last_failure"] = entry
    _save(data)
    return entry


def get_status() -> dict[str, Any]:
    data = _load()
    return {
        "ok": True,
        "jobs": data.get("jobs") or {},
        "last": data.get("last"),
        "last_failure": data.get("last_failure"),
    }


def clear_failure(job: str | None = None) -> None:
    data = _load()
    fail = data.get("last_failure")
    if not fail:
        return
    if job and fail.get("job") != job:
        return
    data.pop("last_failure", None)
    _save(data)
