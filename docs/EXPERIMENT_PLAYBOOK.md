# Experiment Playbook

Step-by-step recipes for common research workflows.

## 1. Quick Backtest

```bash
python scripts/run_backtest.py --data-dir data/processed --output-dir results/quick
```

## 2. Family Ablation Study

**Question**: Which setup families add value?

```bash
python scripts/run_campaign.py ablation --data-dir data/processed --type family
```

This runs:
- All families together (baseline)
- Each family in isolation
- Each family removed (leave-one-out)

## 3. Baseline vs SMC Comparison

**Question**: Does SMC/ICT outperform simpler strategies?

```bash
python scripts/run_campaign.py baseline_vs_smc --data-dir data/processed
```

Compares full SMC stack, individual SMC families, and baselines (momentum, session breakout, mean reversion).

## 4. Walk-Forward Validation

**Question**: Does the strategy hold on unseen data?

```bash
python scripts/run_campaign.py walk_forward --data-dir data/processed --splits 5
```

## 5. Cost Sensitivity Sweep

**Question**: How fragile is performance to execution costs?

```bash
python scripts/run_campaign.py sweep --data-dir data/processed \
    --param execution.default_spread_pips --values 1.0 1.5 2.0 3.0 5.0
```

## 6. Risk Parameter Sensitivity

```bash
python scripts/run_campaign.py sweep --data-dir data/processed \
    --param risk.base_risk_per_trade --values 0.003 0.005 0.008 0.01
```

## 7. Paper Trading Run

**Question**: How would this behave in real-time?

```bash
python scripts/run_paper.py --data-dir data/processed --output-dir paper_runs
```

Review: `cat paper_runs/{run_id}/journal.jsonl | python -m json.tool`

## 8. Full Research Pipeline

```bash
# 1. Generate synthetic data (if no real data available)
python scripts/download_data.py generate --pairs EURUSD GBPUSD USDJPY --output data/processed

# 2. Run baseline comparison
python scripts/run_campaign.py baseline_vs_smc --data-dir data/processed

# 3. Run ablation
python scripts/run_campaign.py ablation --data-dir data/processed --type family

# 4. Walk-forward validation
python scripts/run_campaign.py walk_forward --data-dir data/processed --splits 5

# 5. Cost stress test
python scripts/run_campaign.py sweep --data-dir data/processed \
    --param execution.default_spread_pips --values 1.0 2.0 3.0 5.0

# 6. Paper trading simulation
python scripts/run_paper.py --data-dir data/processed
```

## Interpreting Results

### Campaign Summary Table

```
Name                                 Trades   Sharpe       PF  WinRate           PnL
-----------------------------------------------------------------------------------
full_smc                                 42    0.850     1.45    52.4%      3,241.50
momentum_only                            38    0.320     1.12    48.7%      1,105.20
```

### Key Metrics

| Metric | Good | Concerning |
|--------|------|------------|
| Sharpe | > 0.5 | < 0 |
| Profit Factor | > 1.3 | < 1.0 |
| Win Rate | > 45% | < 35% |
| Max Drawdown | < 10% | > 20% |
| OOS Consistency | > 0.5 | < 0.3 |
