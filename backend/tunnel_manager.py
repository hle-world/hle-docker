"""Manages tunnel lifecycle: persistence and asyncio subprocess management."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from pathlib import Path

from backend.models import (
    AddTunnelRequest,
    TunnelConfig,
    TunnelStatus,
    UpdateTunnelRequest,
)

LOG_DIR = Path("/data/logs")
DATA_FILE = Path("/data/tunnels.json")

_processes: dict[str, asyncio.subprocess.Process] = {}

# Confirmed connected in the current session (subdomain from disk is stale
# until the tunnel actually re-registers with the relay).
_connected: set[str] = set()

# Tunnels explicitly stopped by the user — these show STOPPED, not FAILED.
_user_stopped: set[str] = set()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _load_all() -> dict[str, TunnelConfig]:
    if not DATA_FILE.exists():
        return {}
    data = json.loads(DATA_FILE.read_text())
    return {tid: TunnelConfig(**cfg) for tid, cfg in data.items()}


def _save_all(tunnels: dict[str, TunnelConfig]) -> None:
    DATA_FILE.write_text(
        json.dumps({tid: cfg.model_dump() for tid, cfg in tunnels.items()}, indent=2)
    )


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


async def _spawn(cfg: TunnelConfig) -> asyncio.subprocess.Process:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_DIR / f"tunnel-{cfg.id}.log", "ab")
    cmd = [
        "hle",
        "expose",
        "--service",
        cfg.service_url,
        "--label",
        cfg.label,
        "--auth",
        cfg.auth_mode,
    ]
    if cfg.verify_ssl:
        cmd.append("--verify-ssl")
    if not cfg.websocket_enabled:
        cmd.append("--no-websocket")
    if cfg.upstream_basic_auth:
        cmd.extend(["--upstream-basic-auth", cfg.upstream_basic_auth])
    if cfg.forward_host:
        cmd.append("--forward-host")
    env = {**os.environ}
    if cfg.api_key:
        env["HLE_API_KEY"] = cfg.api_key  # per-tunnel override; not visible in `ps`
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )


def _is_running(proc: asyncio.subprocess.Process | None) -> bool:
    return proc is not None and proc.returncode is None


async def _detect_subdomain(cfg_id: str, service_url: str, label: str) -> None:
    """Poll the relay API until the tunnel appears, then mark it connected."""
    from backend import hle_api

    for _ in range(15):  # up to ~30 seconds
        await asyncio.sleep(2)
        # Stop polling if process already exited (bad key, crash, etc.)
        proc = _processes.get(cfg_id)
        if not _is_running(proc):
            return
        try:
            live = await hle_api.list_live_tunnels()
            for t in live:
                if (
                    t.get("service_url") == service_url
                    or t.get("service_label") == label
                ):
                    subdomain = t.get("subdomain") or t.get("service_label")
                    if subdomain:
                        tunnels = _load_all()
                        if cfg_id in tunnels:
                            tunnels[cfg_id].subdomain = subdomain
                            _save_all(tunnels)
                        _connected.add(cfg_id)
                        return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def restore_all() -> None:
    """Start all saved tunnels. Skips silently if no API key is configured —
    tunnels will start automatically once the key is saved via the Settings UI."""
    if not os.environ.get("HLE_API_KEY"):
        print("[hle] No API key configured — tunnels will start once a key is set.")
        return
    for cfg in _load_all().values():
        if _is_running(_processes.get(cfg.id)):
            continue  # already running (e.g. called again after key is set)
        try:
            proc = await _spawn(cfg)
            _processes[cfg.id] = proc
            _user_stopped.discard(cfg.id)
            asyncio.create_task(_detect_subdomain(cfg.id, cfg.service_url, cfg.label))
        except Exception as exc:
            print(f"[hle] Failed to restore tunnel {cfg.id}: {exc}")


async def shutdown_all() -> None:
    """Terminate all tunnel processes on addon stop so HA Supervisor doesn't
    see orphan processes blocking the container shutdown."""
    procs = list(_processes.items())
    for tid, proc in procs:
        if _is_running(proc):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    if procs:
        await asyncio.gather(
            *[proc.wait() for _, proc in procs if _is_running(proc)],
            return_exceptions=True,
        )


async def add_tunnel(req: AddTunnelRequest) -> TunnelConfig:
    tunnels = _load_all()
    cfg = TunnelConfig(
        id=uuid.uuid4().hex[:8],
        service_url=req.service_url,
        label=req.label,
        name=req.name,
        auth_mode=req.auth_mode,
        verify_ssl=req.verify_ssl,
        websocket_enabled=req.websocket_enabled,
        api_key=req.api_key or None,
        upstream_basic_auth=req.upstream_basic_auth or None,
        forward_host=req.forward_host,
    )
    proc = await _spawn(cfg)
    _processes[cfg.id] = proc
    tunnels[cfg.id] = cfg
    _save_all(tunnels)
    asyncio.create_task(_detect_subdomain(cfg.id, cfg.service_url, cfg.label))
    return cfg


async def update_tunnel(tunnel_id: str, req: UpdateTunnelRequest) -> TunnelConfig:
    """Apply a partial update to a tunnel config, then restart it."""
    tunnels = _load_all()
    cfg = tunnels.get(tunnel_id)
    if cfg is None:
        raise KeyError(tunnel_id)

    # Apply only the fields that were explicitly provided
    changed = req.model_dump(exclude_none=True)
    # Empty string for api_key means "clear the override"
    if "api_key" in req.model_fields_set:
        changed["api_key"] = req.api_key or None
    if "upstream_basic_auth" in req.model_fields_set:
        changed["upstream_basic_auth"] = req.upstream_basic_auth or None

    # Track if label/service changed so we clear the stale subdomain
    label_or_url_changed = ("label" in changed and changed["label"] != cfg.label) or (
        "service_url" in changed and changed["service_url"] != cfg.service_url
    )

    for field, value in changed.items():
        setattr(cfg, field, value)

    if label_or_url_changed:
        cfg.subdomain = None

    tunnels[tunnel_id] = cfg
    _save_all(tunnels)

    # Stop existing process if running
    proc = _processes.get(tunnel_id)
    if _is_running(proc):
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()

    # Restart with updated config
    _connected.discard(tunnel_id)
    _user_stopped.discard(tunnel_id)
    new_proc = await _spawn(cfg)
    _processes[tunnel_id] = new_proc
    asyncio.create_task(_detect_subdomain(cfg.id, cfg.service_url, cfg.label))

    return cfg


async def remove_tunnel(tunnel_id: str) -> None:
    _connected.discard(tunnel_id)
    _user_stopped.add(tunnel_id)
    proc = _processes.pop(tunnel_id, None)
    if _is_running(proc):
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
    tunnels = _load_all()
    tunnels.pop(tunnel_id, None)
    _save_all(tunnels)


async def start_tunnel(tunnel_id: str) -> None:
    tunnels = _load_all()
    cfg = tunnels.get(tunnel_id)
    if cfg is None:
        raise KeyError(tunnel_id)
    if not _is_running(_processes.get(tunnel_id)):
        _connected.discard(tunnel_id)
        _user_stopped.discard(tunnel_id)
        _processes[tunnel_id] = await _spawn(cfg)
        asyncio.create_task(_detect_subdomain(cfg.id, cfg.service_url, cfg.label))


async def stop_tunnel(tunnel_id: str) -> None:
    _connected.discard(tunnel_id)
    _user_stopped.add(tunnel_id)
    proc = _processes.get(tunnel_id)
    if _is_running(proc):
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()


def list_tunnels() -> list[TunnelStatus]:
    return [_make_status(tid, cfg) for tid, cfg in _load_all().items()]


def get_tunnel(tunnel_id: str) -> TunnelStatus | None:
    cfg = _load_all().get(tunnel_id)
    return _make_status(tunnel_id, cfg) if cfg else None


def _last_error_line(tunnel_id: str) -> str | None:
    """Return the last non-empty line from the tunnel log, used for FAILED state."""
    log_path = LOG_DIR / f"tunnel-{tunnel_id}.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(errors="replace").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                return line
    except Exception:
        pass
    return None


def _make_status(tunnel_id: str, cfg: TunnelConfig) -> TunnelStatus:
    proc = _processes.get(tunnel_id)
    running = _is_running(proc)
    error: str | None = None

    if not running:
        if tunnel_id in _user_stopped:
            state = "STOPPED"
        else:
            state = "FAILED"
            error = _last_error_line(tunnel_id)
    elif tunnel_id in _connected:
        state = "CONNECTED"
    else:
        state = "CONNECTING"

    public_url = f"https://{cfg.subdomain}.hle.world" if cfg.subdomain else None
    return TunnelStatus(
        **cfg.model_dump(),
        state=state,
        error=error,
        public_url=public_url,
        pid=proc.pid if running else None,
    )
