# Final Root-Cause and Promotion Decision

Generated: 2026-04-12T15:14:32.189552

## Decision: **CONTINUE_WITH_SIMPLIFICATION**
Confidence: low-medium

## Champion: bos_continuation_only (risk profile: size_030_cb125)

## Root Cause of Holdout Weakness

- win-rate collapse (primary)
- winner size collapse
- extreme USDJPY concentration (100% of train PnL)
- sweep_reversal family reversal (profitable in train, loss-making in holdout)

## Key Evidence

1. **Train vs Holdout**: Sharpe 2.076 -> 0.154 (-92.6%)
2. **Win Rate**: 56.3% -> 31.2% (collapsed)
3. **Walk-Forward**: Mean OOS Sharpe 0.279, 40% positive folds
4. **sweep_reversal**: Profitable in train, loss-making in holdout (family reversal)
5. **bos_continuation**: Loss-making in train, profitable in holdout (inverse behavior)
6. **Pair concentration**: 56% of train trades on USDJPY
7. **Data quality**: Yahoo Sharpe 0.154 vs Synthetic -0.743
8. **Stress test**: Passed (conservative Sharpe remains positive)
9. **Drawdown control**: Remains strong (12.7% holdout)

## Is the Holdout Weakness Structural or Contextual?

The walk-forward evidence suggests **structural weakness** — only 40% of folds are positive.
The strategy has regime-dependent edge that appears in some periods but not reliably.

## Dominant Failure Mechanism

The primary cause is **win-rate collapse combined with extreme pair concentration**.
The strategy's training edge was dominated by USDJPY sweep_reversal trades with 
high win rates. In holdout, sweep_reversal win rate drops from ~60% to ~29%, 
converting a highly profitable family into a loss-maker. BOS continuation, which 
was unprofitable in training, becomes the only profitable holdout family — but 
its contribution is too small to compensate.

## Is BOS-Only the Correct Champion?

- BOS-only holdout: Sharpe=0.154, Trades=253
- sweep_plus_bos holdout: Sharpe=0.154, Trades=253
Performance is similar — BOS-only is preferred for simplicity.

## Next Steps

1. Switch to bos_continuation_only if not already
2. Apply pair filtering if USDJPY concentration is confirmed as beneficial
3. Re-validate simplified config under walk-forward
4. Proceed to paper trading if simplified config passes OOS gates

## Unresolved Risks

- Strategy edge is highly regime-dependent and inconsistent across temporal windows
- Yahoo Finance data quality limitations (30% missing bars, no spread data)
- Extreme USDJPY concentration in training may indicate overfitting to one pair
- Walk-forward shows high variance (Sharpe std ~1.4) indicating fragile alpha
- No session attribution available (all trades tagged 'unknown')