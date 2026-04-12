# Paper Stage Metrics Specification

## Candidate: bos_only_usdjpy

All metrics are computed and reported at daily and weekly granularity.

---

## Core Performance Metrics

| Metric | Frequency | Source | Expected Range |
|--------|-----------|--------|----------------|
| Daily PnL | Daily | Journal trades | Variable |
| Cumulative PnL | Daily | Running sum | Positive trend expected |
| Running Sharpe (annualized) | Weekly | Daily returns * sqrt(252) | 0.3-1.5 |
| Profit Factor | Weekly | Sum(wins) / Sum(losses) | > 1.1 |
| Win Rate | Weekly | Wins / Total closed | 22-38% |
| Average Win | Weekly | Mean of winning trades | > 2x average loss |
| Average Loss | Weekly | Mean of losing trades | Bounded by risk per trade |
| Win/Loss Ratio | Weekly | Avg Win / Avg Loss | > 2.0 |
| Calmar Ratio | Weekly | Return / MaxDD | > 0.5 |

## Trade Activity Metrics

| Metric | Frequency | Expected Range |
|--------|-----------|----------------|
| Trades opened | Daily/Weekly | 1-3 per day, 5-12 per week |
| Trades closed | Daily/Weekly | Matches opened with lag |
| Signals generated | Daily | 2-10 per day |
| Signals rejected | Daily | Variable |
| Signal-to-trade ratio | Weekly | 30-70% |
| Rejection reason breakdown | Weekly | Categorized counts |

## Risk State Metrics

| Metric | Frequency | Concern Threshold |
|--------|-----------|-------------------|
| Peak-to-trough drawdown | Daily | > 10% warn, > 15% halt |
| Circuit breaker proximity | Daily | > 80% escalate |
| Throttle activations | Daily | > 2/day warn |
| Lockout activations | Daily | Any = escalate |
| Risk utilization | Daily | > 90% warn |
| Operational state | Daily | Must be ACTIVE |

## Discrepancy Metrics

| Metric | Frequency | Source |
|--------|-----------|--------|
| Paper vs backtest trade count ratio | Weekly | Compare to holdout (220 trades over holdout period) |
| Paper vs backtest signal frequency | Weekly | Signal count per period |
| Paper vs backtest win rate delta | Weekly | Absolute difference |
| Spread discrepancy | Weekly | Paper fills vs config assumption |
| PnL discrepancy (cumulative) | Weekly | Paper PnL vs scaled backtest PnL |

## Streak and Distribution Metrics

| Metric | Frequency | Concern Threshold |
|--------|-----------|-------------------|
| Current win streak | Daily | — |
| Current loss streak | Daily | > 8 consecutive losses = warn |
| Max loss streak | Weekly | > 12 = investigate |
| Trade duration distribution | Weekly | Compare to backtest |
| PnL per trade distribution | Weekly | Compare to backtest |

---

## Backtest Baselines for Comparison

These are the holdout-period baselines from the promotion gate evaluation:

| Metric | Holdout Baseline |
|--------|-----------------|
| Sharpe (annualized) | 0.850 |
| Profit Factor | 1.96 |
| Win Rate | 29.1% |
| Max Drawdown | 12.6% |
| Total Trades (holdout period) | 220 |
| OOS Mean Sharpe (27 folds) | 1.599 |

---

## Weekly Metrics JSON Schema

```json
{
  "week": "2026-W16",
  "period": "week_1",
  "trades_opened": 8,
  "trades_closed": 7,
  "signals_generated": 22,
  "signals_rejected": 14,
  "weekly_pnl": 1250.50,
  "cumulative_pnl": 1250.50,
  "running_sharpe": 0.45,
  "win_rate": 0.286,
  "profit_factor": 1.65,
  "max_drawdown_pct": 0.038,
  "avg_win": 850.00,
  "avg_loss": -420.00,
  "max_loss_streak": 3,
  "throttle_activations": 0,
  "lockout_activations": 0,
  "circuit_breaker_proximity": 0.15,
  "operational_incidents": [],
  "verdict": "CONTINUE"
}
```
