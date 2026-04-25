# Escalation Playbook

## Escalation Levels

### Level 0: Normal Operation
- Daily report received, metrics within range
- No action required

### Level 1: Investigate (within 8 hours)
**Triggers**:
- WARNING alert received
- Daily report shows unusual metric (e.g., 0 trades today)
- Feed health < 95%
- Minor drift detection

**Actions**:
1. SSH into VPS
2. Check logs: `docker compose logs --tail 100 forward-paper`
3. Check health: `cat forward_runs/health.json`
4. If explainable (weekend gap, expected behavior): note in weekly checkpoint
5. If unexplainable: monitor for 24 hours before escalating

### Level 2: Urgent Response (within 4 hours)
**Triggers**:
- CRITICAL alert (risk state locked/stopped, CB fire, config mismatch)
- Service crash-looping (3+ restarts in 1 hour)
- Zero bars processed for 24+ hours during trading week

**Actions**:
1. Immediately SSH into VPS
2. Check container status and logs
3. Pause the trial if needed: `docker compose stop forward-paper`
4. Investigate root cause
5. Apply fix and restart, OR document as incident
6. Report resolution in weekly checkpoint

### Level 3: Emergency (immediate)
**Triggers**:
- EMERGENCY alert (service crashed with unhandled exception)
- Data corruption detected
- Circuit breaker fires 3+ times in one week

**Actions**:
1. Stop the service: `docker compose stop forward-paper`
2. Preserve all artifacts (do not delete anything)
3. Full investigation
4. Assess whether trial should continue
5. If continuing: fix, restart, document
6. If not: stop trial, produce post-mortem

## Decision Authority

| Decision | Authority |
|----------|-----------|
| Continue after L1 | Operator (self) |
| Continue after L2 | Operator with documented justification |
| Continue after L3 | Full review required before restart |
| Stop trial | Operator at any time |
| Modify strategy | NOT ALLOWED during trial |
| Modify config | NOT ALLOWED during trial |
| Modify infrastructure | Allowed if documented |
