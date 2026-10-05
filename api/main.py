"""Intake API: password gate, account list, cookie upload, remote Playwright."""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from shared.config import BOOKING_EMAIL, LIBCAL_RESERVE_URL, STUDY_ROOMS_CALENDAR_ID, STUDY_ROOMS_CALENDAR_NAME
from shared.cookie_import import (
    CookieImportError,
    account_summaries,
    import_storage_state,
    remove_account,
    validate_nickname,
)
from shared.paths import ensure_data_dirs

INTAKE_PASSWORD = os.environ.get("INTAKE_PASSWORD", "").strip()
INTAKE_SECRET = os.environ.get("INTAKE_SECRET", "").strip() or secrets.token_hex(32)
SESSION_MAX_AGE = int(os.environ.get("INTAKE_SESSION_MAX_AGE", str(60 * 60 * 12)))
BROWSER_IDLE_SECONDS = int(os.environ.get("INTAKE_BROWSER_IDLE", "900"))

# Cookie flags: chapter site owns the UI and proxies /study-room-api → this API
# (same-origin cookies on the chapter host). Prefer Lax. Set INTAKE_HTTPS=1 when
# brothers hit the chapter site over HTTPS (Vercel); leave 0 for local http://localhost:3000.
_PUBLIC_URL = os.environ.get("INTAKE_PUBLIC_URL", "").strip()
_HTTPS_RAW = os.environ.get("INTAKE_HTTPS", "").strip().lower()
if _HTTPS_RAW in ("0", "false", "no"):
    INTAKE_HTTPS = False
elif _HTTPS_RAW in ("1", "true", "yes"):
    INTAKE_HTTPS = True
else:
    INTAKE_HTTPS = _PUBLIC_URL.startswith("https://")
INTAKE_COOKIE_SAMESITE = (
    os.environ.get("INTAKE_COOKIE_SAMESITE", "").strip().lower()
    or ("none" if INTAKE_HTTPS else "lax")
)
if INTAKE_COOKIE_SAMESITE not in ("lax", "strict", "none"):
    INTAKE_COOKIE_SAMESITE = "lax"
CHAPTER_SITE_URL = os.environ.get(
    "CHAPTER_SITE_URL",
    "https://academic-board.vercel.app/academic",
).strip()
# Local UI override (chapter site). Empty = derive from CHAPTER_SITE_URL.
LOCAL_UI_URL = os.environ.get("LOCAL_UI_URL", "").strip()


def chapter_study_rooms_url() -> str:
    if LOCAL_UI_URL:
        return LOCAL_UI_URL.rstrip("/")
    base = CHAPTER_SITE_URL.rstrip("/")
    if base.endswith("/academic"):
        return f"{base}/study-rooms"
    return f"{base}/academic/study-rooms"

_browser_lock = asyncio.Lock()
_sessions: dict[str, "BrowserSession"] = {}
_session_results: dict[str, dict] = {}


class BrowserSession:
    def __init__(self, session_id: str, meta: dict[str, str]):
        self.id = session_id
        self.meta = meta
        self.last_active = time.time()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._cdp = None
        self.viewers: set[WebSocket] = set()
        self.closed = False
        self.status = "starting"
        self.message = "Opening Chromium…"
        self._watch_task: asyncio.Task | None = None
        self.save_result: dict | None = None

    def touch(self) -> None:
        self.last_active = time.time()

    def snapshot(self) -> dict:
        return {
            "session_id": self.id,
            "status": self.status,
            "message": self.message,
            "result": self.save_result,
        }


def _password_ok(candidate: str) -> bool:
    if not INTAKE_PASSWORD:
        return False
    return hmac.compare_digest(
        candidate.encode("utf-8"), INTAKE_PASSWORD.encode("utf-8")
    )


def require_auth(request: Request) -> None:
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="Not authenticated")


class LoginBody(BaseModel):
    password: str


class SessionStartBody(BaseModel):
    nickname: str
    public_name: str = ""
    nid: str = ""
    email: str = ""


