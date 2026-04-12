# Updated Final Decision — Holdout Stability Investigation

Generated: 2026-04-12T13:34:19.677394

## Decision: **HOLD_FOR_MORE_VALIDATION**
Confidence: low-medium

## Champion: bos_continuation_only (risk profile: size_030_cb125)

## Why This Decision

The holdout weakness appears **structural**:

- Walk-forward shows only 40% of OOS folds with positive Sharpe
- Mean OOS Sharpe across folds: 0.195
- Performance degradation is not confined to one period

## Key Evidence

1. **Train vs Holdout**: Sharpe 2.076 -> 0.154
2. **Walk-Forward**: Mean OOS Sharpe 0.195, 40% positive
3. **Stress Test**: Passed
4. **Mitigations**: 0 useful out of 3 tested
5. **Drawdown Control**: Remains strong (12.7% holdout, 13.1% WF average)

## What Caused the Holdout Degradation

Based on the regime diagnostics (Phase A), the holdout period shows:

## Next Steps

1. Acquire higher-quality FX data (Dukascopy CSV or broker data)
2. Re-run holdout on better data to isolate data-quality effects
3. Test on additional OOS periods as more data becomes available
4. Consider extending training window to capture more regimes

## Unresolved Risks

- Yahoo Finance data quality limitations (no bid/ask spread)
- Fixed 1.5 pip spread assumption may overstate or understate costs
- Limited to 3 major pairs (EURUSD, GBPUSD, USDJPY)
- Walk-forward indicates potential structural alpha decay
- Strategy relies on SMC structure detection that may be sensitive to volatility regimes