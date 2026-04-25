# State Persistence Model

## What Is Persisted

| Data | Location | Format | Frequency |
|------|----------|--------|-----------|
| Session state (equity, positions, DD tracker) | `<run_id>/state.json` | JSON | Every 50 bars + on stop |
| Event journal | `<run_id>/journal.jsonl` | JSONL | Every event (fill, signal, state change) |
| Daily reviews | `<run_id>/reviews/day_XXX.json` | JSON | Every day boundary |
| Session summary | `<run_id>/session_summary.json` | JSON | On graceful stop |
| Alerts | `alerts.jsonl` | JSONL | Every alert event |
| Health status | `health.json` | JSON | On start, stop, crash |
| Reports | `reports/<type>_<ts>.md` | Markdown | Daily/weekly via cron |

## LiveState Fields

The checkpoint (`state.json`) captures:

```
state_version, run_id, timestamp, operational_state,
equity, cash, bars_processed, trades_today,
consecutive_losses, open_positions, pending_orders,
peak_equity, initial_equity, day_start_equity,
week_start_equity, current_day, current_week,
cb_fire_count, cb_cooldown_until, circuit_breaker_fired,
config_fingerprint, mode, last_bar_timestamp
```

This is sufficient to fully reconstruct `DrawdownTracker` state and resume bar processing from the exact point of interruption.

## Checkpoint Lifecycle

1. **Periodic**: Every 50 bars during `_run_loop`
2. **On pause**: When `runner.pause()` is called
3. **On stop**: Final checkpoint in `runner.stop()`
4. **On crash**: The last periodic checkpoint serves as the recovery point (up to 50 bars may need reprocessing)

## State File Atomicity

The `LiveState.save()` method writes directly to `state.json`. For production robustness, `_write_health()` in the service uses atomic write-to-temp-then-rename. The checkpoint path follows the same pattern as the runner's internal persistence.
