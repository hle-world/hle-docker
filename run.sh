#!/bin/bash
set -e

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
fi

PORT="${HLE_PORT:-8099}"
mkdir -p /data/logs

echo "[hle] Starting HLE on port ${PORT}..."
exec python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" --app-dir /app
