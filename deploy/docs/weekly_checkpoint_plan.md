# Weekly Checkpoint Plan

## Week 1: Stability Validation

**Goal**: Confirm the system runs stably and processes live data correctly.

| Check | Expected | Action if failed |
|-------|----------|-----------------|
| Service running continuously | Yes | Debug restart loops |
| Bars processed > 100 | Yes | Check data feed pipeline |
| At least 1 trade executed | Yes | Investigate signal path |
| Feed completeness > 90% | Yes | Fix data delivery |
| Zero EMERGENCY alerts | Yes | Investigate root cause |
| Telegram alerts arriving | Yes | Check bot credentials |
| Daily reports generating | Yes | Check cron setup |

**Decision**: Continue / Pause for investigation

## Week 2: Performance Baseline

**Goal**: Establish performance metrics and verify they are within expected ranges.

| Check | Expected | Action if failed |
|-------|----------|-----------------|
| Total trades >= 10 | Yes | Investigate signal drought |
| Win rate > 30% | Yes | Acceptable for early sample |
| PnL trend not catastrophic | Yes | Review if > 5% drawdown |
| No persistent drift | Yes | Review if drift flagged |
| Feed gaps only weekends | Yes | Fix non-weekend gaps |

**Decision**: Continue / Pause / Adjust data feed

## Week 3: Consistency Confirmation

**Goal**: Confirm performance is consistent and risk management is working.

| Check | Expected | Action if failed |
|-------|----------|-----------------|
| Total trades >= 25 | Yes | Investigate if below |
| Win rate stabilizing > 35% | Yes | Monitor closely |
| Max drawdown < 6% | Yes | Review risk params if above |
| Circuit breaker fires <= 1 | Yes | Investigate if more |
| System restarts <= 2 | Yes | Debug stability issues |

**Decision**: Continue / Pause / Extend trial

## Week 4: Final Validation

**Goal**: Complete the trial and produce the decision package.

| Check | Expected | Action if failed |
|-------|----------|-----------------|
| All success criteria met | Yes | Produce go decision |
| No blocking incidents | Yes | Document and assess |
| Clean shutdown and archive | Yes | Manual archive if needed |

**Decision**: Advance to broker-demo / Extend paper / Reject
