# Risk Model

## Constraint Hierarchy

Risk is enforced at multiple levels, each acting as an independent gate:

### Per-Trade Constraints
- **Max trade risk**: Individual position risk capped at 1.5x base risk per trade
- **Minimum R:R**: Reject trades below the configured reward-risk ratio

### Per-Pair Constraints
- **Max pair positions**: Limits concurrent positions per pair
- **Currency exposure**: Net exposure per currency factor must stay within limits

### Portfolio-Level Constraints
- **Max concurrent positions**: Hard cap on total open positions
- **Max portfolio risk**: Total open risk as fraction of equity
- **Directional concentration**: Limits fraction of positions in one direction

### Operational Constraints
- **Daily trade limit**: Max trades per calendar day
- **Daily loss lockout**: Trading halted after daily loss exceeds threshold
- **Weekly drawdown throttle**: Progressive sizing reduction as weekly DD grows
- **Consecutive-loss dampening**: After N consecutive losses, sizing reduced by configurable factor

## Exposure Budgeting

Currency exposure is computed across all open positions:

- Long EURUSD = +EUR, −USD
- Short USDJPY = −USD, +JPY

The `CurrencyExposureConstraint` rejects trades that would push any currency's net exposure beyond the configured limit.

## Drawdown Management

### Throttle Factor

The throttle factor (0.0 to 1.0) reduces all position sizes proportionally:

```
throttle = min(daily_throttle, weekly_throttle) × consecutive_loss_factor
```

Where:
- `daily_throttle = 1.0 − (daily_dd / max_daily_dd)`
- `weekly_throttle = 1.0 − (weekly_dd / max_weekly_dd)`
- `consecutive_loss_factor = 0.5` after N consecutive losses

### Operational State Machine

```
ACTIVE → THROTTLED → LOCKED → STOPPED
  ↑         ↑
  └─────────┘  (new day resets LOCKED → ACTIVE)
```

## Allocation Strategies

| Strategy | Description |
|----------|-------------|
| `equal_risk` | Equal risk budget per position (default) |
| `score_weighted` | Allocate more to higher-scored signals |
| `capped_conviction` | Cap per-trade risk, redistribute excess |

## Configuration

All risk parameters are in `RiskConfig`:

```yaml
risk:
  base_risk_per_trade: 0.005
  max_portfolio_risk: 0.015
  max_daily_drawdown: 0.03
  max_weekly_drawdown: 0.06
  max_currency_exposure: 2.0
  daily_loss_lockout: 0.025
  consecutive_loss_dampen_after: 3
  allocation_strategy: equal_risk
```
