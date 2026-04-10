# FX-smc-bot

Professional quantitative FX strategy lab for systematic SMC/ICT signal formalization, portfolio-aware risk allocation, realistic execution modeling, strategy decomposition, paper trading, and robust research validation.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Generate synthetic data (M1 base + resampled to all TFs)
python scripts/download_data.py --mode generate --output-dir data/processed

# Run backtest
python scripts/run_backtest.py --data-dir data/processed --output-dir results/ --label my_run

# Run ablation study (which families add value?)
python scripts/run_campaign.py ablation --data-dir data/processed --type family

# Compare baselines vs SMC
python scripts/run_campaign.py baseline_vs_smc --data-dir data/processed

# Walk-forward validation
python scripts/run_campaign.py walk_forward --data-dir data/processed --splits 5

# Paper trading replay
python scripts/run_paper.py --data-dir data/processed --output-dir paper_runs

# Run tests (144 tests)
python -m pytest tests/ -v
```

## Architecture

| Package | Purpose |
|---------|---------|
| `data/` | Multi-format ingestion, Parquet pipeline, normalization, diagnostics, manifest |
| `structure/` | SMC primitives: swings, BOS/CHoCH, FVG, OB, liquidity |
| `alpha/` | Config-driven candidate generation, scoring, setup families, baselines |
| `risk/` | Sizing, constraints (currency exposure, daily stop, lockout), drawdown, portfolio diagnostics |
| `portfolio/` | Selection, multi-strategy allocation (equal risk, score-weighted, capped conviction) |
| `execution/` | Fill simulation with configurable policies, slippage models |
| `backtesting/` | Event-driven engine with regime tagging, metrics, multi-dimensional attribution |
| `ml/` | Regime classifiers (volatility, trend/range, spread, composite), microstructure proxies |
| `research/` | Ablation, campaigns, walk-forward, quality scores, experiment registry, reporting |
| `live/` | Paper broker, event journal, state persistence, alerts, paper trading runner |
| `utils/` | ATR, pip math, session times, logging |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## Strategy Decomposition

Config-driven alpha selection enables systematic ablation:

```bash
# Which setup families add value?
python scripts/run_campaign.py ablation --data-dir data/processed --type family

# Scoring weight sensitivity
python scripts/run_campaign.py ablation --data-dir data/processed --type scoring

# Filter threshold sweeps
python scripts/run_campaign.py ablation --data-dir data/processed --type filter
```

## Risk Model

Institutional-grade risk controls:

- **Currency exposure limits** per base/quote currency
- **Directional concentration** caps
- **Daily loss lockout** with operational state machine (ACTIVE → THROTTLED → LOCKED → STOPPED)
- **Consecutive-loss dampening**
- **Multiple allocation strategies**: equal risk, score-weighted, capped conviction

See [docs/RISK_MODEL.md](docs/RISK_MODEL.md).

## Regime Analytics

Every trade is tagged with its market regime at close time:

- Volatility regime (low/normal/high)
- Trend/range classification
- Spread regime (tight/normal/wide)
- Microstructure proxies: bar efficiency, wick asymmetry, spread stress, vol compression, directional persistence
- Interaction effects: pair × regime, family × regime

## Paper Trading

```bash
python scripts/run_paper.py --data-dir data/processed --output-dir paper_runs
```

Produces:
- `journal.jsonl` — Full audit trail (signals, orders, fills, state transitions)
- `state.json` — Resumable session state

See [docs/PAPER_TRADING_GUIDE.md](docs/PAPER_TRADING_GUIDE.md).

## Research Quality Scores

Quantitative confidence metrics for deployment decisions:

| Score | Measures |
|-------|----------|
| Stability | Consistency across time periods |
| Robustness | Survival under cost stress |
| Simplicity | Whether complexity is justified |
| OOS Consistency | In-sample vs out-of-sample ratio |
| Diversification | Balance across pairs/directions/families |
| Deployment Readiness | Composite go/no-go |

## Documentation

| Document | Content |
|----------|---------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture and design decisions |
| [DATA_GUIDE.md](docs/DATA_GUIDE.md) | Data pipeline and formats |
| [RISK_MODEL.md](docs/RISK_MODEL.md) | Constraint hierarchy and exposure budgeting |
| [RESEARCH_METHODOLOGY.md](docs/RESEARCH_METHODOLOGY.md) | Ablation, walk-forward, robustness methodology |
| [PAPER_TRADING_GUIDE.md](docs/PAPER_TRADING_GUIDE.md) | Paper broker setup and operational controls |
| [VALIDATION_GUIDE.md](docs/VALIDATION_GUIDE.md) | OOS discipline and go/no-go criteria |
| [EXPERIMENT_PLAYBOOK.md](docs/EXPERIMENT_PLAYBOOK.md) | Step-by-step experiment recipes |

## Configuration

All parameters are controlled via YAML configs in `configs/`. Key config sections:

- `alpha` — Enabled families, scoring weights, min score, slippage/sizer model
- `risk` — Position limits, currency exposure, daily stop, allocation strategy
- `execution` — Fill policy, spread, slippage factors
- `ml` — Regime tagging, quality model toggles
