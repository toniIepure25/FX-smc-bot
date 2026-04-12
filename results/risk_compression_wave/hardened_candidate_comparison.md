# Hardened Candidate Comparison: sweep_plus_bos vs bos_continuation_only

Generated: 2026-04-12T12:37:58.591245

Gate threshold: max_drawdown_pct <= 20%

## Gate Pass Summary

- sweep_plus_bos: 29/30 profiles pass gate
- bos_continuation_only: 29/30 profiles pass gate

## Best sweep_plus_bos Profile

- Profile: **size_030_cb125** (0.30% risk + 12.5% circuit breaker)
- Sharpe: 2.076 | PF: 5.58 | DD: 13.4% | Trades: 513
- Gate: pass

## Best bos_continuation_only Profile

- Profile: **size_030_cb125** (0.30% risk + 12.5% circuit breaker)
- Sharpe: 1.948 | PF: 5.90 | DD: 12.8% | Trades: 432
- Gate: pass

## Head-to-Head (Best Profile Each)

- Sharpe advantage: sweep_plus_bos by 0.128
- PF advantage: bos_continuation_only by 0.33
- Drawdown: bos_continuation_only is better by 0.6%
- Trade count: sweep_plus_bos has 81 more trades

**Verdict**: sweep_plus_bos has meaningfully better Sharpe — the sweep family adds measurable value.

## Simplicity-Adjusted Ranking

When performance is within 5% on Sharpe, prefer the simpler candidate.

- sweep_plus_bos/size_030_cb125 (2-family): Sharpe=2.076 DD=13.4% Gate=pass
- sweep_plus_bos/hardened_C (2-family): Sharpe=2.026 DD=12.9% Gate=pass
- bos_continuation_only/size_030_cb125 (1-family): Sharpe=1.948 DD=12.8% Gate=pass
- sweep_plus_bos/size_030_tight_daily (2-family): Sharpe=2.069 DD=15.1% Gate=pass
- sweep_plus_bos/size_030 (2-family): Sharpe=2.066 DD=15.0% Gate=pass
- sweep_plus_bos/size_030_cb15 (2-family): Sharpe=2.066 DD=15.0% Gate=pass
- sweep_plus_bos/size_030_conc2 (2-family): Sharpe=2.066 DD=15.0% Gate=pass
- sweep_plus_bos/size_025_conc1 (2-family): Sharpe=2.029 DD=15.2% Gate=pass
- sweep_plus_bos/size_025_cb125 (2-family): Sharpe=1.990 DD=14.4% Gate=pass
- sweep_plus_bos/hardened_B (2-family): Sharpe=2.011 DD=15.3% Gate=pass
