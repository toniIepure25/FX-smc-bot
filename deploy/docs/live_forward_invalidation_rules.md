# Live Forward Invalidation Rules

## Immediate Invalidation (Stop the Trial)

1. **Strategy logic modified** during the trial period
2. **Config parameters changed** without restarting the trial from scratch
3. **Manual trade injection** into the paper account
4. **Retroactive data correction** — re-feeding bars that already processed
5. **Drawdown exceeds 10%** from peak equity
6. **Circuit breaker fires 3+ times** in a single week
7. **Zero trades for 7 consecutive trading days** (signal path failure)
8. **Unrecoverable state corruption** — cannot resume from any checkpoint

## Soft Invalidation (Investigate Before Deciding)

1. **Config fingerprint mismatch** on resume — investigate whether config changed
2. **Feed completeness < 80%** — data pipeline issue, not strategy issue
3. **Single circuit breaker fire** — review cause, may be acceptable
4. **Drift detector flags all metrics** — may indicate regime change, not strategy failure
5. **Service uptime < 90%** — operational issue, not strategy issue

## What Does NOT Invalidate the Trial

- Weekend feed gaps (expected)
- Brief throttle events that auto-recover
- Individual losing days or losing streaks (normal)
- Docker container restarts with successful checkpoint resume
- VPS maintenance reboots with clean recovery
- Telegram alert delivery failures (network issue)

## Post-Invalidation Procedure

1. Stop the trial immediately
2. Preserve all artifacts (do not delete)
3. Document the invalidation reason
4. Assess whether the issue is fixable
5. If fixable: fix, then restart the trial from scratch
6. If not fixable: reassess strategy viability
