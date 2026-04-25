# Automated Reporting Specification

## Report Types

### Daily Report (`generate_report.py --type daily`)
**Schedule**: 22:00 UTC, Monday–Friday (cron)
**Content**:
- Run ID and bars processed
- Cumulative trades, win rate, PnL, equity
- Peak equity and trailing drawdown
- Max loss streak, CB fires, signal drought status
- Drift detection summary (flagged metrics)
- 24-hour alert count (warnings+)
- Latest daily review artifact summary
- Feed health status

### Weekly Report (`generate_report.py --type weekly`)
**Schedule**: Saturday 10:00 UTC (cron)
**Content**:
- Everything in daily report, plus:
- Candidate review pipeline breakdown (accepted/rejected, rejection reasons)
- 7-day alert histogram by severity
- Daily summary table (last 7 days)
- Feed health details (bars received, completeness, gaps)

### Health Report (`generate_report.py --type health`)
**Schedule**: On-demand
**Content**:
- Current health status
- Last bar timestamp
- Equity and trade count
- Feed completeness

## Report Storage

Reports are saved to `forward_runs/reports/<type>_<timestamp>.md` for retention and audit.

## Telegram Delivery

All reports are sent to the configured Telegram chat via `TelegramAlertSink.send_report()`. Messages are capped at 4096 characters (Telegram API limit) and sent with notifications silenced.

## Report Data Sources

| Data | Source file |
|------|------------|
| Session metrics | `<run_id>/session_summary.json` |
| Daily reviews | `<run_id>/reviews/day_*.json` |
| Alerts | `alerts.jsonl` |
| Health status | `health.json` |
