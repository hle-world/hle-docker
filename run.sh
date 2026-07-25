#!/bin/bash
set -e

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
export HLE_DATA_DIR="/data"
mkdir -p /data/logs

echo "[hle] Starting HLE on port ${PORT}..."
exec python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" --app-dir /app
