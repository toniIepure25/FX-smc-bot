# Forward Paper Stack Overview

## Purpose

Run the frozen `bos_only_usdjpy` strategy in paper-trading mode on a VPS for 4 weeks, proving operational stability and live-data performance before advancing to broker-demo integration.

## Stack Components

| Component | Implementation | Status |
|-----------|---------------|--------|
| Strategy engine | `ForwardPaperRunner` (repaired) | Ready |
| LTF feed | `FileWatchFeedProvider` (H1 CSVs) | Ready |
| HTF feed | `ReplayFeedProvider` pre-loaded from historical H4 | Ready |
| Paper broker | `PaperBroker` (simulated fills) | Ready |
| Risk management | `DrawdownTracker` + constraints + `DrawdownAwareSizing` | Ready |
| State persistence | `LiveState` JSON checkpoints | Ready |
| Feed monitoring | `FeedHealthMonitor` | Ready |
| Drift detection | `DriftDetector` with baseline profile | Ready |
| Alert routing | `AlertRouter` → Log + File + Telegram | Ready |
| Service entry point | `scripts/run_live_forward_service.py` | New |
| Containerization | `Dockerfile` + `docker-compose.yml` | New |
| Automated reports | `scripts/generate_report.py` + cron | New |
| Telegram integration | `TelegramAlertSink` | New |
| VPS setup | `deploy/setup-vps.sh` | New |

## Data Flow

```
CSV bar files → FileWatchFeedProvider → ForwardPaperRunner
                                              │
                    ┌─────────────────────────┼────────────────────┐
                    ▼                         ▼                    ▼
              FeedHealthMonitor        _process_bar            AlertRouter
                    │              ┌──────────────────┐           │
                    ▼              │ build_structure   │     ┌────┴────┐
              feed_health.json     │ generate_cands    │     │Telegram │
                                   │ approve/select    │     │File     │
                                   │ execute via       │     │Log      │
                                   │ PaperBroker       │     └─────────┘
                                   └──────────────────┘
                                          │
                                     ┌────┴────┐
                                     │Checkpoint│
                                     │Journal   │
                                     │Reviews   │
                                     └─────────┘
```

## Configuration Fingerprint

All sessions use the frozen `prop_v2_hardened` config:
- `base_risk_per_trade = 0.003`
- `max_daily_drawdown = 0.02`
- `circuit_breaker_threshold = 0.10`
- `enabled_families = ["bos_continuation"]`
- Config fingerprint verified on every startup and resume
