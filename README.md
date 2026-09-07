# HLE Docker

Run [HomeLab Everywhere](https://hle.world) tunnels on any Docker host — Synology, Unraid, bare metal, and more.

Two variants available:

| Tag | Description |
|-----|-------------|
| `latest` | Full image with web UI for managing tunnels |
| `headless` | API + CLI only — no web UI, lighter build |

Either image can run in **agent mode**, where every tunnel is declared in the
hle.world dashboard instead of configured locally. See below.

## Quick Start

### Agent mode (recommended)

One container serves every endpoint you declare at
[hle.world/dashboard](https://hle.world/dashboard). Add or remove endpoints
there and the container converges within seconds — no restart, no local config,
no published ports (the agent dials out).

1. In the dashboard, go to **Agents → New Agent** and copy the credential it shows.
   It is shown only once.
2. Start the container:

```bash
docker run -d \
  --name hle-agent \
  --restart unless-stopped \
  -e HLE_AGENT_TOKEN=<credential> \
  --add-host host.docker.internal:host-gateway \
  -v hle-agent-data:/data \
  ghcr.io/hle-world/hle-docker:headless
```

3. Add endpoints in the dashboard, pointing at your local services — e.g.
   `http://host.docker.internal:8123` for Home Assistant on the Docker host, or
   a container name if you attach this container to the same network.

Agent mode requires the agent feature to be enabled on your account. If the
**Agents** section isn't in your dashboard, use API-key mode below.

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

For agent mode, use the `agent` profile in the bundled `docker-compose.yml`:

```bash
HLE_AGENT_TOKEN=<credential> docker compose --profile agent up -d
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HLE_AGENT_TOKEN` | _(empty)_ | Agent enrollment credential, copied from the dashboard. When set, the container runs in agent mode and every other tunnel setting is ignored — endpoints come from the dashboard. |
| `HLE_API_KEY` | _(empty)_ | Your HLE API key. Can also be set via the web UI or CLI. |
| `HLE_PORT` | `8099` | Port the server listens on inside the container. |

`HLE_AGENT_TOKEN` takes precedence over `HLE_API_KEY`. The token can also be
stored as `agent_token` in `/data/hle_config.json`.

## Data Persistence

All configuration and tunnel state is stored in `/data`. Mount a volume to persist across container restarts.

## Getting an API Key

1. Create a free account at [hle.world/register](https://hle.world/register)
2. Copy your API key from [hle.world/dashboard](https://hle.world/dashboard)

## Getting an Agent Token

1. Create a free account at [hle.world/register](https://hle.world/register)
2. Go to **Agents → New Agent** in the [dashboard](https://hle.world/dashboard)
3. Copy the credential — it is shown once and cannot be retrieved later

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
