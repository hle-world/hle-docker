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

# Last meaningful error/warning line per tunnel (only WARNING/ERROR level).
_last_errors: dict[str, str] = {}


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
    if cfg.response_timeout is not None:
        cmd.extend(["--timeout", str(cfg.response_timeout)])
    env = {**os.environ}
    if cfg.api_key:
        env["HLE_API_KEY"] = cfg.api_key  # per-tunnel override; not visible in `ps`
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    # Stream stdout: write to log file AND parse for status in real-time
    asyncio.create_task(_stream_output(cfg.id, proc))
    return proc


async def _stream_output(cfg_id: str, proc: asyncio.subprocess.Process) -> None:
    """Read CLI stdout line-by-line, write to log file, and parse status."""
    log_path = LOG_DIR / f"tunnel-{cfg_id}.log"
    with open(log_path, "ab") as log_file:
        assert proc.stdout is not None
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            log_file.write(line_bytes)
            log_file.flush()
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            _parse_status_line(cfg_id, line)


def _is_running(proc: asyncio.subprocess.Process | None) -> bool:
    return proc is not None and proc.returncode is None


def _parse_status_line(cfg_id: str, line: str) -> None:
    """Parse a CLI log line and update tunnel state accordingly."""
    if "Tunnel registered:" in line:
        _connected.add(cfg_id)
        _last_errors.pop(cfg_id, None)
        # Extract subdomain from url= field (e.g. "url=https://ha-xxxx.hle.world")
        if "url=https://" in line:
            try:
                url_part = line.split("url=https://", 1)[1].split()[0]
                subdomain = url_part.split(".hle.world")[0]
                if subdomain:
                    tunnels = _load_all()
                    if cfg_id in tunnels:
                        tunnels[cfg_id].subdomain = subdomain
                        _save_all(tunnels)
            except (IndexError, ValueError):
                pass
    elif "Connection lost:" in line:
        _connected.discard(cfg_id)
        _last_errors[cfg_id] = line
    elif "Reconnecting in" in line:
        _connected.discard(cfg_id)
    elif "WARNING" in line or "ERROR" in line:
        # Only store actual warning/error lines (not INFO traffic logs)
        _last_errors[cfg_id] = line


async def _monitor_tunnel(cfg_id: str, service_url: str, label: str) -> None:
    """Detect subdomain, then continuously monitor tunnel health on the relay.

    Phase 1: poll every 2 s for 30 s (fast detection for happy path).
    Phase 2: poll every 10 s indefinitely while the process is alive
             (handles delayed connection, e.g. after max-tunnels clears).
    Phase 3: after connection, poll every 30 s to verify the tunnel stays
             on the relay. Removes from _connected if it disappears (e.g.
             server closed with 4003 for exceeding tunnel limit).
    """
    from backend import hle_api

    async def _poll_once() -> bool:
        """Return True if the tunnel was found on the relay."""
        try:
            live = await hle_api.list_live_tunnels()
            for t in live:
                t_label = t.get("service_label") or ""
                # Match on label (unique per user on the relay).
                # Previously matched on service_url OR label, which caused
                # wrong subdomain assignment when multiple tunnels shared a URL.
                if t_label == label:
                    subdomain = t.get("subdomain") or t_label
                    if subdomain:
                        tunnels = _load_all()
                        if cfg_id in tunnels:
                            tunnels[cfg_id].subdomain = subdomain
                            _save_all(tunnels)
                        _connected.add(cfg_id)
                        return True
        except Exception:
            pass
        return False

    # Phase 1: fast polling (every 2 s, up to ~30 s)
    for _ in range(15):
        await asyncio.sleep(2)
        proc = _processes.get(cfg_id)
        if not _is_running(proc):
            return
        if await _poll_once():
            break
    else:
        # Phase 2: slow polling (every 10 s) while process is alive
        while True:
            await asyncio.sleep(10)
            proc = _processes.get(cfg_id)
            if not _is_running(proc):
                return
            if await _poll_once():
                break

    # Phase 3: health monitoring — verify tunnel stays on relay
    while True:
        await asyncio.sleep(30)
        proc = _processes.get(cfg_id)
        if not _is_running(proc):
            _connected.discard(cfg_id)
            return
        try:
            live = await hle_api.list_live_tunnels()
            found = any(
                t.get("service_url") == service_url or t.get("service_label") == label
                for t in live
            )
            if found:
                _connected.add(cfg_id)
            else:
                _connected.discard(cfg_id)
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
        if cfg.stopped:
            _user_stopped.add(cfg.id)
            continue  # user explicitly stopped this tunnel before restart
        try:
            proc = await _spawn(cfg)
            _processes[cfg.id] = proc
            _user_stopped.discard(cfg.id)
            asyncio.create_task(_monitor_tunnel(cfg.id, cfg.service_url, cfg.label))
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


