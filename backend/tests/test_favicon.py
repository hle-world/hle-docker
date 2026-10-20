"""The favicon proxy must never serve upstream-controlled script.

Only raster formats (confirmed by magic bytes) are served from the management
origin, responses are hardened with a sandboxing CSP and ``nosniff``, and the
proxy never follows a redirect or ``<link rel=icon>`` href that leaves the
service's own origin. These tests pin those properties down with a fake
upstream so nothing touches the network.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend import tunnel_manager as tm

PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 64
ICO = b"\x00\x00\x01\x00" + b"i" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

SERVICE_URL = "http://192.0.2.10:8080"

FAVICON_PATHS = (
    "/favicon.ico",
    "/web/favicon.ico",
    "/favicon.png",
    "/favicon.svg",
)


class _FakeResponse:
    def __init__(self, url, status_code=200, content=b"", headers=None):
        self.url = httpx.URL(url)
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("utf-8", "replace")
        self.is_redirect = 300 <= status_code < 400 and "location" in self.headers

    async def aiter_bytes(self):
        # Small chunks so the streaming size cap is exercised mid-body.
        for start in range(0, len(self.content), 64 * 1024):
            yield self.content[start : start + 64 * 1024]


class _Stream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, routes):
        self._routes = routes
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, follow_redirects=False):
        self.requested.append(str(url))
        handler = self._routes.get(str(url))
        if handler is None:
            return _Stream(_FakeResponse(url, status_code=404))
        return _Stream(handler(str(url)))


class _Factory:
    """Stand-in for ``httpx.AsyncClient`` that records every URL requested."""

    def __init__(self, routes):
        self._routes = routes
        self.clients: list[_FakeClient] = []

    def __call__(self, *args, **kwargs):
        client = _FakeClient(self._routes)
        self.clients.append(client)
        return client

    @property
    def requested(self) -> list[str]:
        return [url for client in self.clients for url in client.requested]


def _ok(url, content, content_type):
    headers = {"content-type": content_type}
    return _FakeResponse(url, 200, content, headers)


def _serve_svg(url):
    return _ok(url, SVG, "image/svg+xml")


def _redirect(url, location):
    return _FakeResponse(url, 302, b"", {"location": location})


@pytest.fixture
def main(tmp_path, monkeypatch):
    """Import backend.main fresh against a temp data dir."""
    monkeypatch.setenv("HLE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)
    monkeypatch.setattr(tm, "DATA_FILE", tmp_path / "tunnels.json")
    monkeypatch.setattr(tm, "LOG_DIR", tmp_path / "logs")
    tm._processes.clear()
    if "backend.main" in sys.modules:
        module = importlib.reload(sys.modules["backend.main"])
    else:
        module = importlib.import_module("backend.main")
    # This image keeps its cache under /data; redirect it to the temp dir.
    monkeypatch.setattr(module, "FAVICON_DIR", tmp_path / "favicons")
    yield module
    tm._processes.clear()


def _authed(main, tmp_path) -> TestClient:
    client = TestClient(main.app)
    token = (tmp_path / auth.TOKEN_FILENAME).read_text().strip()
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _write_tunnel(tmp_path, service_url=SERVICE_URL) -> None:
    cfg = {"id": "t1", "service_url": service_url, "label": "svc"}
    (tmp_path / "tunnels.json").write_text(json.dumps({"t1": cfg}))


def _install(main, monkeypatch, routes) -> _Factory:
    factory = _Factory(routes)
    monkeypatch.setattr(main.httpx, "AsyncClient", factory)
    return factory


# ---------------------------------------------------------------------------
# Never serve SVG
# ---------------------------------------------------------------------------


def test_svg_favicon_is_not_served(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    routes = {f"{SERVICE_URL}{path}": _serve_svg for path in FAVICON_PATHS}
    routes[SERVICE_URL] = lambda url: _ok(url, b"<html></html>", "text/html")
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404
    assert b"<svg" not in resp.content
    assert not (tmp_path / "favicons" / "t1").exists()


def test_svg_in_link_href_is_not_served(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    html = b'<html><head><link rel="icon" href="/logo.svg"></head></html>'
    routes = {SERVICE_URL: lambda url: _ok(url, html, "text/html")}
    routes[f"{SERVICE_URL}/logo.svg"] = _serve_svg
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404


def test_cached_svg_is_not_served(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    cached = tmp_path / "favicons" / "t1"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(SVG)
    routes = {url: (lambda u: _FakeResponse(u, 404)) for url in FAVICON_PATHS}
    routes[SERVICE_URL] = lambda u: _FakeResponse(u, 404)
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Only fetch the service's own origin
# ---------------------------------------------------------------------------


def test_cross_origin_href_is_not_fetched(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    html = (
        b'<html><head><link rel="icon" '
        b'href="http://evil.example/evil.ico"></head></html>'
    )
    routes = {SERVICE_URL: lambda url: _ok(url, html, "text/html")}
    routes["http://evil.example/evil.ico"] = lambda url: _ok(url, PNG, "image/png")
    factory = _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404
    assert not any("evil.example" in url for url in factory.requested)


def test_cross_origin_redirect_is_not_followed(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    routes = {
        f"{SERVICE_URL}/favicon.ico": lambda url: _redirect(
            url, "http://evil.example/x.png"
        ),
        "http://evil.example/x.png": lambda url: _ok(url, PNG, "image/png"),
        SERVICE_URL: lambda url: _FakeResponse(url, 404),
    }
    factory = _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404
    assert not any("evil.example" in url for url in factory.requested)


# ---------------------------------------------------------------------------
# Raster images are served, hardened
# ---------------------------------------------------------------------------


def test_same_origin_href_png_is_served_hardened(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    html = b'<html><head><link rel="icon" href="/static/icon.png"></head></html>'
    routes = {SERVICE_URL: lambda url: _ok(url, html, "text/html")}
    routes[f"{SERVICE_URL}/static/icon.png"] = lambda url: _ok(url, PNG, "image/png")
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 200
    assert resp.content == PNG
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_direct_ico_path_is_served(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    routes = {
        f"{SERVICE_URL}/favicon.ico": lambda url: _ok(
            url, ICO, "application/octet-stream"
        )
    }
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/x-icon"


def test_oversized_image_is_rejected(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    big = PNG + b"0" * main.MAX_FAVICON_BYTES
    routes = {f"{SERVICE_URL}/favicon.ico": lambda url: _ok(url, big, "image/png")}
    routes[SERVICE_URL] = lambda url: _FakeResponse(url, 404)
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404


def test_declared_oversized_body_is_not_read(main, tmp_path, monkeypatch) -> None:
    _write_tunnel(tmp_path)
    declared = {"content-type": "image/png", "content-length": str(10**9)}
    routes = {
        f"{SERVICE_URL}/favicon.ico": lambda url: _FakeResponse(url, 200, PNG, declared)
    }
    routes[SERVICE_URL] = lambda url: _FakeResponse(url, 404)
    _install(main, monkeypatch, routes)

    resp = _authed(main, tmp_path).get("/api/tunnels/t1/favicon")

    assert resp.status_code == 404


def test_read_capped_stops_past_the_limit(main) -> None:
    body = _FakeResponse("http://svc/x", 200, b"x" * (300 * 1024))

    assert asyncio.run(main._read_capped(body, 256 * 1024)) is None
    assert asyncio.run(main._read_capped(body, 400 * 1024)) == body.content
