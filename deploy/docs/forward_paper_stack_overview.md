# Forward Paper Stack Overview

> **Legacy, unvalidated stack.** It documents the earlier `bos_only_usdjpy`
> deployment attempt and is not evidence of a current edge. The current compose
> service uses a Yahoo-backed `live` paper feed (or `replay`); it does not place
> broker orders.

## Purpose

Run the frozen `bos_only_usdjpy` strategy in paper mode on a VPS for operational
observation. The programme is closed; use this stack only to study its behaviour
or to reproduce the legacy service.

## Stack Components

| Component | Implementation | Status |
|-----------|---------------|--------|
| Strategy engine | `ForwardPaperRunner` | Legacy, unvalidated |
| LTF feed (live) | `YahooFeedProvider` (H1) | Legacy, unvalidated |
| HTF feed (live) | `YahooFeedProvider` (H4) | Legacy, unvalidated |
| LTF/HTF feed (replay) | `ReplayFeedProvider` from local data | Legacy, unvalidated |
| Paper broker | `PaperBroker` (simulated fills) | Legacy, unvalidated |
| Risk management | `DrawdownTracker` + constraints + `DrawdownAwareSizing` | Legacy, unvalidated |
| State persistence | `LiveState` JSON checkpoints | Legacy, unvalidated |
| Feed monitoring | `FeedHealthMonitor` | Legacy, unvalidated |
| Drift detection | `DriftDetector` with baseline profile | Legacy, unvalidated |
| Alert routing | `AlertRouter` → Log + File + Telegram | Legacy, unvalidated |
| Service entry point | `scripts/run_live_forward_service.py` | Legacy, unvalidated |
| Containerization | `Dockerfile` + `docker-compose.yml` | Non-root image |
| Automated reports | `scripts/generate_report.py` + cron | Legacy, unvalidated |
| Telegram integration | `TelegramAlertSink` | Optional |
| VPS setup | `deploy/setup-vps.sh` | Historical |

## Data Flow

```
Live: Yahoo H1/H4  ─┐
                    ├─→ ForwardPaperRunner → PaperBroker → journal/checkpoint
Replay: local bars ─┘         │
                              ├─ FeedHealthMonitor → feed_health.json
                              └─ AlertRouter → Telegram/File/Log
```

## Configuration Fingerprint

All sessions use the frozen `prop_v2_hardened` config:
- `base_risk_per_trade = 0.003`
- `max_daily_drawdown = 0.02`
- `circuit_breaker_threshold = 0.10`
- `enabled_families = ["bos_continuation"]`
- Config fingerprint verified on every startup and resume
