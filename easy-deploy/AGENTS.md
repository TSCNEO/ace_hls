# AceHLS Easy Deploy — AI Agent Operational Guide

This document provides instructions for autonomous AI coding and DevOps agents (Claude, Codex, Hermes, GPT, OpenCode) deploying AceHLS via Docker Compose.

## Project Summary
AceHLS (`tscneo/ace-hls-viewer`) is a lightweight web player and HLS streaming proxy for AceStream channels. It normalizes playlists and MylinkPaste DNS-over-HTTPS sources, providing instant browser playback and IPTV exports via an AceStream Orchestrator engine.

## Directory Structure & Variants

```
easy-deploy/
├── orchestrator-local/    # All-in-one: AceHLS + Local AceStream Orchestrator engine (single host)
│   ├── compose.yml
│   └── .env.example
├── orchestrator-remote/   # AceHLS only: connects to an existing Orchestrator on another host/IP
│   ├── compose.yml
│   └── .env.example
├── README.md              # Human-oriented quickstart
└── AGENTS.md              # This file (AI agent operational instructions)
```

## AI Agent Decision Matrix

| User Environment / Request | Variant to Use | Notes & Requirements |
|---|---|---|
| Single host, fresh install, wants all-in-one | `orchestrator-local` | Mounts `/var/run/docker.sock` for dynamic engine spawning. |
| Existing Orchestrator / Gluetun / VPN host | `orchestrator-remote` | Requires `ORCHESTRATOR_HOST` (IP) and `ORCHESTRATOR_API_TOKEN`. |

## Deployment Procedures

### Variant A: Orchestrator Local (All-in-One)

```bash
cd orchestrator-local
cp .env.example .env

# Generate a random 32-char token
TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
sed -i "s/cambia-este-token-compartido/${TOKEN}/" .env

# Pull and start services
docker compose pull
docker compose up -d --remove-orphans
```

- **AceHLS Web UI:** `http://<HOST_IP>:8088`
- **Orchestrator Panel:** `http://<HOST_IP>:8000/panel`

### Variant B: Orchestrator Remote (Connect to existing backend)

```bash
cd orchestrator-remote
cp .env.example .env

# Set the IP and secret token of the remote orchestrator host
sed -i "s/ORCHESTRATOR_HOST=192.168.1.50/ORCHESTRATOR_HOST=<TARGET_IP>/" .env
sed -i "s/ORCHESTRATOR_API_TOKEN=cambia-este-token-compartido/ORCHESTRATOR_API_TOKEN=<TARGET_TOKEN>/" .env

# Pull and start AceHLS
docker compose pull
docker compose up -d --remove-orphans
```

- **AceHLS Web UI:** `http://<HOST_IP>:8088`
- **Direct Stream Port:** `8000` on the remote host must be reachable from LAN players.

## Verification & Health Check Sequence

Execute these commands to verify that the deployment is operating correctly:

```bash
# 1. Container status
docker compose ps

# 2. Version endpoint
curl -s --fail http://127.0.0.1:8088/api/version
# Output: {"transcoding":true,"version":"v2.9.0"}

# 3. Health check
curl -s --fail http://127.0.0.1:8088/health
# Output: {"status":"healthy"}

# 4. Orchestrator communication check
curl -s --fail http://127.0.0.1:8088/api/orchestrator/config
```

## Critical Agent Invariants

1. **Never use `build:` in Easy Deploy:** Easy Deploy must exclusively pull official prebuilt images (`tscneo/ace-hls-viewer:2.9.0`).
2. **Never expose ports directly to WAN:** AceStream and AceHLS are intended for private LANs or VPNs (WireGuard / Tailscale).
3. **Do not destroy data volumes:** Persistent channels and settings reside in `ace_hls_data`. Never run `docker compose down -v` unless the user explicitly requested data destruction.
4. **Remote variant isolation:** `orchestrator-remote` must never mount the Docker socket.
