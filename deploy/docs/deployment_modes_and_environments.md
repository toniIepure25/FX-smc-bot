# Deployment Modes and Environments

## Modes

### 1. Replay Mode (`FEED_MODE=replay`)
- Replays historical H1 bars from `/data/real` as if they were live
- Useful for: testing the deployment stack, validating the service entry point, pre-VPS verification
- Exits when the replay data is exhausted
- Not suitable for the 4-week trial (finite data)

### 2. File-Watch Mode (`FEED_MODE=file_watch`)
- Watches `/data/live` for new CSV files containing H1 bars
- Suitable for: the 4-week VPS trial, integration with any data source that exports CSVs
- Runs indefinitely, processing bars as they arrive
- The operator or an external script drops CSVs into the watch directory

### CSV Format Expected

```csv
timestamp,open,high,low,close,volume,spread
2026-04-10T20:00:00,148.500,148.750,148.200,148.650,1500,0.015
```

## Environments

### Local Development
- Run directly: `python scripts/run_live_forward_service.py --mode replay`
- No Docker required
- Output to `./forward_runs/`

### VPS Paper Trading (Free Trial)
- Docker Compose with `docker compose up -d forward-paper`
- Persistent volumes for state and data
- Cron-based reporting
- Telegram alerts for remote monitoring

### VPS Paper Trading (Paid/Long-term)
- Same stack as free trial
- Add: automated data feed script (broker API polling)
- Add: log rotation and monitoring integrations
- Add: backup script for state/journal snapshots

### Broker-Demo Integration (Future)
- Replace `PaperBroker` with real `BrokerAdapter` in `demo` mode
- Add `BrokerGateway` with `ExecutionMode.DEMO`
- Data feed transitions to live broker API
- Same monitoring, alerting, and reporting stack