async def _close_browser_session(
    session: BrowserSession, *, from_watch: bool = False
) -> None:
    if session.closed:
        return
    session.closed = True
    if (
        not from_watch
        and session._watch_task
        and not session._watch_task.done()
        and session._watch_task is not asyncio.current_task()
    ):
        session._watch_task.cancel()
        try:
            await session._watch_task
        except (asyncio.CancelledError, Exception):
            pass
    if session._cdp:
        try:
            await session._cdp.send("Page.stopScreencast")
        except Exception:
            pass
    for ws in list(session.viewers):
        try:
            await ws.close()
        except Exception:
            pass
    session.viewers.clear()
    for closer in (session.context, session.browser):
        if closer:
            try:
                await closer.close()
            except Exception:
                pass
    # Drop playwright handles so we don't re-enter close from watch.
    session.context = None
    session.browser = None
    session.page = None
    if session.playwright:
        try:
            await session.playwright.stop()
        except Exception:
            pass
        session.playwright = None
    _sessions.pop(session.id, None)
    _session_results[session.id] = session.snapshot()
    if _browser_lock.locked():
        try:
            _browser_lock.release()
        except RuntimeError:
            pass


async def _page_on_auth_challenge(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    return any(
        x in url
        for x in (
            "login.microsoftonline.com",
            "login.live.com",
            "duosecurity.com",
            "/adfs/",
            "sts.windows.net",
            "sso.ucf.edu",
            "login.ucf.edu",
            "okta.com",
            "auth.ucf.edu",
            "shibboleth",
        )
    )


async def _page_libcal_authenticated(page) -> bool:
    """
    True only on the post-SSO booking details form.

    The room calendar is public before login — never treat the grid as signed-in.
    Auth runs after Submit Times; the bot fills input#nick only after SSO.
    """
    if await _page_on_auth_challenge(page):
        return False
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    if "libcal.com" not in url:
        return False

    # Strict: public-name field on the booking form (appears only after auth).
    try:
        nick = page.locator("input#nick").first
        if await nick.count() and await nick.is_visible(timeout=800):
            return True
    except Exception:
        pass

    try:
        btn = page.get_by_role("button", name="Submit My Booking")
        if await btn.count() and await btn.first.is_visible(timeout=800):
            return True
    except Exception:
        pass

    return False


async def _persist_session_cookies(session: BrowserSession) -> dict:
    assert session.context is not None
    # Re-check UI right before reading cookies.
    page = session.page
    if page is None or not await _page_libcal_authenticated(page):
        raise CookieImportError(
            "Booking form not visible — finish MFA until the name field appears."
        )
    state = await session.context.storage_state()
    meta = session.meta
    result = import_storage_state(
        meta["nickname"],
        state,
        email=meta.get("email", ""),
        nid=meta.get("nid", ""),
        public_name=meta.get("public_name", ""),
        require_authenticated=True,
    )
    return {
        "ok": True,
        "id": result.nickname,
        "email": result.email,
        "public_name": result.public_name,
    }


async def _watch_libcal_and_autosave(session: BrowserSession) -> None:
    """
    Save only after: Submit Times → SSO/MFA seen → booking form (#nick) stable.
    Calendar-only or mid-login cookies are rejected.
    """
    session.status = "waiting_login"
    session.message = (
        "1) Pick times → Submit Times  2) Finish UCF/Duo MFA  "
        "3) Wait for the booking form (name field). Then we save."
    )
    stable = 0
    saw_auth = False
    started = time.time()
    try:
        while not session.closed:
            session.touch()
            page = session.page
            if not page:
                break
            try:
                if await _page_on_auth_challenge(page):
                    saw_auth = True
                    session.message = (
                        "Microsoft / Duo login detected — finish MFA in Chromium…"
                    )
                    stable = 0
                    await asyncio.sleep(1.5)
                    continue
                ready = await _page_libcal_authenticated(page)
            except Exception:
                ready = False

            if not saw_auth:
                # Never save before we've seen the SSO challenge.
                session.message = (
                    "Waiting for Submit Times → UCF login. "
                    "(Seeing the calendar alone does not mean you’re signed in.)"
                )
                stable = 0
                await asyncio.sleep(1.5)
                continue

            if time.time() - started < 12:
                # Avoid any race right after launch.
                stable = 0
                await asyncio.sleep(1.5)
                continue

            if ready:
                stable += 1
                session.message = (
                    f"Booking form detected after MFA — confirming ({stable}/5)…"
                )
            else:
                stable = 0
                session.message = (
                    "MFA done? Waiting for the LibCal booking form (name field)…"
                )

            if stable >= 5:
                session.message = "Saving authenticated cookies…"
                try:
                    session.save_result = await _persist_session_cookies(session)
                except CookieImportError as exc:
                    stable = 0
                    session.message = f"Not saving yet: {exc}"
                    await asyncio.sleep(2)
                    continue
                session.status = "saved"
                session.message = (
                    "Cookies saved! Please set an Outlook Forward rule for LibCal alerts."
                )
                await _close_browser_session(session, from_watch=True)
                return
            await asyncio.sleep(1.5)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        session.status = "error"
        session.message = f"Sign-in watch failed: {exc}"
        _session_results[session.id] = session.snapshot()


async def _idle_watchdog() -> None:
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for sess in list(_sessions.values()):
            if now - sess.last_active > BROWSER_IDLE_SECONDS:
                await _close_browser_session(sess)


async def _broadcast_frame(session: BrowserSession, params: dict) -> None:
    payload = {
        "type": "frame",
        "data": params.get("data"),
        "metadata": params.get("metadata"),
    }
    dead: list[WebSocket] = []
    for ws in list(session.viewers):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.viewers.discard(ws)


async def _handle_screencast_frame(session: BrowserSession, params: dict) -> None:
    if session.closed or not session._cdp:
        return
    session.touch()
    try:
        await session._cdp.send(
            "Page.screencastFrameAck", {"sessionId": params["sessionId"]}
        )
    except Exception:
        pass
    await _broadcast_frame(session, params)


async def _start_screencast(session: BrowserSession) -> None:
    assert session.page is not None
    cdp = await session.page.context.new_cdp_session(session.page)
    session._cdp = cdp

    def handler(params: dict) -> None:
        asyncio.create_task(_handle_screencast_frame(session, params))

    cdp.on("Page.screencastFrame", handler)
    await cdp.send(
        "Page.startScreencast",
        {
            "format": "jpeg",
            "quality": 55,
            "maxWidth": 1280,
            "maxHeight": 800,
            "everyNthFrame": 1,
        },
    )


async def _create_browser_session(meta: dict[str, str]) -> BrowserSession:
    if _sessions:
        raise HTTPException(
            status_code=409,
            detail="Another member is signing in right now. Try again shortly.",
        )
    if _browser_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another member is signing in right now. Try again shortly.",
        )

    await _browser_lock.acquire()
    from playwright.async_api import async_playwright

    # Real OS window so Duo/MFA works (screencast/headless often stalls at MFA).
    headed = os.environ.get("INTAKE_HEADED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    session_id = uuid.uuid4().hex
    session = BrowserSession(session_id, meta)
    try:
        session.playwright = await async_playwright().start()
        session.browser = await session.playwright.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        session.context = await session.browser.new_context(
            viewport={"width": 1280, "height": 800} if not headed else None,
            no_viewport=headed,
            locale="en-US",
        )
        session.page = await session.context.new_page()
        await session.page.goto(LIBCAL_RESERVE_URL, wait_until="domcontentloaded")
        try:
            await session.page.bring_to_front()
        except Exception:
            pass
        if not headed:
            await _start_screencast(session)
        session.status = "waiting_login"
        session.message = (
            "Chromium opened — finish UCF sign-in / MFA. We’ll save cookies automatically."
        )
        _sessions[session_id] = session
        session._watch_task = asyncio.create_task(_watch_libcal_and_autosave(session))
        return session
    except Exception:
        await _close_browser_session(session)
        raise


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_data_dirs()
    watchdog = asyncio.create_task(_idle_watchdog())
    yield
    watchdog.cancel()
    for sess in list(_sessions.values()):
        await _close_browser_session(sess)


app = FastAPI(title="Study Room Intake", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=INTAKE_SECRET,
    session_cookie="sr_intake",
    max_age=SESSION_MAX_AGE,
    same_site=INTAKE_COOKIE_SAMESITE,
    https_only=INTAKE_HTTPS or INTAKE_COOKIE_SAMESITE == "none",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Drop stale service workers / caches from the old Vite intake SPA on :8790.
    if request.url.path in ("/", "/api/health"):
        response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return response


@app.get("/")
def root():
    """Send browsers to the chapter Study Rooms UI (saves cookies via this API)."""
    return RedirectResponse(url=chapter_study_rooms_url(), status_code=302)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "password_configured": bool(INTAKE_PASSWORD),
        "booking_email": BOOKING_EMAIL or "jo564454@ucf.edu",
        "calendar_id": STUDY_ROOMS_CALENDAR_ID,
        "calendar_name": STUDY_ROOMS_CALENDAR_NAME,
        "https": INTAKE_HTTPS,
        "cookie_samesite": INTAKE_COOKIE_SAMESITE,
        "public_url": _PUBLIC_URL or None,
        "chapter_site_url": CHAPTER_SITE_URL or None,
        "ui_url": chapter_study_rooms_url(),
        "api_only": True,
    }


@app.post("/api/login")
def login(body: LoginBody, request: Request) -> dict:
    if not INTAKE_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Set INTAKE_PASSWORD in config/intake.env before using the site.",
        )
    if not _password_ok(body.password):
        raise HTTPException(status_code=401, detail="Wrong password")
    request.session["authed"] = True
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request) -> dict:
    return {"authed": bool(request.session.get("authed"))}


