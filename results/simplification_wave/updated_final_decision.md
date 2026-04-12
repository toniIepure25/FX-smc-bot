# Final Simplified-Champion Decision

Generated: 2026-04-12T18:10:45.945276

## Decision: **CONTINUE_PAPER_TRADING**
Confidence: low-medium

## Champion: bos_only_usdjpy
- Family: bos_continuation (sweep_reversal permanently demoted)
- Pairs: USDJPY
- Risk: size_030_cb125

## Answers to Key Questions

### 1. Is the strategy fundamentally a USDJPY-only edge?

**YES.** BOS USDJPY-only holdout Sharpe (0.850) vs all-pairs (0.154). WF confirms: USDJPY-only mean 1.442 vs all-pairs 0.195.

### 2. Does BOS-only + USDJPY-only materially improve OOS consistency?

USDJPY-only OOS: mean=1.442, 60% positive folds.
All-pairs OOS: mean=0.195, 40% positive folds.
**YES** — USDJPY isolation improves OOS stability.

### 3. Does multi-pair diversification actually hurt rather than help?

**YES** — Adding EURUSD/GBPUSD destroys 0.697 Sharpe points in holdout.

### 4. Should EURUSD and GBPUSD be removed?

EURUSD-only holdout: Sharpe=-0.818 -> HARMFUL
GBPUSD-only holdout: Sharpe=-1.380 -> HARMFUL
**YES** — Both are net destructive. Remove from promoted package.

### 5. Is sweep_reversal permanently demoted?

sweep_plus_bos holdout: Sharpe=0.154 vs BOS-only: 0.154
**YES** — sweep_reversal adds no value OOS and reversed from profitable to loss-making.

### 6. Can BOS-only justify paper-trading continuation?

Promotion gate result: **CONDITIONAL_PROMOTE** (confidence: low-medium)
**YES** — With USDJPY focus, BOS-only passes promotion gates.

### 7. Is the strategy still too regime-sensitive?

OOS Sharpe std: 1.778
**YES** — High variance across temporal windows indicates regime sensitivity.

## Key Evidence Summary

1. Holdout Sharpe: 0.850
2. WF mean OOS Sharpe: 1.442
3. WF % positive folds: 60%
4. Stress test: PASSED
5. Drawdown: 12.6%

## Next Steps

1. Deploy bos_only_usdjpy to paper trading with frozen config
2. Monitor for 4-6 weeks with weekly Sharpe checkpoints
3. Compare live signal funnel to backtest expectations
4. Escalate if paper Sharpe < 0.0 after 4 weeks

## Unresolved Risks

- Strategy relies on a single pair (USDJPY) — no cross-pair diversification
- Yahoo Finance data limitations (30% missing bars, no spread data)
- BOS continuation was unprofitable in training, only profitable in holdout
- Walk-forward variance may indicate fragile, regime-dependent alpha
- No session-level attribution available (all trades tagged 'unknown')