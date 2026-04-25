# Forward Service Runtime Spec

## Entry Point

`scripts/run_live_forward_service.py` — production-grade CLI with environment variable support for Docker deployment.

## Arguments / Environment Variables

| CLI Flag | Env Var | Default | Description |
|----------|---------|---------|-------------|
| `--data-dir` | `DATA_DIR` | `data/real` | Historical data for HTF context |
| `--watch-dir` | `WATCH_DIR` | `data/live` | Directory for incoming CSV bar files |
| `--output-dir` | `OUTPUT_DIR` | `forward_runs` | State, journals, reports output |
| `--mode` | `FEED_MODE` | `file_watch` | `file_watch` or `replay` |
| `--auto-resume` | `AUTO_RESUME` | `true` | Auto-resume from latest checkpoint |
| — | `TELEGRAM_BOT_TOKEN` | _(empty)_ | Telegram bot token for alerts |
| — | `TELEGRAM_CHAT_ID` | _(empty)_ | Telegram chat ID for alerts |

## Process Model

- Single-process, single-threaded Python
- Signal handlers for SIGINT/SIGTERM (graceful shutdown via tini)
- No daemon fork — Docker manages the process lifecycle
- `PYTHONUNBUFFERED=1` for real-time log output

## Resource Profile

| Resource | Typical Usage |
|----------|--------------|
| CPU | < 5% (spikes during structure computation) |
| RAM | 200-400 MB (numpy arrays for 2000-bar buffer) |
| Disk I/O | Negligible (periodic JSON writes) |
| Network | Minimal (Telegram API calls only) |
