# Spread Realism Report: BOS-Only USDJPY

Generated: 2026-04-12T18:42:48.224025

Yahoo holdout under varying spread/slippage multipliers.

| Spread         | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------|--------|---------|--------|---------|-------|----------------|
| 1.0x (base)    |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| 1.5x           |    220 |   0.811 |   1.90 |   12.6% | 27.3% |      35,992.16 |
| 2.0x           |    220 |   0.820 |   1.92 |   12.6% | 25.5% |      37,377.17 |
| 2.5x           |    220 |   0.776 |   1.85 |   12.6% | 24.1% |      34,155.97 |
| 3.0x           |    219 |   0.731 |   1.78 |   12.6% | 24.2% |      31,251.45 |

## Degradation Analysis

- Base Sharpe: 0.850
- 3.0x Sharpe: 0.731
- Strategy remains **positive** even at 3x spread/slippage — strong cost robustness.