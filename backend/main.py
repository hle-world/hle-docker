"""FastAPI management API for HLE Docker."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles  # noqa: F401 — used in conditional mount below

from backend import hle_api
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await tm.restore_all()
    yield
    await tm.shutdown_all()


app = FastAPI(title="HLE Docker API", docs_url=None, redoc_url=None, lifespan=lifespan)

HLE_CONFIG = Path("/data/hle_config.json")
STATIC_DIR = Path("/app/backend/static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_api_key() -> None:
    if not os.environ.get("HLE_API_KEY"):
        raise HTTPException(
            status_code=400, detail="API key not configured. Set it in Settings first."
        )


# ---------------------------------------------------------------------------
# Tunnel management
# ---------------------------------------------------------------------------


@app.get("/api/tunnels", response_model=list[TunnelStatus])
async def list_tunnels():
    return tm.list_tunnels()


@app.post("/api/tunnels", response_model=TunnelStatus, status_code=201)
async def add_tunnel(req: AddTunnelRequest):
    _require_api_key()
    cfg = await tm.add_tunnel(req)
    return tm.get_tunnel(cfg.id)


@app.patch("/api/tunnels/{tunnel_id}", response_model=TunnelStatus)
async def update_tunnel(tunnel_id: str, req: UpdateTunnelRequest):
    if tm.get_tunnel(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    cfg = await tm.update_tunnel(tunnel_id, req)
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


@app.get("/api/tunnels/{tunnel_id}/favicon")
async def get_tunnel_favicon(tunnel_id: str):
    """Return the favicon from the tunnel's local service, cached on disk."""
    # Serve from cache if available
    cached = FAVICON_DIR / tunnel_id
    if cached.exists():
        data = cached.read_bytes()
        ct = "image/x-icon"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            ct = "image/png"
        elif data[:5] in (b"<?xml", b"<svg "):
            ct = "image/svg+xml"
        return Response(content=data, media_type=ct)

    # Look up tunnel config to get service_url
    status = tm.get_tunnel(tunnel_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    service_url = status.service_url.rstrip("/")

    # Common favicon paths — services like Jellyfin use /web/favicon.ico
    favicon_paths = [
        "/favicon.ico",
        "/web/favicon.ico",
        "/favicon.png",
        "/favicon.svg",
    ]

    async with httpx.AsyncClient(timeout=5, verify=False) as client:  # nosec B501 — local LAN services often use self-signed certs
        icon_data: bytes | None = None
        icon_ct = "image/x-icon"

        for path in favicon_paths:
            try:
                resp = await client.get(f"{service_url}{path}", follow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 0:
                    ct_header = resp.headers.get("content-type", "")
                    if (
                        "image" in ct_header
                        or "octet-stream" in ct_header
                        or resp.content[:4] in (b"\x00\x00\x01\x00", b"\x89PNG")
                    ):
                        icon_data = resp.content
                        if "png" in ct_header:
                            icon_ct = "image/png"
                        elif "svg" in ct_header:
                            icon_ct = "image/svg+xml"
                        break
            except Exception:
                pass

        # Fallback: parse <link rel="icon"> from HTML
        if icon_data is None:
            try:
                resp = await client.get(service_url, follow_redirects=True)
                if resp.status_code == 200:
                    html = resp.text[:8192]  # only scan the head
                    match = re.search(
                        r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]+href=["\']([^"\']+)',
                        html,
                        re.IGNORECASE,
                    )
                    if match:
                        href = match.group(1)
                        # Resolve relative to final URL (after redirects)
                        base_url = str(resp.url).rstrip("/")
                        if href.startswith("//"):
                            href = "http:" + href
                        elif href.startswith("/"):
                            # Absolute path — use service origin
                            href = service_url + href
                        elif not href.startswith("http"):
                            # Relative path — resolve against final URL
                            href = base_url + "/" + href
                        icon_resp = await client.get(href, follow_redirects=True)
                        if icon_resp.status_code == 200 and len(icon_resp.content) > 0:
                            icon_data = icon_resp.content
                            ct_header = icon_resp.headers.get("content-type", "")
                            if "png" in ct_header:
                                icon_ct = "image/png"
                            elif "svg" in ct_header:
                                icon_ct = "image/svg+xml"
            except Exception:
                pass

    if icon_data is None:
        raise HTTPException(status_code=404, detail="No favicon found")

    # Cache to disk
    FAVICON_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(icon_data)

    return Response(content=icon_data, media_type=icon_ct)


# ---------------------------------------------------------------------------
# Access rules (keyed by subdomain, proxied to relay)
# ---------------------------------------------------------------------------


@app.get("/api/tunnels/{subdomain}/access")
async def list_access_rules(subdomain: str):
    try:
        return await hle_api.list_access_rules(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.post("/api/tunnels/{subdomain}/access", status_code=201)
async def add_access_rule(subdomain: str, req: AddAccessRuleRequest):
    try:
        return await hle_api.add_access_rule(subdomain, req.email, req.provider)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/access/{rule_id}", status_code=204)
async def delete_access_rule(subdomain: str, rule_id: int):
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
async def get_pin_status(subdomain: str):
    try:
        return await hle_api.get_pin_status(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.put("/api/tunnels/{subdomain}/pin", status_code=204)
async def set_pin(subdomain: str, req: SetPinRequest):
    try:
        await hle_api.set_pin(subdomain, req.pin)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/pin", status_code=204)
async def remove_pin(subdomain: str):
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
async def get_basic_auth_status(subdomain: str):
    try:
        return await hle_api.get_basic_auth_status(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.put("/api/tunnels/{subdomain}/basic-auth", status_code=204)
async def set_basic_auth(subdomain: str, req: SetBasicAuthRequest):
    try:
        await hle_api.set_basic_auth(subdomain, req.username, req.password)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/basic-auth", status_code=204)
async def remove_basic_auth(subdomain: str):
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
async def list_share_links(subdomain: str):
    try:
        return await hle_api.list_share_links(subdomain)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.post("/api/tunnels/{subdomain}/share", status_code=201)
async def create_share_link(subdomain: str, req: CreateShareLinkRequest):
    try:
        return await hle_api.create_share_link(
            subdomain, req.duration, req.label, req.max_uses
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        )


@app.delete("/api/tunnels/{subdomain}/share/{link_id}", status_code=204)
async def delete_share_link(subdomain: str, link_id: int):
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
    HLE_CONFIG.write_text(json.dumps(current, indent=2))
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
