# Pair Universe Comparison

Generated: 2026-04-12T17:54:10.244777

## BOS-Only: Holdout + Walk-Forward by Universe

| Universe               | H Sharpe |   H PF | H Trades |  WF Mean |  WF Std |  %Pos |  >0.3 |
|------------------------|----------|--------|----------|----------|---------|-------|-------|
| USDJPY+GBPUSD          |    0.114 |   1.09 |      174 |    0.713 |   1.529 |  60% |  60% |
| USDJPY+EURUSD          |    0.862 |   1.93 |      251 |    0.684 |   1.577 |  60% |  60% |
| USDJPY only            |    0.850 |   1.96 |      220 |    0.649 |   1.562 |  40% |  40% |
| All 3 pairs            |    0.154 |   1.11 |      253 |    0.279 |   1.365 |  40% |  40% |
| EURUSD+GBPUSD          |   -1.097 |   0.29 |      126 |    0.100 |   1.031 |  60% |  60% |
| EURUSD only            |   -0.818 |   0.49 |      114 |   -0.208 |   1.302 |  60% |  60% |
| GBPUSD only            |   -1.380 |   0.15 |       92 |   -0.588 |   0.663 |  20% |  20% |

## Assessment: Which Pairs Are Alpha-Generating?

- **All 3 pairs**: holdout=0.154, WF=0.279 -> **VIABLE**
- **USDJPY only**: holdout=0.850, WF=0.649 -> **VIABLE**
- **EURUSD only**: holdout=-0.818, WF=-0.208 -> **HARMFUL**
- **GBPUSD only**: holdout=-1.380, WF=-0.588 -> **HARMFUL**
- **EURUSD+GBPUSD**: holdout=-1.097, WF=0.100 -> **HARMFUL**
- **USDJPY+EURUSD**: holdout=0.862, WF=0.684 -> **VIABLE**
- **USDJPY+GBPUSD**: holdout=0.114, WF=0.713 -> **VIABLE**