class DuplicateLabelError(ValueError):
    """Raised when a tunnel with the same label already exists."""


async def add_tunnel(req: AddTunnelRequest) -> TunnelConfig:
    tunnels = _load_all()
    for existing in tunnels.values():
        if existing.label == req.label:
            raise DuplicateLabelError(
                f"A tunnel with label '{req.label}' already exists"
            )
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
    asyncio.create_task(_monitor_tunnel(cfg.id, cfg.service_url, cfg.label))
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

    # Reject label changes that collide with another tunnel
    if "label" in changed and changed["label"] != cfg.label:
        for tid, other in tunnels.items():
            if tid != tunnel_id and other.label == changed["label"]:
                raise DuplicateLabelError(
                    f"A tunnel with label '{changed['label']}' already exists"
                )

    # Track if label/service changed so we clear the stale subdomain
    label_or_url_changed = ("label" in changed and changed["label"] != cfg.label) or (
        "service_url" in changed and changed["service_url"] != cfg.service_url
    )

    for field, value in changed.items():
        setattr(cfg, field, value)

    cfg.stopped = False  # editing implies user wants it running

    if label_or_url_changed:
        cfg.subdomain = None
        # Clear cached favicon when service URL changes
        favicon_path = Path("/data/favicons") / tunnel_id
        favicon_path.unlink(missing_ok=True)

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
    _last_errors.pop(tunnel_id, None)
    new_proc = await _spawn(cfg)
    _processes[tunnel_id] = new_proc
    asyncio.create_task(_monitor_tunnel(cfg.id, cfg.service_url, cfg.label))

    return cfg


async def remove_tunnel(tunnel_id: str) -> None:
    _connected.discard(tunnel_id)
    _user_stopped.add(tunnel_id)
    _last_errors.pop(tunnel_id, None)
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
    # Clean up cached favicon
    favicon_path = Path("/data/favicons") / tunnel_id
    favicon_path.unlink(missing_ok=True)


async def start_tunnel(tunnel_id: str) -> None:
    tunnels = _load_all()
    cfg = tunnels.get(tunnel_id)
    if cfg is None:
        raise KeyError(tunnel_id)
    if not _is_running(_processes.get(tunnel_id)):
        _connected.discard(tunnel_id)
        _user_stopped.discard(tunnel_id)
        _last_errors.pop(tunnel_id, None)
        # Clear persisted stopped state
        if cfg.stopped:
            cfg.stopped = False
            tunnels[tunnel_id] = cfg
            _save_all(tunnels)
        _processes[tunnel_id] = await _spawn(cfg)
        asyncio.create_task(_monitor_tunnel(cfg.id, cfg.service_url, cfg.label))


async def stop_tunnel(tunnel_id: str) -> None:
    _connected.discard(tunnel_id)
    _user_stopped.add(tunnel_id)
    _last_errors.pop(tunnel_id, None)
    proc = _processes.get(tunnel_id)
    if _is_running(proc):
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
    # Persist stopped state so it survives restarts
    tunnels = _load_all()
    if tunnel_id in tunnels:
        tunnels[tunnel_id].stopped = True
        _save_all(tunnels)


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
            error = _last_errors.get(tunnel_id) or _last_error_line(tunnel_id)
    elif tunnel_id in _connected:
        state = "CONNECTED"
    else:
        state = "CONNECTING"
        error = _last_errors.get(tunnel_id)

    public_url = f"https://{cfg.subdomain}.hle.world" if cfg.subdomain else None
    return TunnelStatus(
        **cfg.model_dump(),
        state=state,
        error=error,
        public_url=public_url,
        pid=proc.pid if running else None,
    )