@app.get("/api/accounts")
def list_accounts_route(request: Request, _: None = Depends(require_auth)) -> dict:
    accounts = account_summaries()
    return {
        "count": len(accounts),
        "accounts": accounts,
        "booking_email": BOOKING_EMAIL or "jo564454@ucf.edu",
        "forward_from": "alerts@mail.libcal.com",
        "calendar_id": STUDY_ROOMS_CALENDAR_ID,
        "calendar_name": STUDY_ROOMS_CALENDAR_NAME,
    }


@app.delete("/api/accounts/{nickname}")
def delete_account_route(
    nickname: str, request: Request, _: None = Depends(require_auth)
) -> dict:
    try:
        removed = remove_account(nickname)
    except CookieImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}


@app.post("/api/accounts/upload")
async def upload_account(
    request: Request,
    nickname: str = Form(...),
    public_name: str = Form(""),
    nid: str = Form(""),
    email: str = Form(""),
    file: UploadFile = File(...),
    _: None = Depends(require_auth),
) -> dict:
    raw = await file.read()
    try:
        result = import_storage_state(
            nickname,
            raw,
            email=email,
            nid=nid,
            public_name=public_name,
        )
    except CookieImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "id": result.nickname,
        "email": result.email,
        "public_name": result.public_name,
    }


