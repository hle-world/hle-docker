"""Login token gate for the management API.

The management API can create tunnels, change the account API key and strip
protection from published services, so it must never be reachable without
credentials -- not from the LAN, not from another container, and not from a
web page that rebinds its DNS name to this host.

On first start a random token is generated and stored in the data directory
(mode 0600). It is printed once to the logs; after that only its location is
logged. ``HLE_UI_TOKEN`` overrides the stored token.

A request is authorised when it carries either:

* ``Authorization: Bearer <token>`` (scripts, headless installs), or
* the session cookie set by the ``/login`` form (browser UI). The cookie is
  ``HttpOnly`` and ``SameSite=Strict`` and holds an issue time signed with
  the token (HMAC), not the token itself. Sessions expire after
  ``COOKIE_MAX_AGE`` server-side, and rotating the token (delete the token
  file and restart, or change ``HLE_UI_TOKEN``) invalidates all of them.

Token attempts (login form and bearer header -- the only two places a token
is accepted; there is deliberately no query-string login, since a token in a
URL ends up in history, Referer headers and access logs) share one limiter:

* Per peer address (``request.client.host``; run.sh disables proxy headers):
  ``MAX_FAILURES`` failures in ``FAILURE_WINDOW`` -> 429 for that address only.
  The attempt is reserved before the token is compared, in one synchronous
  step, so concurrent requests cannot all slip under the limit; a success
  releases its reservation.
* Globally: never a block, only a slowdown. When many failures arrive from
  all addresses together, each attempt waits ``SLOWDOWN_SECONDS`` before the
  compare, so the owner can still log in during a distributed flood.
* A request with a valid session cookie is exempt from the limiter.

Unauthorised ``/api`` requests get 401 with a ``WWW-Authenticate`` header,
which the UI uses to tell "log in again" apart from relay errors. A browser
opening the UI root is redirected to the login page.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import os
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

TOKEN_ENV = "HLE_UI_TOKEN"
TOKEN_FILENAME = "ui_token"
COOKIE_NAME = "hle_ui_session"
COOKIE_MAX_AGE = 30 * 24 * 3600
AUTH_CHALLENGE = 'Bearer realm="hle-ui"'
# Failed attempts allowed per peer address within the window before 429.
MAX_FAILURES = 10
FAILURE_WINDOW = 900.0
# Failures from all addresses together within the window that switch on the
# slowdown (never a lockout).
GLOBAL_SLOWDOWN_AFTER = 50
SLOWDOWN_SECONDS = 1.5
# Addresses tracked individually (memory bound).
MAX_TRACKED_ADDRESSES = 4096

# Paths reachable without a token. They render or process the login form and
# return nothing about this install.
_OPEN_PATHS = frozenset({"/login", "/logout"})
# Browser entry points that redirect to the login page instead of a bare 401.
_UI_ENTRY_PATHS = frozenset({"/", "/index.html"})


def load_or_create_token(token_file: Path) -> str:
    """Return the UI token, generating and persisting it on first use."""
    env_token = os.environ.get(TOKEN_ENV, "").strip()
    if env_token:
        print(f"[hle] Web UI login token taken from {TOKEN_ENV}.")
        return env_token

    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                pass
            print(f"[hle] Web UI login token is stored in {token_file}")
            return token

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # An empty leftover file is replaced; O_EXCL then guarantees the file is
    # created fresh with 0600 and never exists with looser permissions.
    token_file.unlink(missing_ok=True)
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    print(
        "[hle] Generated a login token for the web UI. It is shown only this "
        f"once and is stored in {token_file}:"
    )
    print(f"[hle]   {token}")
    return token


def _sign(token: str, issued: str) -> str:
    msg = f"hle-ui-session:{issued}".encode()
    return hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()


def session_value(token: str, now: float | None = None) -> str:
    """Cookie value for a logged-in browser: issue time + HMAC(token)."""
    issued = str(int(time.time() if now is None else now))
    return f"{issued}.{_sign(token, issued)}"


def session_valid(token: str, value: str, now: float | None = None) -> bool:
    issued, _, sig = value.partition(".")
    if not issued.isdigit() or not sig:
        return False
    if not hmac.compare_digest(sig.encode(), _sign(token, issued).encode()):
        return False
    age = (time.time() if now is None else now) - int(issued)
    return 0 <= age <= COOKIE_MAX_AGE


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def _token_matches(given: str, token: str) -> bool:
    return hmac.compare_digest(given.encode(), token.encode())


def has_valid_session(request: Request, token: str) -> bool:
    cookie = request.cookies.get(COOKIE_NAME, "")
    return bool(cookie) and session_valid(token, cookie)


class FailureLimiter:
    """Token-attempt limiter: per-address lockout, global slowdown.

    ``reserve`` is synchronous and must be called before the token compare,
    with no ``await`` between the check and the increment: the attempt is
    counted first and ``release`` gives it back on success. Concurrent
    requests from one address therefore cannot all pass the check before any
    failure is recorded.

    Memory is bounded: each per-address deque holds at most ``max_failures``
    timestamps and at most ``max_keys`` addresses are tracked. When the map
    is full, expired entries are pruned; if it is still full, a new address
    is not tracked on its own (it still counts towards, and is slowed by, the
    global figure). Existing entries are never evicted early, so flooding new
    addresses cannot reset an address that is locked out.
    """

    def __init__(
        self,
        max_failures: int = MAX_FAILURES,
        window: float = FAILURE_WINDOW,
        slowdown_after: int = GLOBAL_SLOWDOWN_AFTER,
        max_keys: int = MAX_TRACKED_ADDRESSES,
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self.slowdown_after = slowdown_after
        self.max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}
        # Only needs enough entries to know the threshold has been reached.
        self._global: deque[float] = deque(maxlen=max(slowdown_after, 1) * 2)

    def _expire(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def reserve(self, key: str) -> bool:
        """Count one attempt for ``key``; False (do not compare) if locked out."""
        now = time.monotonic()
        q = self._attempts.get(key)
        if q is not None:
            self._expire(q, now)
            if len(q) >= self.max_failures:
                return False
        elif len(self._attempts) >= self.max_keys:
            for stale in list(self._attempts):
                self._expire(self._attempts[stale], now)
                if not self._attempts[stale]:
                    del self._attempts[stale]
        if q is None and len(self._attempts) < self.max_keys:
            q = self._attempts[key] = deque(maxlen=self.max_failures)
        if q is not None:
            q.append(now)
        self._global.append(now)
        return True

    def release(self, key: str) -> None:
        """Give back the reservation of a successful attempt."""
        q = self._attempts.get(key)
        if q:
            q.pop()
            if not q:
                del self._attempts[key]
        if self._global:
            self._global.pop()

    def slow(self) -> bool:
        self._expire(self._global, time.monotonic())
        return len(self._global) >= self.slowdown_after

    def tracked(self) -> int:
        return len(self._attempts)


def _client_key(request: Request) -> str:
    # The socket peer only. run.sh starts uvicorn with --no-proxy-headers, so
    # X-Forwarded-For cannot change this.
    return request.client.host if request.client else "unknown"


async def _checked_attempt(limiter: FailureLimiter, key: str, ok) -> bool | None:
    """Reserve, optionally slow down, then compare. None means locked out."""
    if not limiter.reserve(key):  # synchronous check-and-reserve
        return None
    if limiter.slow():
        await asyncio.sleep(SLOWDOWN_SECONDS)
    if ok():
        limiter.release(key)
        return True
    return False


def _too_many() -> JSONResponse:
    return JSONResponse(
        {"detail": "Too many failed login attempts. Try again later."},
        status_code=429,
        headers={"Retry-After": str(int(FAILURE_WINDOW)), "Cache-Control": "no-store"},
    )


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip().lower() == "https"


_LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HLE login</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
form{{background:#181b22;padding:24px;border-radius:10px;width:min(360px,90vw)}}
h1{{font-size:18px;margin:0 0 12px}}p{{font-size:13px;color:#a0a4ad;line-height:1.5}}
input{{width:100%;box-sizing:border-box;padding:8px;margin:8px 0;border-radius:6px;
border:1px solid #333;background:#0f1115;color:inherit;font-family:monospace}}
button{{width:100%;padding:8px;border:0;border-radius:6px;background:#3b82f6;color:#fff}}
.err{{color:#f87171}}
</style></head><body>
<form method="post" action="login">
<h1>HLE login</h1>
<p>Enter the login token. It was printed in the logs on first start and is
stored in <code>{token_file}</code>.</p>
{error}
<input type="password" name="token" autocomplete="current-password" autofocus required>
<button type="submit">Log in</button>
</form></body></html>
"""


