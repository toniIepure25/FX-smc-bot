# Gate C.2 — Runtime Integration Report

## Objective

Make the three V2 intraday SMC strategies genuinely executable through
the event-driven backtest engine and build a research-grade bid/ask
market-data acquisition pipeline.

## Architecture Implemented

### Stateful Strategy Runtime Protocol

New file: `src/fx_smc_bot/alpha/intraday/runtime.py`

```
StatefulStrategyRuntime(Protocol):
    family: str
    pair: TradingPair
    session: str
    on_bar(ctx: CausalBarContext) -> list[OrderIntent]
    on_order_accepted(event: OrderAcceptedEvent)
    on_order_filled(event: OrderFilledEvent)
    on_order_cancelled(event: OrderCancelledEvent)
    on_position_closed(event: PositionClosedEvent)
    snapshot_state() -> dict
    reset()
```

Each runtime instance is independent per strategy × pair × session.
No state is shared across pairs. Events carry full provenance IDs
linking liquidity level → strategy instance → order → fill → trade.

### V2 Runtime Factory

New file: `src/fx_smc_bot/alpha/intraday/factory.py`

Registry mapping canonical family names to runtime classes:
- `liquidity_sweep_mss_fvg_reversal` → `SweepReversalRuntime`
- `liquidity_acceptance_fvg_continuation` → `AcceptanceContinuationRuntime`
- `opening_range_displacement_fvg_retest` → `OpeningRangeRuntime`

Unknown family names raise `ValueError` — no silent fallback.

### Intraday Backtest Engine

New file: `src/fx_smc_bot/backtesting/intraday_engine.py`

Separate engine from the legacy `BacktestEngine`. Key differences:
- Maintains stateful runtime instances across bars
- Calls `runtime.on_bar(CausalBarContext)` instead of `generate_candidates()`
- Converts `OrderIntent` → engine `Order` (LIMIT type by default)
- Feeds execution events back to the originating runtime
- Tracks full cost decomposition per trade (gross_pnl, spread, commission, slippage, swap)
- Wires swap calculator for overnight positions
- Produces event-state funnels per runtime
- Reconciliation check ensures lifecycle consistency

### How V2 Strategies Now Reach the Engine

```
IntradayBacktestEngine
  ├── add_runtime(SweepReversalRuntime)
  ├── add_runtime(AcceptanceContinuationRuntime)
  ├── add_runtime(OpeningRangeLondonRuntime)
  └── add_runtime(OpeningRangeNewYorkRuntime)

Per bar:
  1. Process exits (SL/TP) → PositionClosedEvent → runtime
  2. Process pending fills → OrderFilledEvent → runtime
  3. Apply swap for overnight positions
  4. Build CausalBarContext (snapshot, ATR, spread, HTF bias)
  5. For each runtime matching this pair:
     runtime.on_bar(ctx) → list[OrderIntent]
     Each intent → LIMIT Order (activation_bar = signal_bar + 1)
     → OrderAcceptedEvent → runtime
  6. Record equity point
```

## Fixes Applied

### Pair-Specific Pip Arithmetic
- Replaced hardcoded `0.0001` in sweep_reversal.py with `self._pip_size`
- Replaced hardcoded `0.0001` in acceptance_continuation.py with `self._pip_size`
- All three detectors now accept a `pair` parameter and use `PAIR_PIP_INFO`

### Strategy-Specific Corrections
- **max_fvg_bars**: Added `DISPLACEMENT_CONFIRMED` state to sweep_reversal.
  After displacement, the detector now searches for a qualifying FVG over
  `max_fvg_bars` subsequent bars instead of only checking the displacement bar.
- **Hardcoded EURUSD**: Replaced `TradingPair.EURUSD` in opening_range.py
  with `self.pair` parameter.
- **State machine**: Added `StrategyState.DISPLACEMENT_CONFIRMED` to the
  canonical state enum.

### Cost Wiring
- Swap calculator wired into `IntradayBacktestEngine` via `_process_swap()`
- Commission deducted from PnL on position close
- Full cost decomposition tracked in `TradeRecord`

## Data Model

### BidAskBarSeries
New file: `src/fx_smc_bot/data/bidask.py`

Preserves full bid and ask OHLC independently:
- `bid_open/high/low/close`, `ask_open/high/low/close`
- Derived: `mid_open/high/low/close`, `spread_open/close`
- Validates: ask >= bid at open/close, valid OHLC per side
- `to_mid_series()` for backward compatibility

### Data Providers
New file: `src/fx_smc_bot/data/historical_providers.py`

- `DukascopyProvider`: Downloads bi5-compressed tick data, resamples to M1/M5
- `OandaProvider`: REST API v20 with bid/ask candles (requires OANDA_API_TOKEN)
- `MT5CsvImporter`: CSV import from MetaTrader 5 exports
- `cross_validate_providers()`: Compares overlapping data sources

### Executable Ablations
New file: `src/fx_smc_bot/research/ablations.py`

Each ablation resolves against actual config fields and fails loudly
for invalid paths. Produces unique config hashes per variant.

## Test Results

- **493 tests passing** (459 original + 34 new Gate C.2 tests)
- **0 Ruff errors** on all new and modified files
- **Deterministic** synthetic control campaign (hash-verified)

### New Test Categories (34 tests)
1. Pip arithmetic: EURUSD, USDJPY, GBPUSD sizes and distances
2. Runtime factory: known families, unknown family rejection
3. Session selection: independent instances per session
4. Pair identity: GBPUSD and USDJPY preserve identity
5. Config resolution: deterministic hashing, override differentiation
6. BidAsk data model: mid derivation, invariants, slicing
7. Ablations: valid apply, invalid path rejection, hash uniqueness
8. Cost configuration: commission effects, decomposition fields
9. Intraday engine: runtime execution, funnel tracking, reconciliation
10. Multi-pair: pair isolation across runtimes
11. Future-bar invariance: mutation after bar 50 doesn't change bars 0-49
12. Provider interfaces: Dukascopy, OANDA, MT5, cross-validation
