"""The container's management API must refuse unauthenticated callers.

The published port is reachable from the network, so every route needs the
login token (backend/auth.py), and the subdomain-keyed relay routes only act
on tunnels this container manages.
"""

from __future__ import annotations

import importlib
import json
import re
import stat
import sys

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend import auth
from backend import tunnel_manager as tm


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
    yield module
    tm._processes.clear()


def _token(tmp_path) -> str:
    return (tmp_path / auth.TOKEN_FILENAME).read_text().strip()


def _authed(main, tmp_path) -> TestClient:
    client = TestClient(main.app)
    client.headers["Authorization"] = f"Bearer {_token(tmp_path)}"
    return client


def test_token_file_created_0600(main, tmp_path) -> None:
    token_file = tmp_path / auth.TOKEN_FILENAME
    assert len(_token(tmp_path)) >= 32
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_every_api_route_refuses_without_token(main) -> None:
    client = TestClient(main.app)
    routes = [
        (method, re.sub(r"\{[^}]+\}", "1", route.path))
        for route in main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
        for method in route.methods
    ]
    assert len(routes) > 20  # the whole surface, not a sample
    for method, path in routes:
        resp = client.request(method, path)
        assert resp.status_code == 401, (method, path, resp.status_code)
        assert resp.headers["www-authenticate"] == auth.AUTH_CHALLENGE


def test_wrong_token_refused(main) -> None:
    client = TestClient(main.app)
    resp = client.get("/api/tunnels", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    client.cookies.set(auth.COOKIE_NAME, "forged")
    assert client.get("/api/tunnels").status_code == 401


def test_ui_redirects_to_login(main) -> None:
    client = TestClient(main.app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"] == "login"
    assert client.get("/login").status_code == 200


def test_bearer_and_login_cookie_allowed(main, tmp_path) -> None:
    assert _authed(main, tmp_path).get("/api/tunnels").status_code == 200

    client = TestClient(main.app, follow_redirects=False)
    assert client.post("/login", data={"token": "wrong"}).status_code == 401
    resp = client.post("/login", data={"token": _token(tmp_path)})
    assert resp.status_code == 303
    assert "samesite=strict" in resp.headers["set-cookie"].lower()
    assert client.get("/api/tunnels").status_code == 200


def test_subdomain_routes_limited_to_managed_tunnels(
    main, tmp_path, monkeypatch
) -> None:
    (tmp_path / "tunnels.json").write_text(
        json.dumps(
            {
                "t1": {
                    "id": "t1",
                    "service_url": "http://192.0.2.10:8080",
                    "label": "svc",
                    "subdomain": "svc-owner",
                }
            }
        )
    )
    called = []

    async def _fake(subdomain, *args):
        called.append(subdomain)
        return {"has_pin": False, "updated_at": None}

    monkeypatch.setattr(main.hle_api, "get_pin_status", _fake)
    monkeypatch.setattr(main.hle_api, "remove_pin", _fake)
    monkeypatch.setattr(main.hle_api, "create_share_link", _fake)
    client = _authed(main, tmp_path)

    assert client.get("/api/tunnels/someone-else/pin").status_code == 404
    assert client.delete("/api/tunnels/someone-else/pin").status_code == 404
    assert client.post("/api/tunnels/someone-else/share", json={}).status_code == 404
    assert called == []

    assert client.get("/api/tunnels/svc-owner/pin").status_code == 200
    assert called == ["svc-owner"]
