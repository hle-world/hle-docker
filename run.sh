#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Privilege drop. Everything below runs as the unprivileged "hle" user
# (uid 10001). The container starts as root only so volumes created by older
# images (owned by root) can be handed over to that user first; once /data is
# writable by "hle" the script re-executes itself as that user.
#
# Started directly as a non-root user (docker run --user / compose `user:`),
# this block is skipped and /data must already be writable by that user.
# ---------------------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/logs
    # Only touch what is not already owned by hle: cheap on later starts.
    find /data -xdev \( ! -user hle -o ! -group hle \) -exec chown hle:hle {} + 2>/dev/null || true
    if setpriv --reuid=hle --regid=hle --init-groups test -w /data 2>/dev/null; then
        export HOME=/home/hle
        exec setpriv --reuid=hle --regid=hle --init-groups "$0" "$@"
    fi
    # e.g. an NFS export with root_squash, or a read-only/bind mount we cannot
    # chown: keep working as before rather than refusing to start.
    echo "[hle] WARNING: /data cannot be made writable for the unprivileged user (uid 10001); continuing as root."
    echo "[hle] Fix: chown -R 10001:10001 on the host directory, then restart."
elif [ ! -w "${HOME:-/}" ]; then
    # Started with an arbitrary --user: give hle-client somewhere writable.
    export HOME=/tmp
fi

# ---------------------------------------------------------------------------
# Agent mode — one container, many tunnels, all managed from the dashboard.
#
# Enabled by setting HLE_AGENT_TOKEN (or writing agent_token into
# /data/hle_config.json). Endpoints are declared at https://hle.world/dashboard;
# there is no local web UI to configure in this mode, so the container runs the
# agent in the foreground instead of the backend + UI.
# ---------------------------------------------------------------------------
AGENT_TOKEN="${HLE_AGENT_TOKEN}"
if [ -z "${AGENT_TOKEN}" ] && [ -f /data/hle_config.json ]; then
    AGENT_TOKEN=$(python3 -c "import json; print(json.load(open('/data/hle_config.json')).get('agent_token',''))" 2>/dev/null || echo "")
fi

if [ -n "${AGENT_TOKEN}" ]; then
    export HLE_AGENT_TOKEN="${AGENT_TOKEN}"
    export HLE_DATA_DIR="/data"
    mkdir -p /data/logs
    echo "[hle] Starting in agent mode — endpoints are managed from the dashboard."
    # Docker restarts the container on exit (restart: unless-stopped), so the
    # agent doesn't need its own supervisor.
    exec hle agent run
fi

# Read API key from config file if not set via environment variable
if [ -z "${HLE_API_KEY}" ]; then
    HLE_CONFIG="/data/hle_config.json"
    if [ -f "${HLE_CONFIG}" ]; then
        HLE_API_KEY=$(python3 -c "import json; print(json.load(open('${HLE_CONFIG}')).get('api_key',''))" 2>/dev/null || echo "")
        export HLE_API_KEY
    fi
fi

if [ -z "${HLE_API_KEY}" ]; then
    echo "[hle] No API key configured. Open the web UI to set one, or set HLE_API_KEY env var."
    echo "[hle] Tip: set HLE_AGENT_TOKEN instead to manage every tunnel from the dashboard."
fi

PORT="${HLE_PORT:-8099}"
# All interfaces inside the container so the published port works. The web UI
# and API require the login token (printed on first start, stored in
# /data/ui_token). To keep the port off the network entirely, publish it on
# loopback only: "127.0.0.1:8099:8099".
BIND_HOST="${HLE_BIND_HOST:-0.0.0.0}"
export HLE_DATA_DIR="/data"
mkdir -p /data/logs

echo "[hle] Starting HLE on ${BIND_HOST}:${PORT}..."
# --no-proxy-headers: the login rate limit keys on the socket peer address, so
# a client-supplied X-Forwarded-For must not be able to change it.
exec python3 -m uvicorn backend.main:app --host "${BIND_HOST}" --port "${PORT}" --app-dir /app --no-proxy-headers
