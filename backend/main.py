"""FastAPI management API for HLE Docker."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles  # noqa: F401 — used in conditional mount below

from backend import auth, hle_api
from backend.models import (
    AddAccessRuleRequest,
    AddTunnelRequest,
    CreateShareLinkRequest,
    SetBasicAuthRequest,
    SetPinRequest,
    TunnelStatus,
    UpdateConfigRequest,
    UpdateTunnelRequest,
)
from backend import tunnel_manager as tm
from backend.tunnel_manager import DuplicateLabelError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Restore API key from persisted config if not already set in environment
    if not os.environ.get("HLE_API_KEY") and HLE_CONFIG.exists():
        try:
            api_key = json.loads(HLE_CONFIG.read_text()).get("api_key", "")
            if api_key:
                os.environ["HLE_API_KEY"] = api_key
        except Exception:
            pass
    await tm.restore_all()
    yield
    await tm.shutdown_all()


app = FastAPI(title="HLE Docker API", docs_url=None, redoc_url=None, lifespan=lifespan)

HLE_CONFIG = Path("/data/hle_config.json")
STATIC_DIR = Path("/app/backend/static")

# The published port is reachable from the LAN (or the internet on a VPS), so
# every route (API and UI) requires the login token. See backend/auth.py.
auth.install(app, Path(os.environ.get("HLE_DATA_DIR", "/data")) / auth.TOKEN_FILENAME)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_api_key() -> None:
    if not os.environ.get("HLE_API_KEY"):
        raise HTTPException(
            status_code=400, detail="API key not configured. Set it in Settings first."
        )


def _managed_subdomain(subdomain: str) -> str:
    """Only proxy relay calls for tunnels this container manages.

    The relay calls below use the account's global key, which can reach every
    tunnel on the account; this keeps them scoped to the local tunnels.
    """
    if not any(t.subdomain == subdomain for t in tm.list_tunnels()):
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return subdomain


ManagedSubdomain = Annotated[str, Depends(_managed_subdomain)]


# ---------------------------------------------------------------------------
# Tunnel management
# ---------------------------------------------------------------------------


@app.get("/api/tunnels", response_model=list[TunnelStatus])
async def list_tunnels():
    return tm.list_tunnels()


@app.post("/api/tunnels", response_model=TunnelStatus, status_code=201)
async def add_tunnel(req: AddTunnelRequest):
    _require_api_key()
    try:
        cfg = await tm.add_tunnel(req)
    except DuplicateLabelError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return tm.get_tunnel(cfg.id)


@app.patch("/api/tunnels/{tunnel_id}", response_model=TunnelStatus)
async def update_tunnel(tunnel_id: str, req: UpdateTunnelRequest):
    if tm.get_tunnel(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    try:
        cfg = await tm.update_tunnel(tunnel_id, req)
    except DuplicateLabelError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return tm.get_tunnel(cfg.id)


@app.delete("/api/tunnels/{tunnel_id}", status_code=204)
async def remove_tunnel(tunnel_id: str):
    if tm.get_tunnel(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    await tm.remove_tunnel(tunnel_id)


@app.post("/api/tunnels/{tunnel_id}/start", status_code=204)
async def start_tunnel(tunnel_id: str):
    if tm.get_tunnel(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    await tm.start_tunnel(tunnel_id)


@app.post("/api/tunnels/{tunnel_id}/stop", status_code=204)
async def stop_tunnel(tunnel_id: str):
    if tm.get_tunnel(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    await tm.stop_tunnel(tunnel_id)


# ---------------------------------------------------------------------------
# Tunnel logs
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{tunnel_id}/logs")
async def get_tunnel_logs(tunnel_id: str, lines: int = 100):
    log_path = Path(f"/data/logs/tunnel-{tunnel_id}.log")
    if not log_path.exists():
        return {"lines": []}
    text = log_path.read_text(errors="replace")
    all_lines = text.splitlines()
    return {"lines": all_lines[-lines:]}


@app.get("/api/tunnels/{tunnel_id}/logs/download")
async def download_tunnel_logs(tunnel_id: str, lines: int = 2000):
    """Download the last N log lines as a plain text file."""
    log_path = Path(f"/data/logs/tunnel-{tunnel_id}.log")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No log file found")
    text = log_path.read_text(errors="replace")
    all_lines = text.splitlines()
    content = "\n".join(all_lines[-lines:])
    return Response(
        content=content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="tunnel-{tunnel_id}.log"'
        },
    )


# ---------------------------------------------------------------------------
# Favicon proxy (fetches from the tunnel's local service URL)
# ---------------------------------------------------------------------------

FAVICON_DIR = Path("/data/favicons")

# Favicon bytes are rendered on the management origin, so they must be inert:
# raster formats only (never SVG, which can carry script), confirmed by magic
# bytes, and never larger than this.
MAX_FAVICON_BYTES = 256 * 1024

_FAVICON_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_image(data: bytes) -> str | None:
    """Return the media type for a supported raster image, or ``None``.

    The upstream ``Content-Type`` is deliberately ignored — the upstream is
    attacker controlled — and the format is decided purely by magic bytes.
    This is what keeps SVG (and any other script-bearing content) from ever
    being served from the management origin.
    """
    for magic, media_type in _FAVICON_MAGIC:
        if data.startswith(magic):
            return media_type
    return None


def _url_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _favicon_response(data: bytes, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _read_capped(resp, limit: int) -> bytes | None:
    """Read at most ``limit`` bytes of a streamed body; ``None`` if it is larger.

    The upstream is attacker controlled, so the cap is enforced while reading
    rather than after the whole body has been buffered.
    """
    declared = resp.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


async def _fetch_same_origin(
    client, url: str, origin: str, limit: int, max_redirects: int = 5
) -> tuple[httpx.URL, bytes] | None:
    """GET ``url`` and return ``(final_url, body)`` for a 200 response.

    Only redirects that stay on ``origin`` are followed: following the
    upstream's redirect to another host would be SSRF. A cross-origin
    ``Location``, too many hops, a non-200 status or a body over ``limit``
    bytes all return ``None``, which the caller treats as "no favicon".
    """
    for _ in range(max_redirects + 1):
        async with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.is_redirect and resp.headers.get("location"):
                url = str(resp.url.join(resp.headers["location"]))
                if _url_origin(url) != origin:
                    return None
                continue
            if resp.status_code != 200:
                return None
            body = await _read_capped(resp, limit)
            return None if body is None else (resp.url, body)
    return None


@app.get("/api/tunnels/{tunnel_id}/favicon")
async def get_tunnel_favicon(tunnel_id: str):
    """Return the favicon from the tunnel's local service, cached on disk.

    Only PNG/ICO/JPEG/GIF are served, confirmed by magic bytes — never SVG —
    because these bytes render on the management origin. Responses are capped
    in size and sent with ``nosniff`` and a sandboxing CSP, and only
    same-origin URLs are ever fetched.
    """
    # Serve from cache if available
    cached = FAVICON_DIR / tunnel_id
    if cached.exists():
        data = cached.read_bytes()
        media_type = _sniff_image(data)
        if media_type is not None and 0 < len(data) <= MAX_FAVICON_BYTES:
            return _favicon_response(data, media_type)

    # Look up tunnel config to get service_url
    status = tm.get_tunnel(tunnel_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    service_url = status.service_url.rstrip("/")
    origin = _url_origin(service_url)

    # Common favicon paths — services like Jellyfin use /web/favicon.ico
    favicon_paths = [
        "/favicon.ico",
        "/web/favicon.ico",
        "/favicon.png",
        "/favicon.svg",
    ]

    icon_data: bytes | None = None
    icon_media = "image/x-icon"

    async with httpx.AsyncClient(timeout=5, verify=False) as client:  # nosec B501 — local LAN services often use self-signed certs
        for path in favicon_paths:
            try:
                fetched = await _fetch_same_origin(
                    client, f"{service_url}{path}", origin, MAX_FAVICON_BYTES
                )
            except Exception:
                continue
            if fetched is None:
                continue
            data = fetched[1]
            media_type = _sniff_image(data)
            if media_type is not None and len(data) > 0:
                icon_data = data
                icon_media = media_type
                break

        # Fallback: parse <link rel="icon"> from HTML
        if icon_data is None:
            try:
                # Pages are often larger than the head we scan, so this fetch
                # gets a generous cap and only the first 8 KiB is searched.
                page = await _fetch_same_origin(
                    client, service_url, origin, 2 * 1024 * 1024
                )
                if page is not None:
                    page_url, page_body = page
                    html = page_body[:8192].decode(
                        "utf-8", "replace"
                    )  # only scan the head
                    match = re.search(
                        r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]+href=["\']([^"\']+)',
                        html,
                        re.IGNORECASE,
                    )
                    if match:
                        # Resolve relative to the (same-origin) final URL and
                        # refuse anything that escapes the service's origin.
                        href = str(page_url.join(match.group(1)))
                        if _url_origin(href) == origin:
                            icon = await _fetch_same_origin(
                                client, href, origin, MAX_FAVICON_BYTES
                            )
                            if icon is not None:
                                data = icon[1]
                                media_type = _sniff_image(data)
                                if media_type is not None and len(data) > 0:
                                    icon_data = data
                                    icon_media = media_type
            except Exception:
                pass

    if icon_data is None:
        raise HTTPException(status_code=404, detail="No favicon found")

    # Cache to disk
    FAVICON_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(icon_data)

    return _favicon_response(icon_data, icon_media)


# ---------------------------------------------------------------------------
# Access rules (keyed by subdomain, proxied to relay)
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{subdomain}/access")
async def list_access_rules(subdomain: ManagedSubdomain):
    try:
        return await hle_api.list_access_rules(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.post("/api/tunnels/{subdomain}/access", status_code=201)
async def add_access_rule(subdomain: ManagedSubdomain, req: AddAccessRuleRequest):
    try:
        return await hle_api.add_access_rule(subdomain, req.email, req.provider)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/access/{rule_id}", status_code=204)
async def delete_access_rule(subdomain: ManagedSubdomain, rule_id: int):
    try:
        await hle_api.delete_access_rule(subdomain, rule_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


# ---------------------------------------------------------------------------
# PIN protection (keyed by subdomain)
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{subdomain}/pin")
async def get_pin_status(subdomain: ManagedSubdomain):
    try:
        return await hle_api.get_pin_status(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.put("/api/tunnels/{subdomain}/pin", status_code=204)
async def set_pin(subdomain: ManagedSubdomain, req: SetPinRequest):
    try:
        await hle_api.set_pin(subdomain, req.pin)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/pin", status_code=204)
async def remove_pin(subdomain: ManagedSubdomain):
    try:
        await hle_api.remove_pin(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


# ---------------------------------------------------------------------------
# Basic auth (keyed by subdomain)
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{subdomain}/basic-auth")
async def get_basic_auth_status(subdomain: ManagedSubdomain):
    try:
        return await hle_api.get_basic_auth_status(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.put("/api/tunnels/{subdomain}/basic-auth", status_code=204)
async def set_basic_auth(subdomain: ManagedSubdomain, req: SetBasicAuthRequest):
    try:
        await hle_api.set_basic_auth(subdomain, req.username, req.password)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/basic-auth", status_code=204)
async def remove_basic_auth(subdomain: ManagedSubdomain):
    try:
        await hle_api.remove_basic_auth(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


# ---------------------------------------------------------------------------
# Share links (keyed by subdomain)
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{subdomain}/share")
async def list_share_links(subdomain: ManagedSubdomain):
    try:
        return await hle_api.list_share_links(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.post("/api/tunnels/{subdomain}/share", status_code=201)
async def create_share_link(subdomain: ManagedSubdomain, req: CreateShareLinkRequest):
    try:
        return await hle_api.create_share_link(
            subdomain, req.duration, req.label, req.max_uses
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/share/{link_id}", status_code=204)
async def delete_share_link(subdomain: ManagedSubdomain, link_id: int):
    try:
        await hle_api.delete_share_link(subdomain, link_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def get_config():
    key = ""
    if HLE_CONFIG.exists():
        key = json.loads(HLE_CONFIG.read_text()).get("api_key", "")
    if not key:
        key = os.environ.get("HLE_API_KEY", "")
    masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("set" if key else "")
    return {"api_key_set": bool(key), "api_key_masked": masked}


@app.post("/api/config", status_code=204)
async def update_config(req: UpdateConfigRequest):
    current = {}
    if HLE_CONFIG.exists():
        current = json.loads(HLE_CONFIG.read_text())
    current["api_key"] = req.api_key
    # The file holds the account API key: owner-only, even if it already existed.
    fd = os.open(HLE_CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fd = -1
            fh.write(json.dumps(current, indent=2))
    finally:
        if fd >= 0:
            os.close(fd)
    os.environ["HLE_API_KEY"] = req.api_key
    # Start any configured tunnels that were waiting for a key
    await tm.restore_all()


# ---------------------------------------------------------------------------
# Serve React SPA (must be last)
# ---------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:

    @app.get("/")
    async def index():
        return {"status": "frontend not built"}
