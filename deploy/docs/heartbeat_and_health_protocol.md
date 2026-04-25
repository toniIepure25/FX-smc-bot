# Heartbeat and Health Protocol

## Health File

Path: `forward_runs/health.json`

Updated on service state transitions:
- `"starting"` — service is initializing
- `"running"` — main loop is active (future: updated periodically)
- `"stopped"` — graceful shutdown completed
- `"crashed"` — unhandled exception occurred

### Format
```json
{
  "status": "starting",
  "timestamp": "2026-04-20T10:00:00.000000",
  "run_id": "fwd_20260420_100000_abc123",
  "mode": "file_watch"
}
```

## Docker HEALTHCHECK

Configured in `Dockerfile`:
- **Interval**: 60 seconds
- **Timeout**: 10 seconds
- **Retries**: 3
- **Check**: Reads `health.json` and verifies `status` is a known state

If the health check fails 3 consecutive times, Docker marks the container as unhealthy.

## Remote Health Checking

### Via Docker
```bash
docker inspect --format='{{.State.Health.Status}}' fx-forward-paper
```

### Via SSH
```bash
cat /var/lib/docker/volumes/fx-smc-bot_forward-runs/_data/health.json
```

### Via Telegram
Send the health report manually:
```bash
docker compose run --rm daily-report --type health
```

## Staleness Detection

The `FeedHealthMonitor` tracks:
- Time since last bar received
- Gap detection (expected vs actual bar intervals)
- Completeness percentage

If no bars arrive for 6+ hours during expected trading hours, the monitor fires a WARNING alert.

## Liveness vs Readiness

| Check | Type | What it means |
|-------|------|---------------|
| health.json exists and is recent | Liveness | Process is running and writing state |
| health.json status = "running" | Readiness | Main loop is active and processing |
| Last bar timestamp < 2 hours old | Feed health | Data pipeline is delivering bars |
