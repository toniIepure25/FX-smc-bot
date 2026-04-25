# Crash and Recovery Playbook

## Scenario 1: Container Crash (Auto-Recovery)

**Symptoms**: EMERGENCY alert on Telegram, container restarts automatically.

**Action**:
1. Check if the service recovered: `docker compose ps`
2. Check logs for the crash reason: `docker compose logs --tail 50 forward-paper`
3. Verify checkpoint resume: look for "Resuming from checkpoint" in logs
4. If recovered: monitor for 1 hour, then continue normal operation
5. If crash-looping: `docker compose stop forward-paper`, investigate, fix, restart

## Scenario 2: VPS Reboot

**Symptoms**: All services go down, Docker auto-restarts on boot.

**Action**:
1. Wait 2-5 minutes for Docker to restart the container
2. Verify: `docker compose ps`
3. Check resume: `docker compose logs --tail 20 forward-paper`
4. If not auto-restarting: `docker compose up -d forward-paper`

## Scenario 3: Corrupted State

**Symptoms**: "Failed to validate checkpoint" in logs, fresh session starts.

**Action**:
1. Check the old state file: `cat forward_runs/fwd_*/state.json`
2. If the data is recoverable, manually fix the JSON and restart
3. If not: accept the fresh start (some history lost, but not critical for paper)
4. Document as an incident

## Scenario 4: Disk Full

**Symptoms**: Write errors in logs, container may crash.

**Action**:
1. Check disk: `df -h`
2. Clean old logs: `docker system prune -f`
3. Remove old run artifacts: `rm -rf forward_runs/fwd_OLD_*/`
4. Restart: `docker compose restart forward-paper`

## Scenario 5: Network Partition (Telegram Down)

**Symptoms**: No Telegram alerts, but service is running fine.

**Action**:
1. Verify service is running: `docker compose ps`
2. Check logs: `docker compose logs --tail 10 forward-paper`
3. Telegram alerts will resume when connectivity returns
4. No action needed for the trading service itself

## Scenario 6: Data Feed Stops

**Symptoms**: No new bars processed, signal drought alert.

**Action**:
1. Check if CSV files are being dropped: `ls -la /data/live/` (inside container)
2. Resume data feed
3. The service will automatically pick up new files when they appear
4. Extended gaps are logged by FeedHealthMonitor

## General Recovery Checklist

- [ ] Container is running (`docker compose ps`)
- [ ] Health file shows non-crashed status
- [ ] Latest checkpoint is recent
- [ ] Logs show normal operation
- [ ] Telegram connectivity restored
- [ ] Data feed is flowing
