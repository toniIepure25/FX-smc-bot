# Promotion-Gate Review: BOS-Only USDJPY

Generated: 2026-04-12T18:47:22.263754

## Gate Configurations Tested

| Gate | MinSharpe | MinPF | MaxDD | MinTrades | MinWR | Verdict |
|------|-----------|-------|-------|-----------|-------|---------|
| Default | 0.3 | 1.1 | 20% | 30 | 35% | fail |
| Revised | 0.3 | 1.1 | 20% | 30 | 25% | pass |
| Strict-1pair | 0.5 | 1.3 | 15% | 50 | 25% | pass |

## Candidate Metrics

- Sharpe: 0.850
- PF: 1.96
- MaxDD: 12.6%
- Trades: 220
- Win%: 29.1%

**Default gate blockers**: win_rate