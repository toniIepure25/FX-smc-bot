# Operator Playbook

## Daily Workflow (5 minutes)

1. **Check Telegram** for daily report (arrives at 22:00 UTC)
2. Review key metrics: trades, PnL, equity, drawdown
3. Note any WARNING/CRITICAL alerts
4. If anything unusual: SSH into VPS and check logs
5. Done

## Weekly Workflow (15 minutes)

1. **Check Telegram** for weekly report (arrives Saturday 10:00 UTC)
2. Compare metrics against weekly checkpoint expectations
3. Fill in the trial manifest weekly checkpoint
4. Make continue/pause/abort decision
5. If continuing: no action needed
6. If pausing: `docker compose stop forward-paper`

## Common Commands

```bash
# Check service status
docker compose ps

# View live logs
docker compose logs -f forward-paper

# View recent logs
docker compose logs --tail 50 forward-paper

# Check health
cat forward_runs/health.json

# Restart service
docker compose restart forward-paper

# Stop service
docker compose stop forward-paper

# Start service
docker compose up -d forward-paper

# Generate report manually
docker compose run --rm daily-report --type health

# View latest state
cat forward_runs/fwd_*/state.json | python3 -m json.tool

# SSH tunnel for remote access
ssh -L 8080:localhost:8080 user@vps-ip
```

## Data Feed: Dropping CSV Files

For the file-watch mode, the operator (or a script) drops H1 bar CSV files into the watch directory:

```bash
# On the VPS
docker compose exec forward-paper ls /data/live/

# Copy a CSV file into the watch directory
docker cp bars_2026041020.csv fx-forward-paper:/data/live/
```

CSV format:
```
timestamp,open,high,low,close,volume,spread
2026-04-10T20:00:00,148.500,148.750,148.200,148.650,1500,0.015
```

Bars must be sorted by timestamp. One file can contain multiple bars.
