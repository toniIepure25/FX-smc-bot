# Regime-Aware Mitigation Report

Generated: 2026-04-12T13:34:19.668906

Baseline holdout Sharpe: 0.154 | PF: 1.11 | Trades: 253

## Weakness Identification

### Worst Session: unknown
- Trades: 253 | PnL: 4,215.01 | Win%: 31.2%
### Worst Pair: EURUSD
- Trades: 41 | PnL: -3,926.11 | Win%: 41.5%

### Worst Regime: normal
- Trades: 116 | PnL: -10,312.47 | Win%: 25.9%

### Worst Direction: long
- Trades: 77 | PnL: -7,546.80 | Win%: 36.4%


## Mitigation Tests

| Mitigation                     | Trades | Removed |  Sharpe~ |   Delta |     PF |          PnL |
|--------------------------------|--------|---------|----------|---------|--------|--------------|
| Baseline (no filter)           |    253 |       — |    0.154 |       — |   1.11 |     4,215.01 |
| Filter EURUSD pair             |    212 |      41 |    0.063 |  -0.090 |   1.25 |     8,141.12 |
| Filter normal regime           |    137 |     116 |    0.196 |  +0.042 |   1.80 |    14,527.48 |
| Filter long direction          |    176 |      77 |    0.112 |  -0.042 |   1.44 |    11,761.81 |

## Mitigation Conclusions

No mitigation produced a meaningful improvement (>0.05 Sharpe delta).

This suggests the holdout weakness is not concentrated in a single dimension 
that can be easily filtered — it may be a broad regime shift affecting trade quality.
