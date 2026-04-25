# Component Interaction Diagram

## Runtime Interactions

```
                ┌──────────────────────────────────────────────┐
                │          run_live_forward_service.py          │
                │                                              │
                │  startup_validation()                        │
                │    ├─ build_frozen_config()                  │
                │    ├─ config_fingerprint() verification      │
                │    ├─ _find_latest_checkpoint() for resume   │
                │    ├─ _build_alert_router()                  │
                │    │    ├─ LogAlertSink                      │
                │    │    ├─ FileAlertSink                     │
                │    │    └─ TelegramAlertSink (if env set)    │
                │    ├─ build_feed() → FileWatch or Replay     │
                │    ├─ load_htf_data() → ReplayFeedProvider   │
                │    └─ _write_health("starting")              │
                │                                              │
                │  ForwardPaperRunner.start()                  │
                │    ├─ _restore(checkpoint) if resuming       │
                │    ├─ _run_loop()                            │
                │    │    ├─ poll feed                         │
                │    │    ├─ _sync_htf_to(bar.timestamp)       │
                │    │    ├─ _process_bar()                    │
                │    │    │    ├─ risk state update             │
                │    │    │    ├─ process fills                 │
                │    │    │    ├─ build structure snapshot      │
                │    │    │    ├─ generate candidates           │
                │    │    │    ├─ approve + select              │
                │    │    │    ├─ submit orders                 │
                │    │    │    └─ log pipeline_diagnostic       │
                │    │    └─ _save_checkpoint() every 50 bars  │
                │    └─ stop() → final checkpoint + summary    │
                │                                              │
                │  on crash:                                   │
                │    ├─ _write_health("crashed")               │
                │    └─ emit EMERGENCY alert via Telegram      │
                └──────────────────────────────────────────────┘

                ┌──────────────────────────────────────────────┐
                │          generate_report.py (cron)           │
                │                                              │
                │  reads: forward_runs/<run>/session_summary   │
                │  reads: forward_runs/<run>/reviews/day_*.json│
                │  reads: forward_runs/alerts.jsonl            │
                │  reads: forward_runs/health.json             │
                │  writes: forward_runs/reports/<type>_<ts>.md │
                │  sends: Telegram report message              │
                └──────────────────────────────────────────────┘
```

## Volume Mapping

| Container Path | Host/Volume | Access | Content |
|---------------|-------------|--------|---------|
| `/data/real` | `./data/real` | read-only | Historical H1/H4 Parquet/CSV |
| `/data/live` | `live-feed` volume | read-write | Incoming H1 CSV bar drops |
| `/app/forward_runs` | `forward-runs` volume | read-write | State, journals, reviews, reports |
