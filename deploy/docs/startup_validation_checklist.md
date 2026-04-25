# Startup Validation Checklist

The service validates the following before entering the main loop:

## Automatic Checks (performed by `run_live_forward_service.py`)

- [x] Config builds successfully (`build_frozen_config()`)
- [x] Config fingerprint computed
- [x] Output directory exists or created
- [x] Logging configured (console + file)
- [x] Alert router built (Log + File sinks always; Telegram if credentials present)
- [x] Checkpoint scan completed (finds latest `state.json` if resuming)
- [x] Checkpoint config fingerprint verified (refuses mismatched configs)
- [x] Data feed constructed (file-watch dir created or replay data loaded)
- [x] HTF data loaded (or graceful fallback to no-HTF mode)
- [x] ForwardPaperRunner instantiated
- [x] Health file written (`"starting"`)
- [x] Startup alert sent

## Manual Pre-Deployment Checks

- [ ] `.env` file exists with correct `FEED_MODE`
- [ ] Historical data present in `/data/real/` (H1 + H4 Parquet/CSV)
- [ ] Telegram bot token and chat ID configured (optional but recommended)
- [ ] Docker build completed successfully
- [ ] Docker volumes created
- [ ] Sufficient disk space (>5 GB free)
- [ ] Outbound HTTPS connectivity (for Telegram API)

## Post-Startup Verification (within first hour)

- [ ] `docker compose logs forward-paper` shows "Starting forward paper session"
- [ ] `health.json` shows `"status": "starting"` or `"running"`
- [ ] If file-watch mode: drop a test CSV and verify it's processed
- [ ] Telegram startup alert received (if configured)
- [ ] No CRITICAL or EMERGENCY alerts in first hour
