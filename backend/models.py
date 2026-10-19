"""Pydantic models for the HLE add-on management API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class _TunnelFields(BaseModel):
    """Tunnel settings that are safe to return from the API."""

    id: str
    service_url: str
    label: str
    name: Optional[str] = None  # display name; falls back to label if not set
    auth_mode: Literal["sso", "none"] = "sso"
    verify_ssl: bool = False
    websocket_enabled: bool = True
    forward_host: bool = False  # forward browser's Host header to local service
    response_timeout: Optional[int] = None  # server-side response timeout in seconds
    subdomain: Optional[str] = None  # populated once tunnel connects to relay
    public_url: Optional[str] = (
        None  # server-authoritative public URL (no client-side construction)
    )
    zone_domain: Optional[str] = (
        None  # custom zone domain — informational only, never used to build URLs
    )
    webhook_path: Optional[str] = None  # webhook path prefix (e.g. "/webhook/github")
    server_tunnel_id: Optional[str] = None  # server-assigned UUID
    tier: Optional[str] = None  # billing tier from server
    stopped: bool = False  # persisted: user explicitly stopped this tunnel


class TunnelConfig(_TunnelFields):
    """Persisted tunnel config, including secrets. Never return it from the API."""

    api_key: Optional[str] = None  # per-tunnel key override; falls back to global
    upstream_basic_auth: Optional[str] = (
        None  # "user:pass" injected into upstream requests
    )


class TunnelStatus(_TunnelFields):
    """API view of a tunnel. Secrets are reduced to set/masked indicators."""

    state: Literal["CONNECTED", "CONNECTING", "STOPPED", "FAILED"] = "STOPPED"
    error: Optional[str] = None  # last error line from log when state is FAILED
    pid: Optional[int] = None
    api_key_set: bool = False  # a per-tunnel key override is configured
    api_key_masked: Optional[str] = None  # e.g. "hle_...a1b2"; never the full key
    has_upstream_basic_auth: bool = False
    upstream_basic_auth_user: Optional[str] = None  # username only, never the password


def mask_secret(value: str) -> str:
    """Show only enough of a key to recognise it (same format as /api/config)."""
    return f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "set"


class _TimeoutValidator(BaseModel):
    @field_validator("response_timeout", check_fields=False)
    @classmethod
    def validate_response_timeout(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 1200):
            raise ValueError("response_timeout must be between 1 and 1200 seconds")
        return v


class AddTunnelRequest(_TimeoutValidator):
    service_url: str
    label: str
    name: Optional[str] = None
    auth_mode: Literal["sso", "none"] = "sso"
    verify_ssl: bool = False
    websocket_enabled: bool = True
    api_key: Optional[str] = None
    upstream_basic_auth: Optional[str] = None
    forward_host: bool = False
    response_timeout: Optional[int] = None
    webhook_path: Optional[str] = None


class UpdateTunnelRequest(_TimeoutValidator):
    service_url: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    auth_mode: Optional[Literal["sso", "none"]] = None
    verify_ssl: Optional[bool] = None
    websocket_enabled: Optional[bool] = None
    api_key: Optional[str] = None  # set to "" to clear the override
    upstream_basic_auth: Optional[str] = None  # set to "" to clear
    forward_host: Optional[bool] = None
    response_timeout: Optional[int] = None
    webhook_path: Optional[str] = None


class UpdateConfigRequest(BaseModel):
    api_key: str


class AddAccessRuleRequest(BaseModel):
    email: str
    provider: Literal["any", "google", "github", "hle"] = "any"


class SetPinRequest(BaseModel):
    pin: str  # 4-8 digits


class SetBasicAuthRequest(BaseModel):
    username: str
    password: str


class CreateShareLinkRequest(BaseModel):
    duration: Literal["1h", "24h", "7d"] = "24h"
    label: str = ""
    max_uses: Optional[int] = None


class Notice(BaseModel):
    """Server-pushed informational message captured from the CLI's events.

    The relay streams these over the tunnel's control WebSocket; the CLI
    turns each into a ``notice`` event on stdout under ``--events jsonl``,
    whose ``level`` and ``message`` are recorded here for the UI.
    """

    level: Literal["info", "success", "warning", "error"]
    message: str
    ts: datetime
