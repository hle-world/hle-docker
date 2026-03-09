"""Pydantic models for the HLE add-on management API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class TunnelConfig(BaseModel):
    id: str
    service_url: str
    label: str
    name: Optional[str] = None  # display name; falls back to label if not set
    auth_mode: Literal["sso", "none"] = "sso"
    verify_ssl: bool = False
    websocket_enabled: bool = True
    api_key: Optional[str] = None  # per-tunnel key override; falls back to global
    upstream_basic_auth: Optional[str] = (
        None  # "user:pass" injected into upstream requests
    )
    forward_host: bool = False  # forward browser's Host header to local service
    response_timeout: Optional[int] = None  # server-side response timeout in seconds
    subdomain: Optional[str] = None  # populated once tunnel connects to relay
    stopped: bool = False  # persisted: user explicitly stopped this tunnel


class TunnelStatus(TunnelConfig):
    state: Literal["CONNECTED", "CONNECTING", "STOPPED", "FAILED"] = "STOPPED"
    error: Optional[str] = None  # last error line from log when state is FAILED
    public_url: Optional[str] = None
    pid: Optional[int] = None


class _TimeoutValidator(BaseModel):
    @field_validator("response_timeout")
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
