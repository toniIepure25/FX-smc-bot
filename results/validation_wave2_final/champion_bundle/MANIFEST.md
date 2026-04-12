# Champion Strategy Manifest

**Champion**: full_smc
**Config Hash**: 87f3de347ff496c1
**Bundle Hash**: 4220e60fb2229d33
**Frozen At**: 2026-04-11T17:52:53.296007

## Metrics

- **sharpe_ratio**: 1.804224527991424
- **profit_factor**: 2.7335634868076317
- **win_rate**: 0.4433849821215733
- **total_pnl**: 2029656.7467529257
- **total_trades**: 839
- **max_drawdown_pct**: 0.20061978160518332

## Gate Result

- Verdict: conditional
- Recommendation: CONDITIONAL: passes blocking gates but warnings on robustness, diversification. Review before promoting.

## Execution Profile

- fill_policy: pessimistic
- slippage_model: volatility
- spread_model: from_data
- latency_assumption: next_bar

## Invalidation Criteria

- max_holdout_drawdown_pct: 0.25
- min_holdout_sharpe: 0.2
- max_paper_discrepancy_pct: 10.0
- max_consecutive_losing_weeks: 4
- staleness_days: 90