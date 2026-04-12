# Risk Compression Campaign Report

Generated: 2026-04-12T12:40:13.565435

## Summary

- Total profiles tested: 60
- Profiles passing gate: 58
- Profiles failing gate: 2
- Gate max_drawdown_pct threshold: 20%

## Best Deployment-Ready Profile

- **sweep_plus_bos / size_030_cb125**
- Description: 0.30% risk + 12.5% circuit breaker
- Sharpe: 2.076 | PF: 5.58
- Max DD: 13.4% | Trades: 513
- Calmar: 365.67 | DD Efficiency: 15.45
- Risk overrides: {
  "base_risk_per_trade": 0.003,
  "max_portfolio_risk": 0.009,
  "circuit_breaker_threshold": 0.125
}

## Key Findings

- Drawdown range across all profiles: 10.0% — 35.2%
- Sharpe range (trades > 30): 0.434 — 2.076
- Circuit breaker fired in 58 profiles

## Risk Control Effectiveness

### Drawdown by base_risk_per_trade

- 0.20%: avg DD=13.7%, avg Sharpe=0.544 (12 profiles)
- 0.25%: avg DD=14.5%, avg Sharpe=1.812 (20 profiles)
- 0.30%: avg DD=14.6%, avg Sharpe=1.900 (16 profiles)
- 0.35%: avg DD=15.1%, avg Sharpe=1.630 (6 profiles)
- 0.40%: avg DD=16.8%, avg Sharpe=1.667 (4 profiles)
- 0.50%: avg DD=35.2%, avg Sharpe=1.521 (2 profiles)

## Holdout Results

- sweep_plus_bos/size_030_cb125: Sharpe=0.154 DD=12.7% Trades=253 Gate=fail
- sweep_plus_bos/hardened_C: Sharpe=0.147 DD=14.7% Trades=195 Gate=fail
- bos_continuation_only/size_030_cb125: Sharpe=0.154 DD=12.7% Trades=253 Gate=fail
- sweep_plus_bos/size_030_tight_daily: Sharpe=0.054 DD=15.2% Trades=261 Gate=fail
- sweep_plus_bos/size_030: Sharpe=0.034 DD=15.8% Trades=470 Gate=fail
