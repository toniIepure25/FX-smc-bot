# Prop Account Preconditions

## Strategy Validation Complete

- [x] Historical validation (1,235 trades, PF 2.99)
- [x] Advanced robustness suite (7 tests passed)
- [x] Forward runner repaired and validated
- [ ] 4-week live forward paper trial
- [ ] 1-week broker-demo shadow
- [ ] 2-week broker-demo actual

## Operational Readiness

- [x] Containerized deployment stack
- [x] Crash recovery with checkpoints
- [x] Remote monitoring via Telegram
- [x] Automated daily/weekly reporting
- [x] Risk management (DD tracker, CB, constraints)
- [ ] Proven on real live data for 4 weeks
- [ ] Broker API integration tested
- [ ] Kill switch tested on real infrastructure
- [ ] Disaster recovery procedure tested

## Prop Firm Requirements

| Requirement | Status | Notes |
|------------|--------|-------|
| Drawdown limit compliance | Designed for 5-10% DD | Strategy params hardened |
| Daily loss limit | 2% configured | Matches most prop rules |
| Consistency requirements | Need 4-week data | Some props require consistent profitability |
| Minimum trading days | Need data | Most props require ~10+ trading days/month |
| Position sizing rules | Risk-based sizing | Compliant with standard prop rules |
| News event restrictions | Not implemented | May need calendar integration |
| Weekend holding restrictions | Not implemented | Strategy closes daily in practice |

## Capital Sizing

For a prop firm account:
- `base_risk_per_trade = 0.003` (0.3% per trade)
- On $100K account: ~$300 risk per trade
- Max 3 trades/day: ~$900 max daily exposure
- Max daily DD: 2% = $2,000
- Circuit breaker: 10% = $10,000

These parameters are conservative and compatible with most prop firm rules.

## Missing Pieces Before Prop

1. **Live data feed**: Need a reliable source for USDJPY H1 bars (broker API, free data provider, or manual export)
2. **Broker adapter**: Need to implement `BrokerAdapter` for the chosen prop firm's platform
3. **News calendar integration**: Optional but recommended for prop compliance
4. **Position rollover handling**: For overnight/weekend positions
5. **Regulatory compliance**: Depends on jurisdiction and prop firm terms
