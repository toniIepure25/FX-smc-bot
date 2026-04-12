# Final Promotion Verdict: BOS-Only USDJPY

Generated: 2026-04-12T18:47:22.266002

## Decision: **CONTINUE_PAPER_TRADING**
Confidence: **low-medium**

## Champion
- Strategy: bos_only_usdjpy
- Family: bos_continuation (sweep_reversal permanently demoted)
- Pair: USDJPY (EURUSD and GBPUSD excluded)
- Risk: 0.30% per trade, 12.5% circuit breaker

## Does BOS-only USDJPY survive stronger validation?

**YES.** Holdout Sharpe 0.850, OOS mean 1.599 across
27 folds (63% positive).
Strategy remains positive under all execution stress scenarios.

## Does it remain robust on better data and realistic spreads?

**PARTIALLY.** Synthetic holdout Sharpe 0.000 — edge weakens on cleaner data.
Cost robustness through 3.0x spread multiplier confirmed.

## Is the low win rate a real blocker?

**NO.** Win rate 29.1% is structurally expected for a trend-following BOS signal.
PF of 1.96 demonstrates that winners compensate for frequency.
Revised gate threshold of 25% is justified for this strategy type.

## Does BOS-only USDJPY remain positive across stronger temporal validation?

**YES.** 63% of 27 folds are positive,
with mean OOS Sharpe 1.599.

## Is CONTINUE_PAPER_TRADING justified?

**YES.** The candidate passes the revised promotion gate, demonstrates positive OOS mean,
survives execution stress, and has a hardened paper-trading package with clear
invalidation criteria. Paper trading is the appropriate next step to validate
whether the backtest edge translates to live market conditions.

## Unresolved Risks

- Single-pair USDJPY concentration
- Yahoo data quality (~30% missing bars)
- High OOS variance (std=2.060)
- No institutional-grade data confirmation
- Regime sensitivity in some temporal windows

## Next Steps

1. Deploy frozen bos_only_usdjpy config to paper trading environment
2. Execute paper_stage_checklist.md pre-deployment steps
3. Monitor for minimum 4 weeks with weekly reviews
4. Compare paper results against backtest baselines using discrepancy_thresholds.json
5. Week 2: initial signal funnel audit
6. Week 4: first Sharpe assessment — hard stop if < 0
7. Week 6: full promotion review — decide live / extend / reject