@app.post("/api/sessions")
async def start_session(
    body: SessionStartBody,
    request: Request,
    _: None = Depends(require_auth),
) -> dict:
    try:
        nick = validate_nickname(body.nickname)
    except CookieImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = {
        "nickname": nick,
        "public_name": (body.public_name or nick).strip(),
        "nid": (body.nid or nick).strip(),
        "email": (body.email or "").strip(),
    }
    session = await _create_browser_session(meta)
    headed = os.environ.get("INTAKE_HEADED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    return {
        "session_id": session.id,
        "url": LIBCAL_RESERVE_URL,
        "headed": headed,
        "hint": (
            "Chromium opened. Pick times → Submit Times → finish MFA. "
            "We save cookies when the booking form appears (calendar alone is not logged-in)."
            if headed
            else "Complete Submit Times + MFA; cookies save on the booking form."
        ),
    }


@app.get("/api/sessions/{session_id}/status")
def session_status(
    session_id: str, request: Request, _: None = Depends(require_auth)
) -> dict:
    live = _sessions.get(session_id)
    if live:
        return live.snapshot()
    done = _session_results.get(session_id)
    if done:
        return done
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/{session_id}/save")
async def save_session(
    session_id: str,
    request: Request,
    _: None = Depends(require_auth),
) -> dict:
    session = _sessions.get(session_id)
    if not session or not session.context:
        done = _session_results.get(session_id)
        if done and done.get("status") == "saved" and done.get("result"):
            return done["result"]
        raise HTTPException(status_code=404, detail="Session not found")
    session.touch()
    try:
        result = await _persist_session_cookies(session)
    except CookieImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.save_result = result
    session.status = "saved"
    session.message = (
        "Cookies saved! Please go to your email and forward LibCal alerts."
    )
    await _close_browser_session(session)
    return result


@app.delete("/api/sessions/{session_id}")
async def cancel_session(
    session_id: str,
    request: Request,
    _: None = Depends(require_auth),
) -> dict:
    session = _sessions.get(session_id)
    if session:
        session.status = "cancelled"
        session.message = "Cancelled"
        await _close_browser_session(session)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Verify / onboarding pipeline
# ---------------------------------------------------------------------------


@app.post("/api/verify/{nickname}/test-book")
async def verify_test_book(
    nickname: str,
    request: Request,
    phase: str = "first",
    _: None = Depends(require_auth),
) -> dict:
    if phase not in ("first", "second"):
        raise HTTPException(status_code=400, detail="phase must be first or second")
    if _sessions:
        raise HTTPException(
            status_code=409,
            detail="Close the remote sign-in browser before running a test booking.",
        )
    try:
        from api.verify_flow import run_test_book

        return await asyncio.to_thread(run_test_book, nickname, phase=phase)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/verify/{nickname}/cancel-libcal")
