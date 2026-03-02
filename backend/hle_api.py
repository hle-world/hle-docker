"""Proxy helpers: calls to the HLE relay server API using ApiClient from hle-client."""

from __future__ import annotations

import os

from hle_client.api import ApiClient, ApiClientConfig


def _client() -> ApiClient:
    api_key = os.environ.get("HLE_API_KEY", "")
    return ApiClient(ApiClientConfig(api_key=api_key))


async def list_live_tunnels() -> list[dict]:
    return await _client().list_tunnels()


# ---------------------------------------------------------------------------
# Access rules
# ---------------------------------------------------------------------------

async def list_access_rules(subdomain: str) -> list[dict]:
    return await _client().list_access_rules(subdomain)


async def add_access_rule(subdomain: str, email: str, provider: str = "any") -> dict:
    return await _client().add_access_rule(subdomain, email, provider)


async def delete_access_rule(subdomain: str, rule_id: int) -> dict:
    return await _client().delete_access_rule(subdomain, rule_id)


# ---------------------------------------------------------------------------
# PIN protection
# ---------------------------------------------------------------------------

async def get_pin_status(subdomain: str) -> dict:
    return await _client().get_tunnel_pin_status(subdomain)


async def set_pin(subdomain: str, pin: str) -> dict:
    return await _client().set_tunnel_pin(subdomain, pin)


async def remove_pin(subdomain: str) -> dict:
    return await _client().remove_tunnel_pin(subdomain)


# ---------------------------------------------------------------------------
# Basic auth
# ---------------------------------------------------------------------------

async def get_basic_auth_status(subdomain: str) -> dict:
    return await _client().get_tunnel_basic_auth_status(subdomain)


async def set_basic_auth(subdomain: str, username: str, password: str) -> dict:
    return await _client().set_tunnel_basic_auth(subdomain, username, password)


async def remove_basic_auth(subdomain: str) -> dict:
    return await _client().remove_tunnel_basic_auth(subdomain)


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------

async def list_share_links(subdomain: str) -> list[dict]:
    return await _client().list_share_links(subdomain)


async def create_share_link(subdomain: str, duration: str, label: str, max_uses: int | None) -> dict:
    return await _client().create_share_link(subdomain, duration=duration, label=label, max_uses=max_uses)


async def delete_share_link(subdomain: str, link_id: int) -> dict:
    return await _client().delete_share_link(subdomain, link_id)