def install(app: FastAPI, token_file: Path) -> str:
    """Protect every route of ``app`` with the UI token. Returns the token."""
    token = load_or_create_token(token_file)
    shown_path = html.escape(str(token_file))

    def _page(error: str = "", status_code: int = 200) -> HTMLResponse:
        err = f'<p class="err">{html.escape(error)}</p>' if error else ""
        return HTMLResponse(
            _LOGIN_PAGE.format(token_file=shown_path, error=err),
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    limiter = FailureLimiter()
    app.state.ui_auth_limiter = limiter

    @app.middleware("http")
    async def _require_ui_token(request: Request, call_next):
        path = request.url.path
        if path in _OPEN_PATHS:
            return await call_next(request)
        # A valid session is exempt from the limiter, so a flood of guesses
        # never locks out a browser that is already logged in. (Forging the
        # HMAC-signed cookie is not a practical guessing target.)
        if has_valid_session(request, token):
            return await call_next(request)
        bearer = _bearer(request)
        if bearer:
            result = await _checked_attempt(
                limiter, _client_key(request), lambda: _token_matches(bearer, token)
            )
            if result is None:
                return _too_many()
            if result:
                return await call_next(request)
        if request.method in ("GET", "HEAD") and path in _UI_ENTRY_PATHS:
            return RedirectResponse("login", status_code=303)
        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": AUTH_CHALLENGE},
        )

    @app.get("/login", include_in_schema=False)
    async def login_page() -> Response:
        return _page()

    @app.post("/login", include_in_schema=False)
    async def login(request: Request) -> Response:
        form = parse_qs((await request.body()).decode(errors="replace"))
        given = (form.get("token") or [""])[0].strip()
        result = await _checked_attempt(
            limiter,
            _client_key(request),
            lambda: bool(given) and _token_matches(given, token),
        )
        if result is None:
            return _page(
                "Too many failed attempts. Try again later.",
                status_code=429,
            )
        if not result:
            return _page("Invalid token.", status_code=401)
        resp = RedirectResponse("./", status_code=303)
        resp.set_cookie(
            COOKIE_NAME,
            session_value(token),
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="strict",
            secure=_is_https(request),
            path="/",
        )
        return resp

    @app.post("/logout", include_in_schema=False)
    async def logout() -> Response:
        resp = RedirectResponse("login", status_code=303)
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp

    return token
