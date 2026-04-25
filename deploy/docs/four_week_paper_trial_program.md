# 4-Week Paper Trading Trial Program

## Objective

Prove the `bos_only_usdjpy` strategy is operationally stable and generates realistic trades on live data over 28 calendar days (~20 trading days) before advancing to broker-demo integration.

## Experimental Design

| Parameter | Value |
|-----------|-------|
| Strategy | `bos_only_usdjpy` (frozen) |
| Pair | USDJPY |
| Timeframe | H1 (execution), H4 (HTF context) |
| Config | `prop_v2_hardened` (fingerprinted) |
| Sizing | `DrawdownAwareSizing` |
| Initial equity | $100,000 (paper) |
| Duration | 28 calendar days |
| Feed mode | `file_watch` (live CSV drops) |
| Platform | VPS (Docker Compose) |

## Schedule

| Week | Dates | Focus |
|------|-------|-------|
| 1 | Days 1-7 | System stability, feed integrity, first trades |
| 2 | Days 8-14 | Performance baseline, pattern analysis |
| 3 | Days 15-21 | Consistency confirmation, risk stress |
| 4 | Days 22-28 | Final validation, decision package |

## Daily Expectations

- **Bars**: ~24 H1 bars per trading day
- **Candidates**: 5-15 raw candidates per trading day
- **Trades**: 1-3 executed trades per trading day (capped by `max_trades_per_day=3`)
- **Artifacts**: Daily review JSON, alerts, journal entries

## Weekly Checkpoint

At the end of each week, the operator must:
1. Review the weekly Telegram report
2. Check cumulative metrics vs thresholds
3. Document any incidents
4. Make a continue/pause/abort decision

## Success Criteria (End of 4 Weeks)

| Metric | Threshold | Hard/Soft |
|--------|-----------|-----------|
| Total trades | >= 40 | Hard |
| Win rate | > 35% | Hard |
| Profit factor | > 1.0 | Hard |
| Max drawdown | < 8% | Hard |
| Circuit breaker fires | <= 1 | Hard |
| Feed completeness | > 90% | Hard |
| Signal drought (max) | < 5 trading days | Hard |
| Service uptime | > 95% | Soft |
| Daily reports generated | >= 18/20 | Soft |
| Drift detector all-red | Never | Hard |

## Failure Criteria (Immediate Stop)

- Circuit breaker fires 3+ times
- Max drawdown exceeds 10%
- Zero trades in 7 consecutive trading days
- Config fingerprint mismatch detected
- Unrecoverable data corruption

## Invalidation Rules

The trial is invalidated if:
- Strategy logic is modified during the trial
- Config parameters are changed
- Data feed is retroactively corrected
- Manual trades are injected
