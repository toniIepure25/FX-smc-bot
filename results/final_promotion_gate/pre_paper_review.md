# Pre-Paper Review: BOS-Only USDJPY

Generated: 2026-04-12T18:47:22.265325

## What Is Strong

1. **Holdout Sharpe**: 0.850 — materially positive, well above 0.3 threshold
2. **Profit Factor**: 1.96 — winners significantly exceed losers
3. **Drawdown**: 12.6% — well contained, below 15%
4. **Execution Stress**: All 4 scenarios positive — edge survives realistic friction
5. **Cost Robustness**: Positive through 3.0x spread multiplier
6. **OOS Mean**: 1.599 positive across 27 folds

## What Remains Weak

1. **Win Rate**: 29.1% — below standard thresholds (mitigated by high PF)
2. **OOS Variance**: std=2.060 — high temporal instability
3. **Worst Fold**: Sharpe=-0.975 — some periods are clearly negative
4. **Single-Pair Concentration**: No cross-pair diversification
5. **Data Quality**: Yahoo ~30% missing bars, no institutional spread data

## What Is Known

- The edge is overwhelmingly concentrated in USDJPY BOS continuation
- EURUSD and GBPUSD are net destructive and correctly excluded
- sweep_reversal has been correctly demoted (reversed from profitable to harmful OOS)
- The strategy is a low-frequency, high-RR trend-following signal
- Low win rate is structurally expected for this signal type

## What Is Uncertain

- Whether the edge persists in live conditions with real spreads and fills
- Whether Yahoo data gaps inflated or deflated performance
- Whether the strong OOS mean is driven by a few outlier winning periods
- How the strategy behaves during USDJPY-specific regime shifts (BoJ intervention, etc.)
- Whether signal frequency in live matches backtest expectations

## What Could Invalidate Quickly

- Sustained zero signals (BOS pattern may not appear in current market structure)
- Win rate collapsing below 15% (structure may have fundamentally changed)
- Drawdown exceeding 15% within first 4 weeks
- USDJPY regime shift (major BoJ policy change, carry trade unwind)

## Is Single-Pair Concentration Acceptable for Paper Stage?

**YES.** Paper trading is inherently a validation experiment, not a commitment.
The purpose is precisely to test whether the backtest edge translates to live conditions.
Single-pair concentration is a known risk factor but not a reason to skip paper validation.
The hardened invalidation criteria and weekly review process are designed to catch
concentration-related failures early.

## Is Data Quality Good Enough for a Paper-Stage Decision?

**MARGINAL.** The synthetic data does not confirm Yahoo results,
introducing meaningful uncertainty about data-quality dependence.

## Is Temporal Instability Acceptable for Paper Stage?

**YES.** Despite high variance, the majority of OOS folds are positive
and the mean is materially positive. The 4-6 week paper window
may fall in a positive or negative period — the weekly review process
is designed to account for this by comparing against backtest baselines
rather than demanding immediately profitable results.