async def verify_cancel_libcal(
    nickname: str,
    request: Request,
    phase: str | None = None,
    _: None = Depends(require_auth),
) -> dict:
    try:
        from api.verify_flow import cancel_libcal_booking

        return await asyncio.to_thread(cancel_libcal_booking, nickname, phase)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/verify/scrape")
async def verify_scrape(
    request: Request,
    nickname: str | None = None,
    _: None = Depends(require_auth),
) -> dict:
    try:
        from api.verify_flow import run_scrape

        result = await asyncio.to_thread(run_scrape, nickname)
        if not result.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=result.get("detail") or "Outlook scrape failed",
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs")
async def jobs_status(request: Request, _: None = Depends(require_auth)) -> dict:
    from shared.job_status import get_status

    return get_status()


class JobRerunBody(BaseModel):
    job: str  # book | scrape


@app.post("/api/jobs/rerun")
async def jobs_rerun(
    body: JobRerunBody,
    request: Request,
    _: None = Depends(require_auth),
) -> dict:
    job = (body.job or "").strip().lower()
    if job not in ("book", "scrape"):
        raise HTTPException(status_code=400, detail="job must be 'book' or 'scrape'")
    if _sessions:
        raise HTTPException(
            status_code=409,
            detail="Close the remote sign-in browser before rerunning a job.",
        )

    def _run() -> dict:
        if job == "scrape":
            from api.verify_flow import run_scrape

            return run_scrape(None)
        # Full weekday booking pass (same as ./run-bot.sh --now)
        import study_room_bot as bot
        from shared.alerts import report_job

        try:
            os.environ["RUN_HEADLESS"] = "1"
            bot.book_room()
            report_job("book", ok=True, detail="manual rerun finished")
            return {"ok": True, "job": "book", "detail": "Booking run finished."}
        except Exception as exc:
            report_job("book", ok=False, error=str(exc))
            raise

    try:
        result = await asyncio.to_thread(_run)
        from shared.job_status import get_status

        status = get_status()
        return {"ok": True, "job": job, "result": result, "status": status}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/verify/{nickname}/calendar")
async def verify_calendar(
    nickname: str,
    request: Request,
    phase: str = "second",
    _: None = Depends(require_auth),
) -> dict:
    try:
        from api.verify_flow import calendar_status

        return await asyncio.to_thread(calendar_status, nickname, phase)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/verify/{nickname}/cleanup-calendar")
async def verify_cleanup_calendar(
    nickname: str,
    request: Request,
    _: None = Depends(require_auth),
) -> dict:
    try:
        from api.verify_flow import cleanup_calendar

        return await asyncio.to_thread(cleanup_calendar, nickname)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/verify/{nickname}/state")
def verify_state(
    nickname: str, request: Request, _: None = Depends(require_auth)
) -> dict:
    from api.verify_flow import load_state

    return load_state(nickname)


@app.websocket("/api/sessions/{session_id}/ws")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    session_data = websocket.scope.get("session") or {}
    if not session_data.get("authed"):
        await websocket.send_json({"type": "error", "detail": "Not authenticated"})
        await websocket.close(code=4401)
        return

    session = _sessions.get(session_id)
    if not session or not session.page:
        await websocket.send_json({"type": "error", "detail": "Session not found"})
        await websocket.close(code=4404)
        return

    session.viewers.add(websocket)
    session.touch()
    try:
        await websocket.send_json({"type": "ready", "session_id": session_id})
        while True:
            msg = await websocket.receive_json()
            session.touch()
            await _handle_input(session, msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        session.viewers.discard(websocket)


async def _handle_input(session: BrowserSession, msg: dict[str, Any]) -> None:
    page = session.page
    if not page or session.closed:
        return
    kind = msg.get("type")
    try:
        if kind == "click":
            await page.mouse.click(float(msg["x"]), float(msg["y"]))
        elif kind == "dblclick":
            await page.mouse.dblclick(float(msg["x"]), float(msg["y"]))
        elif kind == "move":
            await page.mouse.move(float(msg["x"]), float(msg["y"]))
        elif kind == "wheel":
            await page.mouse.wheel(float(msg.get("dx", 0)), float(msg.get("dy", 0)))
        elif kind == "type":
            text = msg.get("text") or ""
            if text:
                await page.keyboard.type(text, delay=15)
        elif kind == "press":
            key = msg.get("key") or ""
            if key:
                await page.keyboard.press(key)
    except Exception:
        pass
