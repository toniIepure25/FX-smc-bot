# Concentration-Adjusted Candidate Ranking

Generated: 2026-04-12T17:54:10.245244

Ranking penalizes single-pair concentration (0.9x multiplier for 1-pair variants)

| Rank | Variant                              |  Raw WF |  Adj WF | H Sharpe | Pairs |
|------|--------------------------------------|---------|---------|----------|-------|
|    1 | sweep_plus_bos | USDJPY only         |   0.836 |   0.753 |    1.172 |     1 |
|    2 | bos_only | USDJPY+GBPUSD             |   0.713 |   0.713 |    0.114 |     2 |
|    3 | bos_only | USDJPY+EURUSD             |   0.684 |   0.684 |    0.862 |     2 |
|    4 | bos_only | USDJPY only               |   0.649 |   0.584 |    0.850 |     1 |
|    5 | bos_only | All 3 pairs               |   0.279 |   0.279 |    0.154 |     3 |
|    6 | sweep_plus_bos | All 3 pairs         |   0.279 |   0.279 |    0.154 |     3 |
|    7 | bos_only | EURUSD+GBPUSD             |   0.100 |   0.100 |   -1.097 |     2 |
|    8 | bos_only | EURUSD only               |  -0.208 |  -0.188 |   -0.818 |     1 |
|    9 | bos_only | GBPUSD only               |  -0.588 |  -0.529 |   -1.380 |     1 |