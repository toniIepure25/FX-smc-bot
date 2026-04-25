# Recovery and Resume Protocol

## Automatic Recovery Flow

When the service restarts (crash, reboot, `docker compose restart`):

```
1. Service starts
2. build_frozen_config() → same config every time
3. _find_latest_checkpoint(output_dir)
   └─ scans forward_runs/fwd_*/state.json by modification time
4. If checkpoint found:
   a. LiveState.load(checkpoint_path)
   b. verify_config(cfg) → compare fingerprints
   c. If fingerprint matches:
      └─ resume_from=checkpoint_path passed to runner.start()
   d. If fingerprint mismatch:
      └─ CRITICAL alert, refuse resume, start fresh
5. If no checkpoint:
   └─ Start fresh session
6. ForwardPaperRunner.start(resume_from=...)
   a. _restore(checkpoint) → rehydrate DrawdownTracker, bar count, etc.
   b. _run_loop() begins from last_bar_timestamp
```

## Crash Scenarios

### Docker container crash
- Docker `restart: unless-stopped` auto-restarts the container
- On restart, `AUTO_RESUME=true` triggers checkpoint recovery
- Up to 50 bars of history may be reprocessed (harmless in paper mode)

### VPS reboot
- Docker daemon starts automatically (`systemctl enable docker`)
- Container restart policy kicks in
- Same recovery flow as container crash

### Corrupted state file
- `LiveState.load()` raises `ValueError` or `json.JSONDecodeError`
- The service catches the exception and starts a fresh session
- CRITICAL alert sent to Telegram
- The corrupted file remains on disk for post-mortem analysis

### Network partition (Telegram unreachable)
- Alerts fail silently (exception caught in `TelegramAlertSink.emit()`)
- Local file alerts and logs are unaffected
- Service continues running normally

### Data feed gap (no new CSVs)
- `FileWatchFeedProvider.poll_new_bars()` returns empty
- The main loop continues polling (no crash)
- `FeedHealthMonitor` detects staleness after configurable threshold
- Alert fired if gap exceeds expected bar interval

## Manual Recovery

If automatic recovery fails:

1. Check logs: `docker compose logs forward-paper`
2. Inspect state: `docker compose exec forward-paper cat /app/forward_runs/health.json`
3. If state is corrupted, remove the bad checkpoint and restart:
   ```bash
   docker compose stop forward-paper
   # identify and remove corrupted state file
   docker compose start forward-paper
   ```
4. The service will start a fresh session
