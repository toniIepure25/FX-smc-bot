# Gate F.0 Portfolio Construction

This specification applies identically to every candidate in
`FX_CLASSICAL_RISK_PREMIA_V1`. Previous lineage seals remain closed.

## Risk estimation and scaling

- Per-instrument volatility: 60-day exponentially weighted daily volatility.
- EWMA decay: `0.94`.
- Per-instrument annualized volatility target: `10%`.
- Portfolio covariance: Ledoit-Wolf shrinkage on a 252-day return window.
- Volatility and covariance inputs: lagged one trading day.
- Annualized portfolio volatility target: `10%`.

Scaling is deterministic. Candidate direction and strength are applied before
portfolio risk scaling. The fixed multi-factor candidate targets its frozen
factor risk contributions without PnL-based optimization.

## Constraints

- Maximum gross leverage: `3.0`.
- Maximum absolute instrument exposure: `0.50` portfolio NAV.
- Maximum absolute currency exposure: `1.00` portfolio NAV.

Pair notionals must be translated into base- and quote-currency legs. Currency
and instrument limits are enforced after volatility scaling and before orders.
Constraint application must be deterministic and must not reverse a signal.

## Rebalancing

Rebalance daily at the frozen execution timestamp. Do not rebalance an
instrument when required notional change is less than `5%` of its current
absolute notional target. When that target is zero, any nonzero required change
is outside the band. The threshold is not tunable.

Missing required price, spread, rate, volatility, or covariance input produces:

```text
NO_POSITION_CHANGE_WITH_RECORDED_REASON
```

Prices are never forward-filled. Official rates may be carried forward only
after publication and under the frozen rate registry. Every held or changed
position must satisfy leverage, currency-leg, timing, and accounting
reconciliations.

This is an ex-ante construction freeze and reports no portfolio outcome.
