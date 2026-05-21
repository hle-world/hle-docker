"""Manages tunnel lifecycle: persistence and asyncio subprocess management."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from backend.models import (
    AddTunnelRequest,
    Notice,
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

# Server-pushed NOTICE messages, ring buffer per tunnel.
_NOTICE_BUFFER_SIZE = 20
_last_notices: dict[str, deque[Notice]] = {}

# Map CLI glyph prefix → notice level. The CLI renders notices with these
# leading characters (see hle_client/notices.py); we recover the level here
# without coupling to a structured CLI output mode that does not yet exist.
_NOTICE_GLYPHS: dict[str, str] = {
    "ℹ": "info",
    "✓": "success",
    "⚠": "warning",
    "✗": "error",
}


def _record_notice(cfg_id: str, level: str, message: str) -> None:
    buf = _last_notices.setdefault(cfg_id, deque(maxlen=_NOTICE_BUFFER_SIZE))
    buf.append(Notice(level=level, message=message, ts=datetime.now(timezone.utc)))


def get_notices(cfg_id: str) -> list[Notice]:
    """Return the recent NOTICE buffer for a tunnel (oldest → newest)."""
    return list(_last_notices.get(cfg_id, ()))


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
    if cfg.webhook_path:
        cmd = [
            "hle", "webhook",
            "--path", cfg.webhook_path,
            "--forward-to", cfg.service_url,
            "--label", cfg.label,
        ]
    else:
        cmd = [
            "hle", "expose",
            "--service", cfg.service_url,
            "--label", cfg.label,
            "--auth", cfg.auth_mode,
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
    """Parse a CLI log line and update tunnel state accordingly.

    The webapp formerly extracted the tunnel subdomain from the
    ``url=https://...`` field of the ``Tunnel registered:`` log line.
    Subdomain (and the rest of the live state) is now fetched
    server-authoritatively via ``GET /api/tunnels/{subdomain}/status``
    in :func:`_monitor_tunnel`, so this routine only tracks
    connection-state transitions and server-pushed NOTICE messages.
    """
    # Server NOTICEs are rendered by the CLI with a leading glyph + space.
    # Match them first so a notice line never falls through to the
    # WARNING/ERROR string heuristic below.
    glyph = line[:1]
    if glyph in _NOTICE_GLYPHS:
        message = line[1:].strip()
        if message:
            _record_notice(cfg_id, _NOTICE_GLYPHS[glyph], message)
        return

    if "Tunnel registered:" in line:
        _connected.add(cfg_id)
        _last_errors.pop(cfg_id, None)
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
                            # Enrich with server-authoritative fields. The relay
                            # is the source of truth for public_url — never
                            # reconstruct it client-side.
                            tunnels[cfg_id].public_url = t.get("public_url")
                            tunnels[cfg_id].zone_domain = t.get("zone")
                            tunnels[cfg_id].server_tunnel_id = t.get("tunnel_id")
                            tunnels[cfg_id].tier = t.get("tier")
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

    # Phase 3: health monitoring — single /status call per cycle.
    # Server is authoritative for is_active, auth_mode, zone, etc.
    while True:
        await asyncio.sleep(30)
        proc = _processes.get(cfg_id)
        if not _is_running(proc):
            _connected.discard(cfg_id)
            return

        tunnels = _load_all()
        cfg = tunnels.get(cfg_id)
        if cfg is None or not cfg.subdomain:
            # Lost the subdomain somehow — fall back to the list-tunnels
            # path so the next loop iteration can re-discover it.
            continue

        try:
            status = await hle_api.get_tunnel_status(cfg.subdomain)
        except Exception:
            # Transient server / network error — keep current state and retry.
            continue

        if status.get("is_active"):
            _connected.add(cfg_id)
        else:
            _connected.discard(cfg_id)
            continue

        # Refresh server-authoritative fields. tier no longer flows through
        # /status (it's account-wide, not per-tunnel) so we leave it alone.
        # public_url is the source of truth — never reconstructed locally.
        changed = False
        server_to_local = {
            "public_url": "public_url",
            "zone": "zone_domain",
            "auth_mode": "auth_mode",
            "subdomain": "subdomain",
        }
        for server_key, local_attr in server_to_local.items():
            val = status.get(server_key)
            if val is not None and getattr(cfg, local_attr, None) != val:
                setattr(cfg, local_attr, val)
                changed = True
        if changed:
            _save_all(tunnels)


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
    is_webhook = bool(req.webhook_path)
    cfg = TunnelConfig(
        id=uuid.uuid4().hex[:8],
        service_url=req.service_url,
        label=req.label,
        name=req.name,
        auth_mode="none" if is_webhook else req.auth_mode,
        verify_ssl=False if is_webhook else req.verify_ssl,
        websocket_enabled=False if is_webhook else req.websocket_enabled,
        api_key=req.api_key or None,
        upstream_basic_auth=None if is_webhook else (req.upstream_basic_auth or None),
        forward_host=False if is_webhook else req.forward_host,
        response_timeout=req.response_timeout,
        webhook_path=req.webhook_path,
    )
    proc = await _spawn(cfg)
    _processes[cfg.id] = proc
    tunnels[cfg.id] = cfg
    _save_all(tunnels)
    asyncio.create_task(_monitor_tunnel(cfg.id, cfg.service_url, cfg.label))
    return cfg


async def update_tunnel(tunnel_id: str, req: UpdateTunnelRequest) -> TunnelConfig:
    """Apply a partial update to a tunnel config.

    Auth-mode changes are handled via the server REST API (no restart).
    Connection-affecting changes (label, service_url, etc.) trigger a restart.
    """
    from backend import hle_api

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

    # Detect auth_mode change before applying
    old_auth_mode = cfg.auth_mode
    new_auth_mode = changed.get("auth_mode")
    auth_mode_changed = new_auth_mode is not None and new_auth_mode != old_auth_mode

    # Track if label/service changed so we clear the stale subdomain
    label_or_url_changed = ("label" in changed and changed["label"] != cfg.label) or (
        "service_url" in changed and changed["service_url"] != cfg.service_url
    )

    for field, value in changed.items():
        setattr(cfg, field, value)

    if label_or_url_changed:
        cfg.subdomain = None
        cfg.public_url = None
        cfg.zone_domain = None
        cfg.server_tunnel_id = None
        # Clear cached favicon when service URL changes
        favicon_path = Path("/data/favicons") / tunnel_id
        favicon_path.unlink(missing_ok=True)

    tunnels[tunnel_id] = cfg
    _save_all(tunnels)

    # Handle auth_mode change via REST API (no restart needed).
    # The relay stores auth_mode per tunnel and enforces it at the gate layer —
    # rules/PIN/Basic-Auth are preserved so re-enabling SSO restores the previous
    # allow-list without having to recreate it.
    if auth_mode_changed and cfg.subdomain and new_auth_mode is not None:
        try:
            await hle_api.set_auth_mode(cfg.subdomain, new_auth_mode)
        except Exception as exc:
            print(f"[hle] Failed to update auth_mode for {cfg.subdomain}: {exc}")

    # Determine if a process restart is needed
    # Auth-mode-only changes don't need restart — server enforces per-request
    _CONNECTION_FIELDS = {
        "service_url", "label", "verify_ssl", "websocket_enabled",
        "upstream_basic_auth", "forward_host", "response_timeout", "api_key",
        "webhook_path", "zone_domain",
    }
    needs_restart = bool(set(changed.keys()) & _CONNECTION_FIELDS)

    if needs_restart:
        cfg.stopped = False  # connection-affecting edit implies user wants it running
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

    # public_url is server-authoritative (set during /status sync).
    # For webhook tunnels, the server returns the base URL — append the path.
    public_url = cfg.public_url
    if public_url and cfg.webhook_path:
        public_url = f"{public_url}{cfg.webhook_path}"
    payload = cfg.model_dump()
    payload["public_url"] = public_url
    return TunnelStatus(
        **payload,
        state=state,
        error=error,
        pid=proc.pid if running else None,
    )
