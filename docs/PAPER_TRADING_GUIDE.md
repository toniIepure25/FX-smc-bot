# Paper Trading Guide

## Overview

The paper trading system replays real market data through a simulated broker, using the same signal generation, risk management, and portfolio logic as the backtester. It produces a complete audit trail for review.

## Architecture

```
Real Data (Parquet) → PaperTradingRunner → PaperBroker → EventJournal
                            ↓                    ↓
                     Signal Engine          FillEngine
                     Risk/Portfolio         State Persistence
```

### Key Components

- **PaperBroker**: Implements `BrokerAdapter` protocol. Manages orders, positions, and fills using the existing `FillEngine`.
- **EventJournal**: Append-only JSONL log recording every signal, order, fill, and state transition.
- **LiveState**: Serializable session state for restart/resume support.
- **AlertSink**: Extensible alert interface (logging, collecting, custom).

## Running Paper Trading

```bash
python scripts/run_paper.py --data-dir data/processed --output-dir paper_runs
```

### Options

| Flag | Description |
|------|-------------|
| `--data-dir` | Path to processed Parquet data (required) |
| `--output-dir` | Output directory for run artifacts |
| `--config` | YAML config override file |
| `--pairs` | Specific pairs to trade |

## Output Artifacts

Each paper trading run creates a directory under `paper_runs/{run_id}/`:

- `journal.jsonl` — Complete event log (signals, orders, fills, alerts)
- `state.json` — Latest session state snapshot

## Operational Risk States

| State | Meaning | Behavior |
|-------|---------|----------|
| ACTIVE | Normal operation | Full trading permitted |
| THROTTLED | Approaching risk limits | Reduced position sizing |
| LOCKED | Daily loss limit hit | No new trades until next day |
| STOPPED | Manual/emergency stop | No trading until manual restart |

## State Persistence

State is checkpointed every 500 bars and at run completion. The state file contains:

- Run ID and timestamp
- Current equity and cash
- Bars processed
- Operational state
- Consecutive loss count

## Extending for Live Trading

The `BrokerAdapter` protocol can be implemented for real broker APIs:

```python
class InteractiveBrokerAdapter:
    def submit_order(self, order: Order) -> str: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_positions(self) -> list[Position]: ...
    def get_account(self) -> AccountState: ...
    def process_bar(self, pair, o, h, l, c, timestamp) -> list[Fill]: ...
```
