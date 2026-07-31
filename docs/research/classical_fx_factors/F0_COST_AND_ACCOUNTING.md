# Gate F.0 Cost and Accounting

All primary results for `FX_CLASSICAL_RISK_PREMIA_V1` must be net of executable
costs. The closed SMC and quant-polarity lineages supply no trades or cost rows.

## Required return components

Daily portfolio accounting must separately record and reconcile:

- executable bid/ask spread;
- configured commission;
- configured slippage;
- overnight financing return;
- broker financing markup cost;
- multi-day rollover;
- turnover;
- currency conversion;
- gross trading PnL and net portfolio return.

Execution must use the correct bid or ask for trade direction. Zero spread,
slippage, or financing assumptions are forbidden.

## Frozen scenarios

| Scenario | Spread and slippage | Commission | Annual financing markup |
|---|---:|---|---:|
| base | Actual / configured | Configured | 0.50% |
| stress_1 | 1.5x base | Configured | 1.00% |
| stress_2 | 2.0x base | Configured | 1.50% |

Only spread and slippage multipliers change under execution stress. Commission
remains configured; financing uses the scenario-specific markup.

## Reconciliation invariants

The engine must pass daily NAV, position, cash, currency-leg, cost, and
gross-to-net return reconciliation. For each day:

```text
net PnL =
gross PnL
+ financing return
- spread cost
- commission cost
- slippage cost
- financing markup cost
- currency-conversion cost
```

Multi-day financing must use the actual financed calendar days. Unexplained PnL
has zero tolerance; any nonzero residual is an execution/accounting failure and
requires an applicable blocking decision. This document contains no cost or PnL
result.
