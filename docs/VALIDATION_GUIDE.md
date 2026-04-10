# Validation Guide

## Out-of-Sample Discipline

### Train/Test Split Rules

1. Never optimize parameters on OOS data
2. Use purged walk-forward with embargo periods
3. Compare IS vs OOS Sharpe explicitly
4. Flag strategies with > 50% OOS degradation

### Walk-Forward Protocol

```python
from fx_smc_bot.research.campaigns import run_walk_forward_campaign

report = run_walk_forward_campaign(config, data, n_splits=5)
print(report.summary_table())
```

## Go / No-Go Criteria

A strategy is considered deployment-ready when:

| Criterion | Threshold |
|-----------|-----------|
| Stability score | ≥ 0.5 |
| Robustness score | ≥ 0.4 |
| OOS consistency | ≥ 0.5 |
| Deployment readiness | ≥ 0.5 |
| Profitable at 2x costs | Yes |
| Sharpe > 0 on at least 60% of yearly periods | Yes |

## Regime-Based Evaluation

Performance must be assessed across multiple regimes:

- **Volatility regimes**: Low, normal, high
- **Trend/range regimes**: Trending up, trending down, ranging
- **Spread regimes**: Tight, normal, wide
- **Session regimes**: Asian, London, NY, Overlap

Strategies that only work in one regime should be flagged and potentially constrained to that regime.

## Interaction Effects

Cross-dimensional analysis reveals hidden dependencies:

```python
# Pair × Regime interaction
report.pair_x_regime  # e.g., EURUSD only works in trending regimes?

# Family × Regime interaction
report.family_x_regime  # e.g., FVG retrace fails in high volatility?
```

## Cost Sensitivity Validation

```python
from fx_smc_bot.research.evaluation import cost_sensitivity

points = cost_sensitivity(trades, equity_curve, initial_capital,
                          multipliers=[0.5, 1.0, 1.5, 2.0, 3.0])
```

The strategy must remain profitable at the 2x cost multiplier.

## Ablation Validation

Before deployment, validate that:

1. Each family adds measurable marginal value (leave-one-out test)
2. Removing any family does not improve overall performance significantly
3. The scoring weights are not overly sensitive to small changes
4. Filter thresholds are not on a cliff edge (small changes → large performance shifts)

## Reproducibility Checklist

- [ ] Config YAML saved with each run
- [ ] Random seed fixed and documented
- [ ] Data version/hash recorded in manifest
- [ ] Experiment registered in registry
- [ ] Artifacts saved to structured directory
