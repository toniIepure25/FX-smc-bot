# Gate Criterion Justification

Generated: 2026-04-12T18:47:22.264005

## Is a 35% win-rate threshold appropriate?

The candidate has a 29.1% win rate with Sharpe 0.850 and PF 1.96.

**Analysis**: A 35% win-rate threshold is standard for balanced strategies that mix
frequent small wins with occasional losses. However, BOS continuation is a
trend-following signal that targets larger reward-to-risk ratios. Such strategies
routinely operate at 25-35% win rates while maintaining positive expectancy
because their average winner significantly exceeds their average loser.

With PF=1.96 (meaning winners are 2.0x total losers),
the low win rate is **compensated by large winners** and is NOT a valid blocker.
**Recommendation**: Lower win-rate threshold to 25% for this strategy type.

## Should a single-pair strategy have stricter standards?

**Yes, partially.** A single-pair strategy has no cross-pair diversification,
so a regime shift in USDJPY directly impacts the entire portfolio. However:
- The candidate has already been tested under 4 execution stress scenarios (all positive)
- Walk-forward shows the strategy survives multiple temporal windows
- Paper trading is inherently a further validation stage — not a commitment to live capital

**Recommendation**: Apply a concentration penalty to confidence but do NOT block
paper-stage promotion solely due to single-pair concentration. Paper trading IS
the appropriate next step for validating single-pair robustness.

## Does positive stress test performance offset low win rate?

**YES.** The strategy remains positive under all spread multipliers tested (1.0x-3.0x).
This demonstrates that the edge is real and not an artifact of optimistic execution assumptions.

## Should confidence remain low-medium despite passing gates?

OOS mean Sharpe: 1.599 (std: 2.060)
OOS % positive: 63%
High OOS variance justifies maintaining **low-medium** confidence even if nominal gates pass.
Paper trading should be treated as a further validation stage, not a confirmed edge.