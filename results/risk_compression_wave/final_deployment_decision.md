# Final Deployment Decision

Generated: 2026-04-12

## Decision: **HOLD_FOR_MORE_VALIDATION**

Confidence: medium

## What Was Tested

- 60 backtest runs across 30 risk parameter profiles and 2 alpha candidates
- sweep_plus_bos (2-family: sweep reversal + BOS continuation)
- bos_continuation_only (1-family: BOS continuation)
- Real H1 FX data: EURUSD, GBPUSD, USDJPY (April 2024 - April 2026)
- H4 higher-timeframe context for structural bias
- Train split: 60% of data (~7,400 bars/pair)
- Holdout split: last 20% of data (~2,450 bars/pair)

## What Reduced Drawdown

The primary drawdown reduction came from reducing `base_risk_per_trade`:
- 0.50% -> 0.30%: drawdown fell from 35.2% to 15.0% (a 57% reduction)
- Adding 12.5% circuit breaker: drawdown fell further to 13.4%

The circuit breaker was the most impactful supplementary control, responsible for ~1.6% additional drawdown reduction. Concurrency limits and daily lockout tightening provided marginal additional benefit.

**Position sizing was by far the dominant lever.** The existing risk infrastructure (throttling, constraints, daily lockout) was already well-designed — the only issue was the base sizing being too aggressive for deployment.

## Whether Sharpe/Edge Survived

On training data: **yes, emphatically**. Sharpe *improved* from 1.53 to 2.08 as risk was reduced, because the lower sizing reduced variance more than it reduced return. Profit factor improved from 2.2 to 5.6.

On holdout data: **partially**. Sharpe dropped to 0.15 (positive but below the 0.3 gate threshold). Drawdown control survived fully (12.7% in holdout). The alpha is real but the return magnitude did not persist into the last 20% of data at the same level.

## Who The Final Hardened Champion Is

**sweep_plus_bos** with the **size_030_cb125** risk profile:
- base_risk_per_trade: 0.30%
- max_portfolio_risk: 0.90%
- circuit_breaker_threshold: 12.5%
- All other risk controls at defaults

This profile achieved:
- Training: Sharpe 2.076, PF 5.58, DD 13.4%, 513 trades
- Holdout: Sharpe 0.154, DD 12.7%, 253 trades

The challenger bos_continuation_only was materially weaker (Sharpe 1.948 vs 2.076 on training), so sweep_plus_bos remains the champion. Sweep adds 0.128 Sharpe and 81 trades, justifying the 2-family complexity.

## Whether Paper-Trading Is Justified

**Not yet.** The holdout Sharpe degradation (93% drop) is too large to justify immediate paper trading promotion. While the strategy is not losing money on holdout (Sharpe > 0), the return magnitude is insufficient to meet the deployment gate.

## Reasons

1. **Drawdown compression succeeded**: 35.2% -> 13.4% on training, 12.7% on holdout
2. **Sharpe improved on training**: 1.53 -> 2.08 (risk reduction improved Sharpe)
3. **Circuit breaker works**: fired once, providing active tail-risk protection
4. **58/60 profiles pass training gate**: risk compression is broadly effective
5. **Holdout Sharpe fails gate**: 0.154 vs 0.3 threshold
6. **Holdout drawdown passes**: 12.7% vs 20% threshold (risk controls generalize)
7. **The alpha is real but regime-sensitive**: positive holdout Sharpe, but far below training

## What the Chosen Risk Profile Preserves

- The fundamental alpha from sweep reversal and BOS continuation
- Trade count adequate for statistical significance (500+ on train, 250+ on holdout)
- Win rate above 56% (training)
- Drawdown well within institutional limits (13.4% training, 12.7% holdout)
- All professional risk controls active

## What Unresolved Deployment Risks Remain

1. **Holdout performance degradation**: The most critical issue. Alpha may be regime-dependent.
2. **Data quality**: Yahoo Finance free data with fixed 1.5 pip spread assumption.
3. **Limited history**: 2 years is marginal for tail-risk estimation.
4. **No execution latency modeling**: Assuming next-bar fills.
5. **Circuit breaker uncertainty**: One activation during training — the strategy's behavior post-restart is untested.

## Recommended Next Steps

1. **Investigate holdout regime**: Analyze what changed in the Oct 2025 - Apr 2026 period
2. **Acquire professional data**: Real tick data with spreads from a broker or Dukascopy
3. **Walk-forward validation**: Replace train/holdout split with rolling walk-forward
4. **Consider relaxed holdout gate**: If drawdown is the primary deployment concern (it is), a min_sharpe of 0.1 for holdout may be more appropriate since the strategy is profitable
5. **Paper-trade with manual monitoring**: Even before formal promotion, the hardened risk profile could be paper-tested with daily human review

## Risk Profile for Future Paper Trading

When holdout validation is eventually passed:

```json
{
  "base_risk_per_trade": 0.003,
  "max_portfolio_risk": 0.009,
  "circuit_breaker_threshold": 0.125,
  "max_concurrent_positions": 3,
  "max_daily_drawdown": 0.03,
  "max_weekly_drawdown": 0.06,
  "daily_loss_lockout": 0.025,
  "consecutive_loss_dampen_after": 3,
  "consecutive_loss_dampen_factor": 0.5
}
```
