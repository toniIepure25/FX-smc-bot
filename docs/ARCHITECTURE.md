# Architecture Overview

## Mission

Professional quantitative FX strategy lab that formalizes SMC/ICT concepts into systematic signals, supports institutional-grade risk controls, enables rigorous strategy decomposition, and provides deployment-ready paper trading with full audit trails.

## System Architecture

```
                    ┌─────────────┐
                    │  YAML Config │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  AppConfig   │  (Pydantic v2)
                    │  + AlphaConfig│
                    │  + RiskConfig │
                    │  + MlConfig   │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  Data Layer  │ │  Structure   │ │    Utils     │
    │  (providers, │ │  Engine      │ │  (ATR, pips, │
    │   normalize, │ │  (swings,    │ │   sessions)  │
    │   Parquet)   │ │   BOS/CHoCH) │ └─────────────┘
    └──────┬──────┘ └──────┬──────┘
           │               │
           │        ┌──────▼──────┐
           │        │  Alpha Layer │  ◄── config-driven
           │        │  (candidates,│      detector selection
           │        │   scoring,   │      (ablation-ready)
           │        │   families,  │
           │        │   baselines) │
           │        └──────┬──────┘
           │               │
    ┌──────┼───────────────┤
    │      │        ┌──────▼──────┐
    │      │        │  Portfolio   │◄── Risk Layer
    │      │        │  (selector,  │    (constraints, exposure,
    │      │        │   allocator) │     lockout, diagnostics)
    │      │        └──────┬──────┘
    │      │               │
    │      │        ┌──────▼──────┐
    │      └───────►│  Execution   │
    │               │  (fills,     │
    │               │   slippage)  │
    │               └──────┬──────┘
    │                      │
    │          ┌───────────┼───────────┐
    │          │                       │
    │   ┌──────▼──────┐        ┌──────▼──────┐
    └──►│  Backtest    │        │  Live Layer  │
        │  Engine      │        │  (PaperBroker│
        │  + regime    │        │   Journal,   │
        │    tagging   │        │   State,     │
        └──────┬──────┘        │   Runner)    │
               │               └──────┬──────┘
        ┌──────▼──────┐               │
        │  Research    │◄──────────────┘
        │  (ablation,  │
        │   campaigns, │
        │   scores,    │
        │   reporting) │
        └──────┬──────┘
               │
        ┌──────▼──────┐
        │  ML Layer    │  (optional)
        │  (regime,    │
        │   microstruct│
        │   features)  │
        └─────────────┘
```

## Package Structure

- **config.py** — `AppConfig` with `AlphaConfig`, `RiskConfig`, `ExecutionConfig`, `MlConfig`, `OperationalState` enum
- **domain.py** — ~35 domain types including `ClosedTrade` with `regime` field for regime-tagged analytics
- **data/** — BarSeries model, CSV/Parquet providers, Dukascopy, normalizer, manifest, diagnostics
- **structure/** — SMC primitives: swings, BOS/CHoCH, liquidity pools, displacement, FVG, order blocks, sessions
- **alpha/** — Config-driven candidate generation with detector registry, scoring with configurable weights, baselines
- **risk/** — Sizing, constraints (currency exposure, directional concentration, daily stop lockout, daily trade limit), drawdown with operational state machine, portfolio diagnostics
- **portfolio/** — Selection, multi-strategy allocation (equal risk, score-weighted, capped conviction)
- **execution/** — Fill simulation (conservative/optimistic/random), slippage models (fixed, volatility, data-driven)
- **backtesting/** — Event-driven engine with regime tagging, trade ledger, metrics, attribution with interaction dimensions
- **ml/** — Regime classifiers (volatility, trend/range, spread, composite), microstructure proxies (bar efficiency, wick asymmetry, spread stress, volatility compression, directional persistence)
- **research/** — Ablation runner (family/scoring/filter), campaign orchestration (config sweep, baseline-vs-SMC, walk-forward), research quality scores, experiment registry, evaluation with regime/interaction dimensions
- **live/** — BrokerAdapter protocol, PaperBroker, EventJournal (JSONL audit log), LiveState persistence, PaperTradingRunner, AlertSink protocol
- **utils/** — ATR, pip math, session time helpers, logging

## Data Pipeline

```
data/raw/          ← Downloaded CSVs (Dukascopy, MT4, generic)
data/interim/      ← Normalized CSVs
data/processed/    ← Final Parquet files (canonical schema)
  EURUSD/
    1m.parquet     ← Base resolution
    15m.parquet    ← Resampled
    1h.parquet
    4h.parquet
  manifest.json    ← Dataset metadata
```

## Operational Risk State Machine

```
ACTIVE → THROTTLED → LOCKED → STOPPED
  ↑         ↑
  └─────────┘  (new day resets LOCKED → ACTIVE)
```

- **ACTIVE**: Full trading, throttle factor = 1.0
- **THROTTLED**: Approaching DD limits, sizing reduced
- **LOCKED**: Daily loss limit hit, no new trades
- **STOPPED**: Manual/emergency stop

## Strategy Decomposition

The `AlphaConfig.enabled_families` field controls which detector classes are active:

```yaml
alpha:
  enabled_families: [sweep_reversal, bos_continuation, fvg_retrace]
  scoring_weights: [0.5, 0.3, 0.2]
  min_signal_score: 0.15
```

The ablation runner systematically tests each family in isolation, leave-one-out, and full stack.

## Paper Trading Architecture

```
Data (Parquet) → PaperTradingRunner → PaperBroker → EventJournal
                       ↓                    ↓
                 Signal Engine          FillEngine
                 Risk/Portfolio         State Persistence
```

The `BrokerAdapter` protocol enables swapping `PaperBroker` for a real broker implementation.

## Key Design Decisions

1. **NumPy for hot paths, DataFrames for I/O**
2. **Protocols for all interfaces**: `BrokerAdapter`, `SlippageModel`, `SizingStrategy`, `ConstraintChecker`, `SetupDetector`, `RegimeClassifier`, `AlertSink`
3. **Config-driven ablation**: Detector selection, scoring weights, and filter thresholds all configurable for systematic decomposition
4. **Event-driven simulation**: Same signal/risk/portfolio loop for both backtest and paper trading
5. **Operational risk state machine**: Drawdown tracker manages ACTIVE/THROTTLED/LOCKED/STOPPED states
6. **Regime tagging on every trade**: `ClosedTrade.regime` field enables regime-dimensional evaluation
7. **Append-only audit journal**: JSONL event log for full signal-to-fill traceability
8. **Research quality scores**: Quantitative go/no-go diagnostics (stability, robustness, simplicity, OOS consistency, diversification)

## Non-goals (current phase)

- Full UI/dashboard
- Deep learning from raw candles
- Reinforcement learning
