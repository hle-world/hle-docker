# HLE Docker

Run [Home Lab Everywhere](https://hle.world) tunnels on any Docker host — Synology, Unraid, bare metal, and more.

Includes a web UI for managing tunnels, access rules, PIN protection, basic auth, and share links.

## Quick Start

```bash
docker run -d \
  --name hle \
  -p 8099:8099 \
  -v hle-data:/data \
  ghcr.io/hle-world/hle-docker:latest
```

Open `http://your-host:8099` and enter your API key.

## Docker Compose

```yaml
services:
  hle:
    image: ghcr.io/hle-world/hle-docker:latest
    container_name: hle
    restart: unless-stopped
    ports:
      - "8099:8099"
    volumes:
      - hle-data:/data
    environment:
      - HLE_API_KEY=           # Optional: set here or via web UI

volumes:
  hle-data:
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HLE_API_KEY` | _(empty)_ | Your HLE API key. Can also be set via the web UI. |
| `HLE_PORT` | `8099` | Port the web UI listens on inside the container. |

## Data Persistence

All configuration and tunnel state is stored in `/data`. Mount a volume to persist across container restarts.

## Getting an API Key

1. Create a free account at [hle.world/register](https://hle.world/register)
2. Copy your API key from [hle.world/dashboard](https://hle.world/dashboard)
