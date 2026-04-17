# HLE Docker

Run [HomeLab Everywhere](https://hle.world) tunnels on any Docker host — Synology, Unraid, bare metal, and more.

Two variants available:

| Tag | Description |
|-----|-------------|
| `latest` | Full image with web UI for managing tunnels |
| `headless` | API + CLI only — no web UI, lighter build |

## Quick Start

### With Web UI

```bash
docker run -d \
  --name hle \
  -p 8099:8099 \
  -v hle-data:/data \
  ghcr.io/hle-world/hle-docker:latest
```

Open `http://your-host:8099` and enter your API key.

### Headless (no UI)

```bash
docker run -d \
  --name hle \
  -p 8099:8099 \
  -v hle-data:/data \
  ghcr.io/hle-world/hle-docker:headless
```

Manage tunnels via CLI or API:

```bash
# Set API key
docker exec hle hle config set-key YOUR_API_KEY

# Start a tunnel
docker exec hle hle expose --service http://host.docker.internal:8123 --label ha

# Forward webhooks from external services
docker exec hle hle webhook --path /hook/github --forward-to http://host.docker.internal:3000 --label github-hook

# List tunnels via API
curl http://localhost:8099/api/tunnels
```

The web UI supports creating both regular tunnels and webhook tunnels for receiving callbacks from GitHub, Stripe, and other external services.

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

For headless, replace the image tag with `ghcr.io/hle-world/hle-docker:headless`, or use the headless profile:

```bash
docker compose --profile headless up -d
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HLE_API_KEY` | _(empty)_ | Your HLE API key. Can also be set via the web UI or CLI. |
| `HLE_PORT` | `8099` | Port the server listens on inside the container. |

## Data Persistence

All configuration and tunnel state is stored in `/data`. Mount a volume to persist across container restarts.

## Getting an API Key

1. Create a free account at [hle.world/register](https://hle.world/register)
2. Copy your API key from [hle.world/dashboard](https://hle.world/dashboard)

## Building from Source

```bash
git clone https://github.com/hle-world/hle-docker.git
cd hle-docker

# Full image (with web UI)
docker build -t hle-docker:local .

# Headless (no UI)
docker build -f Dockerfile.headless -t hle-docker:headless .
```

## Documentation

Full documentation: [hle.world/docs/docker](https://hle.world/docs/docker)
