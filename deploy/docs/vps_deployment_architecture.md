# VPS Deployment Architecture

## Overview

The forward paper trading stack runs on a single Linux VPS as a Docker Compose application with three logical layers:

```
┌───────────────────────────────────────────────────────┐
│                     VPS (Linux)                       │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Docker Compose                                 │  │
│  │                                                 │  │
│  │  ┌──────────────────┐   ┌───────────────────┐   │  │
│  │  │  forward-paper   │   │  Report generators │   │  │
│  │  │  (always-on)     │   │  (cron-triggered)  │   │  │
│  │  │                  │   │  - daily-report    │   │  │
│  │  │  ForwardPaper    │   │  - weekly-report   │   │  │
│  │  │  Runner          │   └───────────────────┘   │  │
│  │  │  + AlertRouter   │                           │  │
│  │  │  + FeedHealth    │                           │  │
│  │  │  + DriftDetect   │                           │  │
│  │  └────────┬─────────┘                           │  │
│  │           │                                     │  │
│  │  ┌────────┴─────────────────────────────────┐   │  │
│  │  │           Persistent Volumes              │   │  │
│  │  │  /data/real   (H1/H4 historical, RO)     │   │  │
│  │  │  /data/live   (incoming CSV bar drops)    │   │  │
│  │  │  forward_runs/ (state, journals, reports) │   │  │
│  │  └──────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  ┌────────────┐   ┌────────────┐                      │
│  │  Cron      │   │  Telegram  │ ← alerts & reports   │
│  │  (reports) │   │  Bot API   │                      │
│  └────────────┘   └────────────┘                      │
└───────────────────────────────────────────────────────┘
```

## Components

### 1. Forward Paper Service (`forward-paper`)
- **Runtime**: Python 3.12 in Docker container
- **Process**: `scripts/run_live_forward_service.py`
- **Signal handling**: SIGINT/SIGTERM for graceful shutdown (via tini)
- **Restart policy**: `unless-stopped` — auto-restarts on crash or reboot
- **State**: Checkpoints every 50 bars to `forward_runs/<run_id>/state.json`
- **Resume**: On restart, auto-locates latest valid checkpoint and resumes

### 2. Data Layer
- **Historical data** (`/data/real`): read-only H1 and H4 Parquet/CSV used for HTF context and replay testing
- **Live feed** (`/data/live`): writable directory watched by `FileWatchFeedProvider` for new CSV bar files
- **Run artifacts** (`forward_runs/`): journals, checkpoints, reviews, alerts, reports

### 3. Monitoring & Alerting
- **Telegram**: `TelegramAlertSink` sends WARNING+ alerts and scheduled reports
- **File alerts**: `alerts.jsonl` for audit-quality persistence
- **Health file**: `health.json` updated atomically for Docker HEALTHCHECK
- **Structured logs**: `service.log` in the run directory

### 4. Reporting (cron-triggered)
- **Daily report**: Generated at 22:00 UTC weekdays, sent via Telegram
- **Weekly report**: Generated Saturday 10:00 UTC, sent via Telegram
- Both are one-shot Docker containers reading from the shared `forward_runs/` volume

## VPS Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 512 MB | 1 GB |
| Disk | 5 GB | 10 GB |
| OS | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 |
| Network | Outbound HTTPS (Telegram API) | Same |

A free-trial VPS from providers like Oracle Cloud (always-free tier), Hetzner, DigitalOcean, or Vultr meets these requirements.
