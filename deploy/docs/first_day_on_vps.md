# First Day on VPS

## Hour 0: Deploy

1. Follow `vps_setup_guide.md` to install and start the service
2. Confirm Docker container is running: `docker compose ps`
3. Confirm Telegram startup alert received
4. Confirm health file: `cat forward_runs/health.json`

## Hour 0-1: First Bar

5. Drop the first CSV file into the live feed directory:
   ```bash
   docker cp my_bars.csv fx-forward-paper:/data/live/
   ```
6. Check logs for bar processing: `docker compose logs --tail 10 forward-paper`
7. Look for "bar accepted" and "pipeline_diagnostic" messages

## Hour 1-4: Signal Verification

8. Check that candidates are being evaluated (look for `pipeline_diagnostic` in journal)
9. If `htf_bias = null` persists, verify HTF data was loaded correctly
10. Watch for first trade signal in logs

## Hour 4-12: First Trading Session

11. If London/NY session bars are flowing, expect 1-3 trade signals
12. Check for `log_fill` entries in the journal
13. Verify daily review artifact is being created

## End of Day 1: Verification

14. Run a health report:
    ```bash
    docker compose run --rm daily-report --type health
    ```
15. Check Telegram for the daily report at 22:00 UTC
16. Verify:
    - [ ] Bars processed > 0
    - [ ] No EMERGENCY alerts
    - [ ] Feed health showing bars received
    - [ ] Health file status is not "crashed"

## Troubleshooting

| Problem | Check | Fix |
|---------|-------|-----|
| No bars processing | `docker compose logs forward-paper` | Verify CSV files in `/data/live` |
| Container restarting | `docker compose logs forward-paper` | Check for import errors or missing data |
| No Telegram alerts | `.env` file | Verify token and chat ID |
| "Config mismatch" alert | State from different config | Remove old state files, restart |
| "No HTF data" warning | Missing H4 data | Upload H4 Parquet to `/data/real` |
