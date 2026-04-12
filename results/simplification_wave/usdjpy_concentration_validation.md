# USDJPY Concentration Validation

Generated: 2026-04-12T17:54:10.244112

## Train Period

| Variant                              | Pairs                  | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|--------------------------------------|------------------------|--------|---------|--------|---------|-------|----------------|
| sweep_plus_bos | All 3 pairs         | All 3 pairs            |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |
| sweep_plus_bos | USDJPY only         | USDJPY only            |    512 |   2.075 |   5.62 |   13.5% | 55.7% |   8,604,535.71 |
| bos_only | USDJPY+EURUSD             | USDJPY+EURUSD          |    432 |   1.948 |   5.90 |   12.8% | 59.7% |   6,175,139.77 |
| bos_only | All 3 pairs               | All 3 pairs            |    432 |   1.948 |   5.90 |   12.8% | 59.7% |   6,175,139.77 |
| bos_only | USDJPY only               | USDJPY only            |    429 |   1.930 |   5.88 |   12.8% | 58.7% |   5,705,609.62 |
| bos_only | USDJPY+GBPUSD             | USDJPY+GBPUSD          |    426 |   1.924 |   5.90 |   12.8% | 59.2% |   5,710,921.52 |
| bos_only | EURUSD only               | EURUSD only            |    125 |   0.115 |   1.17 |   12.7% | 32.0% |       3,683.63 |
| bos_only | EURUSD+GBPUSD             | EURUSD+GBPUSD          |     80 |   0.091 |   1.18 |   12.6% | 23.8% |       2,818.57 |
| bos_only | GBPUSD only               | GBPUSD only            |     48 |  -0.279 |   0.55 |   12.7% | 29.2% |      -6,456.44 |

## Holdout Period

| Variant                              | Pairs                  | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|--------------------------------------|------------------------|--------|---------|--------|---------|-------|----------------|
| sweep_plus_bos | USDJPY only         | USDJPY only            |    330 |   1.172 |   2.04 |   12.5% | 34.8% |      71,845.63 |
| bos_only | USDJPY+EURUSD             | USDJPY+EURUSD          |    251 |   0.862 |   1.93 |   12.6% | 35.5% |      38,606.59 |
| bos_only | USDJPY only               | USDJPY only            |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| bos_only | All 3 pairs               | All 3 pairs            |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| sweep_plus_bos | All 3 pairs         | All 3 pairs            |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| bos_only | USDJPY+GBPUSD             | USDJPY+GBPUSD          |    174 |   0.114 |   1.09 |   12.7% | 27.0% |       2,845.58 |
| bos_only | EURUSD only               | EURUSD only            |    114 |  -0.818 |   0.49 |   12.8% | 25.4% |      -7,703.89 |
| bos_only | EURUSD+GBPUSD             | EURUSD+GBPUSD          |    126 |  -1.097 |   0.29 |   12.8% | 27.0% |     -12,058.61 |
| bos_only | GBPUSD only               | GBPUSD only            |     92 |  -1.380 |   0.15 |   12.5% |  9.8% |     -12,309.40 |

## Walk-Forward OOS (5 anchored folds)

| Variant                              | Pairs                  |  WF Mean |    Std |  %Pos |  >0.3 |                          Folds |
|--------------------------------------|------------------------|----------|--------|-------|-------|--------------------------------|
| sweep_plus_bos | USDJPY only         | USDJPY only            |    0.836 |  1.473 |  60% |  60% | -0.975, -0.393, 2.189, 2.864, 0.496 |
| bos_only | USDJPY+GBPUSD             | USDJPY+GBPUSD          |    0.713 |  1.529 |  60% |  60% | -1.366, 0.526, 2.132, 2.711, -0.436 |
| bos_only | USDJPY+EURUSD             | USDJPY+EURUSD          |    0.684 |  1.577 |  60% |  60% | -0.364, 0.742, 1.907, 2.783, -1.648 |
| bos_only | USDJPY only               | USDJPY only            |    0.649 |  1.562 |  40% |  40% | -0.975, -0.393, 2.189, 2.864, -0.441 |
| bos_only | All 3 pairs               | All 3 pairs            |    0.279 |  1.365 |  40% |  40% | -0.281, 0.747, -0.652, 2.713, -1.131 |
| sweep_plus_bos | All 3 pairs         | All 3 pairs            |    0.279 |  1.365 |  40% |  40% | -0.281, 0.745, -0.652, 2.713, -1.131 |
| bos_only | EURUSD+GBPUSD             | EURUSD+GBPUSD          |    0.100 |  1.031 |  60% |  60% | 1.214, 0.809, 0.756, -0.947, -1.330 |
| bos_only | EURUSD only               | EURUSD only            |   -0.208 |  1.302 |  60% |  60% | -1.594, 0.822, 1.107, 0.595, -1.973 |
| bos_only | GBPUSD only               | GBPUSD only            |   -0.588 |  0.663 |  20% |  20% | -0.594, 0.433, -0.206, -1.159, -1.414 |

## Key Finding: Is the Edge Just USDJPY?

- BOS all pairs holdout Sharpe: 0.154
- BOS USDJPY-only holdout Sharpe: 0.850
- BOS excl USDJPY holdout Sharpe: -1.097

**YES**: The edge is predominantly USDJPY. Removing USDJPY destroys alpha; isolating USDJPY improves holdout Sharpe by +0.697.

## Does Multi-Pair Diversification Help OOS?

- BOS all pairs WF mean Sharpe: 0.279 (40% positive)
- BOS USDJPY-only WF mean Sharpe: 0.649 (40% positive)

Multi-pair diversification **hurts** OOS consistency. USDJPY-only is more stable.