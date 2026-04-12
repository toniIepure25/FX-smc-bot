# Paper Stage Invalidation Rules

## Candidate: bos_only_usdjpy

---

## Hard-Stop Invalidation (Immediate Suspension)

These criteria cause immediate termination of the paper trading program.
No discretion — if any of these fire, paper trading stops.

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| **HSI-1** Negative Sharpe at week 4 | Paper Sharpe < 0.0 after 4 complete weeks | If the strategy cannot maintain positive expectancy over 4 weeks of paper trading, the backtest edge is not translating |
| **HSI-2** Excessive drawdown | Peak-to-trough > 15% at any point | Exceeds the hardened risk profile's acceptable range (holdout MaxDD was 12.6%) |
| **HSI-3** Win rate collapse | Win rate < 15% over any rolling 2-week window | Below the structural floor; at backtest WR of 29%, a 15% floor is ~2 standard deviations below expectation |
| **HSI-4** Signal drought | 0 signals generated for 5 consecutive trading days | Indicates the BOS continuation pattern is not appearing in current market structure |
| **HSI-5** Circuit breaker fires | Any circuit breaker activation | The 12.5% CB threshold should not be reachable under normal operation |
| **HSI-6** Config mutation | Config fingerprint mismatch detected at any checkpoint | Indicates the frozen config was tampered with, invalidating the controlled experiment |

---

## Soft Warning Rules (Increased Monitoring)

These do not halt paper trading but require documented acknowledgment and closer monitoring.

| Rule | Threshold | Response |
|------|-----------|----------|
| **SW-1** Low trade frequency | < 3 trades in any week | Increase monitoring; investigate signal funnel |
| **SW-2** High trade frequency | > 15 trades in any week | Investigate for signal spam; compare to backtest baseline |
| **SW-3** Signal rejection spike | > 80% of signals rejected in a week | Review rejection reasons; check for data or config issues |
| **SW-4** Spread discrepancy | Paper fills consistently 2x+ wider than backtest assumptions | Flag execution environment concern |
| **SW-5** Win rate drift | Win rate < 20% over any 3-week window | Monitor closely; not yet a hard stop but approaching |
| **SW-6** Drawdown warning | Peak-to-trough > 10% | Increase monitoring frequency; prepare for potential hard stop |
| **SW-7** Sharpe degradation | Running Sharpe decreasing for 3 consecutive weeks | Note trend; check for regime shift |
| **SW-8** Session concentration | > 80% of trades in a single session (e.g., only Asian) | Compare to backtest session distribution |

---

## Continue-With-Monitoring Rules

These represent acceptable conditions that should still be tracked.

| Rule | Condition | Action |
|------|-----------|--------|
| **CM-1** Normal variance | Weekly PnL oscillates but cumulative trend positive | Standard weekly review |
| **CM-2** Expected losing week | 1 losing week in a positive trend | Document; verify no structural change |
| **CM-3** Trade count in range | 5-12 trades/week | Standard weekly review |
| **CM-4** Win rate in range | 22-38% over 2+ week window | Standard weekly review |
| **CM-5** Drawdown within limits | < 10% peak-to-trough | Standard weekly review |
| **CM-6** No risk events | No throttle/lockout/CB activations | Standard weekly review |

---

## Invalidation Review Process

1. When a hard-stop fires: immediately halt, preserve all artifacts, document the trigger
2. When a soft warning fires: document in the next review artifact, increase monitoring
3. At each formal checkpoint: evaluate all active warnings and their trends
4. Hard-stop decisions are final for the current campaign (no restart without new approval)
5. Soft warnings can be resolved if the underlying condition improves over the next review period
