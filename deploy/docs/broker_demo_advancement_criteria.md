# Broker-Demo Advancement Criteria

## Prerequisites (Must ALL be true)

1. **4-week paper trial completed** with all hard success criteria met
2. **Total trades >= 40** over the trial period
3. **Profit factor > 1.0** (net profitable)
4. **Win rate > 35%** (reasonable for BOS continuation)
5. **Max drawdown < 8%** from peak equity
6. **Circuit breaker fires <= 1** over the full trial
7. **Feed completeness > 90%** (data pipeline reliable)
8. **Service uptime > 95%** (infrastructure stable)
9. **No unresolved P0/P1 incidents** from the trial period
10. **All weekly checkpoints documented** with continue decisions

## Required Preparation Before Broker-Demo

| Item | Status | Notes |
|------|--------|-------|
| Broker demo account | Not started | Choose broker with FX demo API |
| `BrokerAdapter` implementation | Not started | Implement for chosen broker |
| `BrokerGateway` demo mode test | Partially done | Tested with `PaperBroker` in near-live wave |
| Kill switch verification | Not started | Test `BrokerGateway.kill()` with real adapter |
| Order reconciliation logic | Exists | `SafetyController` has basic reconciliation |
| Demo API credentials | Not started | Obtain from broker |

## Remaining Technical Gaps

| Gap | Severity | To Fix |
|-----|----------|--------|
| No real `BrokerAdapter` implementation | High | Build for chosen broker |
| `PollingFeedProvider` is a stub | Medium | Implement for broker's data API |
| No live H4 feed mechanism | Medium | Add H4 polling or compute from H1 |
| VPS → broker network latency unknown | Low | Test during demo phase |
