# Research Methodology

## Overview

This document describes the systematic research methodology used in the FX SMC framework. All strategy evaluation follows a rigorous process designed to minimize false confidence and maximize reproducibility.

## Strategy Decomposition

### Family-Level Ablation

Each setup family (sweep reversal, BOS continuation, FVG retrace, baselines) is evaluated:

- **Isolation**: Run each family alone to measure standalone performance
- **Leave-one-out**: Remove each family to measure marginal contribution
- **Full stack**: All families active as the baseline

This answers: "Does this family genuinely add value, or is it noise?"

### Scoring Component Ablation

The composite signal score combines structure, liquidity, and session sub-scores. Weight ablation tests:

- Equal weights vs default weights
- Each component in isolation
- Removing each component

### Filter Threshold Sweeps

Systematic variation of `min_signal_score` and `min_reward_risk_ratio` to identify optimal selectivity vs volume tradeoff.

## Walk-Forward Validation

### Protocol

1. **Anchored walk-forward**: Expanding training window with fixed-size test periods
2. **Purged splits**: Embargo period between train/test to prevent lookahead
3. **Per-fold metrics**: Sharpe, profit factor, win rate computed per fold
4. **Aggregate consistency**: Mean and std of metrics across folds

### OOS Discipline

- Never optimize on out-of-sample data
- Compare IS vs OOS Sharpe ratios explicitly
- Flag strategies with > 50% OOS degradation

## Cost Sensitivity

### Methodology

- Sweep execution cost multipliers: 0.5x, 0.75x, 1.0x, 1.5x, 2.0x, 3.0x
- Measure Sharpe, profit factor, and win rate at each level
- Strategy must remain profitable at 2x costs to be considered robust

### Fill Policy Sensitivity

- Test under CONSERVATIVE, OPTIMISTIC, and RANDOM fill policies
- Strategies that only work under OPTIMISTIC fills are flagged

## Research Quality Scores

| Score | Measures | Range |
|-------|----------|-------|
| Stability | Consistency across time (monthly/yearly) | 0-1 |
| Robustness | Survival under cost stress | 0-1 |
| Simplicity | Whether complexity adds value | 0-1 |
| OOS Consistency | IS vs OOS performance ratio | 0-1 |
| Diversification | Balance across pairs/directions/families | 0-1 |
| Deployment Readiness | Composite go/no-go score | 0-1 |

## Regime-Aware Evaluation

Performance is broken down by:

- Volatility regime (low/normal/high)
- Trend/range regime
- Spread regime
- Session (Asian/London/NY/Overlap)
- Interaction effects (pair × regime, family × regime)

## Reproducibility

- All configs serialized with each run
- Deterministic random seeds
- Experiment registry tracks every run with config hash
- Artifacts saved to structured directories
