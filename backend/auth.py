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
  ``HttpOnly`` and ``SameSite=Strict`` and holds a value derived from the
  token, not the token itself.

Unauthorised ``/api`` requests get 401 with a ``WWW-Authenticate`` header,
which the UI uses to tell "log in again" apart from relay errors. A browser
opening the UI root is redirected to the login page.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

TOKEN_ENV = "HLE_UI_TOKEN"
TOKEN_FILENAME = "ui_token"
COOKIE_NAME = "hle_ui_session"
COOKIE_MAX_AGE = 30 * 24 * 3600
AUTH_CHALLENGE = 'Bearer realm="hle-ui"'

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
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    os.chmod(token_file, 0o600)
    print(
        "[hle] Generated a login token for the web UI. It is shown only this "
        f"once and is stored in {token_file}:"
    )
    print(f"[hle]   {token}")
    return token


def session_value(token: str) -> str:
    """Cookie value for a logged-in browser, derived from the token."""
    return hmac.new(token.encode(), b"hle-ui-session", hashlib.sha256).hexdigest()


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def is_authorized(request: Request, token: str) -> bool:
    bearer = _bearer(request)
    if bearer and hmac.compare_digest(bearer.encode(), token.encode()):
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    return bool(cookie) and hmac.compare_digest(
        cookie.encode(), session_value(token).encode()
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

    @app.middleware("http")
    async def _require_ui_token(request: Request, call_next):
        path = request.url.path
        if path in _OPEN_PATHS or is_authorized(request, token):
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
        if not given or not hmac.compare_digest(given.encode(), token.encode()):
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
