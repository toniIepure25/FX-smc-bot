# Intraday SMC Validation — Methods Reference

## Overview

This document describes the technical methodology for the rigorous validation of three intraday SMC/ICT strategy families implemented in this repository.

---

## 1. Strategy Families

### Strategy A: Liquidity Sweep → Reclaim → MSS → Displacement → FVG Reversal

A reversal strategy that:
1. Identifies a key liquidity level (equal highs/lows, session extremes, prior-day extremes)
2. Detects a sweep of that level (price briefly exceeds it by a minimum threshold)
3. Confirms a reclaim (price closes back inside within N bars)
4. Detects a Market Structure Shift (MSS) confirming directional change
5. Requires a displacement move (strong momentum candle)
6. Enters on a retest of a Fair Value Gap (FVG) left by the displacement

Implementation: `src/fx_smc_bot/alpha/intraday/sweep_reversal.py`

### Strategy B: Liquidity Break → Acceptance → FVG Continuation

A continuation strategy that:
1. Identifies a break of a key liquidity level
2. Confirms acceptance via N consecutive closes beyond the level
3. Waits for a retest of a displacement FVG for entry

Implementation: `src/fx_smc_bot/alpha/intraday/acceptance_continuation.py`

### Strategy C: Opening Range Displacement → FVG Retest

A breakout strategy based on time-of-day:
1. Defines a session opening range (default 30min)
2. Detects a displacement breakout from the range
3. Enters on retest of an FVG formed during the breakout

Implementation: `src/fx_smc_bot/alpha/intraday/opening_range.py`

---

## 2. Causal Architecture

All strategies are implemented as explicit state machines (`src/fx_smc_bot/alpha/intraday/state_machine.py`). Key invariants:

- **No look-ahead bias**: Each bar is processed sequentially; strategies only access data at or before the current bar index.
- **HTF causality**: Higher timeframe bars are only visible after their close time, not during formation.
- **Order filling**: Market orders fill at the next bar's open. Limit orders fill no earlier than the bar after placement.
- **Session boundaries**: DST-aware via `zoneinfo`, not fixed UTC offsets.

Verified by the leakage test suite in `tests/leakage/`.

---

## 3. Execution Model

### Spread and Slippage
- Bid/ask modeled from either real tick data or synthetic spread
- Slippage applied as additional cost at fill

### Commission
- Deducted per-lot at trade close
- Configured in YAML per strategy

### Swap/Financing
- Overnight swap calculated using per-pair long/short swap rates
- Triple swap on Wednesday (standard broker convention)
- DST-aware rollover time detection

### Same-Bar Handling
- Conservative fill policy: when both SL and TP are within a bar's range, SL is assumed hit first
- Optimistic fill policy: TP assumed hit first (used for sensitivity analysis only)

Implementation: `src/fx_smc_bot/execution/`

---

## 4. Statistical Methodology

### Bootstrap Confidence Intervals
- Stationary bootstrap (Politis & Romano, 1994) for autocorrelated return series
- Block bootstrap as fallback
- Default 5000 iterations, block length 5

### Sharpe Ratio Testing
- Probabilistic Sharpe Ratio (PSR): probability observed SR exceeds a benchmark
- Deflated Sharpe Ratio (DSR): adjusts for multiple testing across strategy variants
- Minimum Track Record Length (MTRL): minimum observations for significance

### Multiple Testing
- Holm-Bonferroni for primary hypotheses
- Benjamini-Hochberg FDR for ablation tests
- White's Reality Check for baseline comparisons

### Overfitting Detection
- Combinatorially Symmetric Cross-Validation (CSCV) Probability of Backtest Overfitting (PBO)

Implementation: `src/fx_smc_bot/research/statistical_inference.py`, `src/fx_smc_bot/research/overfitting.py`

---

## 5. Baselines and Placebos

Each strategy is compared against:
1. **Random direction**: same timestamps, random long/short
2. **Random time**: same direction logic, random entry times
3. **Signal inversion**: exact mirror of the strategy
4. **Simple momentum**: trend-following baseline using recent returns

Plus systematic ablations removing individual components:
- No MSS requirement
- No FVG requirement
- No displacement requirement
- No sweep/break requirement
- Random entry within the session
- Inverted direction
- No session filter (24-hour)
- No HTF filter

Implementation: `src/fx_smc_bot/research/placebos.py`

---

## 6. Prop-Account Simulation

Monte Carlo simulation of prop trading challenge outcomes using bootstrap resampling of actual trade returns.

Features:
- Configurable challenge profiles (balance, targets, loss limits)
- Daily and total drawdown tracking
- Consistency rule support
- Risk-per-trade grid search

Implementation: `src/fx_smc_bot/research/prop_simulation.py`

---

## 7. Data Requirements

### Minimum Data
- M1 OHLCV data for primary pairs
- 8-10 years preferred for statistical power
- Bid/ask data preferred; synthetic spread acceptable but labeled

### Data Quality
- Provenance tracking: checksums, missing intervals, duplicates
- Economic calendar for news filtering

### Sources
- Dukascopy (free tick data)
- FXCM/TrueFX (M1 bid/ask)
- MetaTrader 5 terminal export

Implementation: `src/fx_smc_bot/data/provenance.py`, `src/fx_smc_bot/data/economic_calendar.py`

---

## 8. Running a Campaign

### Step 1: Acquire Data
Download M1 data for target pairs and convert to Parquet format.

### Step 2: Validate Data Provenance
```bash
python -c "from fx_smc_bot.data.provenance import build_provenance; ..."
```

### Step 3: Run Development Campaign
```bash
python scripts/run_intraday_smc_campaign.py --strategy all --pairs EURUSD GBPUSD
```

### Step 4: Review Results
Check statistical reports in `results/intraday_smc/`.

### Step 5: Prop Simulation
```bash
python scripts/run_prop_monte_carlo.py --profile "Standard 100K Challenge"
```

---

## 9. File Map

```
configs/research/intraday_smc/
  sweep_reversal.yaml          # Strategy A frozen params
  acceptance_continuation.yaml # Strategy B frozen params
  opening_range.yaml           # Strategy C frozen params
  prop_profiles.yaml           # Prop challenge definitions

src/fx_smc_bot/
  alpha/intraday/
    state_machine.py           # Generic causal state machine
    common.py                  # Shared SMC helpers
    sweep_reversal.py          # Strategy A
    acceptance_continuation.py # Strategy B
    opening_range.py           # Strategy C
  data/
    provenance.py              # Data lineage tracking
    timezone.py                # DST-aware session boundaries
    economic_calendar.py       # News event adapter
  execution/
    fills.py                   # Fill engine + same-bar logic
    swap.py                    # Overnight swap calculator
  research/
    statistical_inference.py   # Bootstrap, PSR, DSR, VaR
    overfitting.py             # Multiple testing, PBO
    placebos.py                # Baselines and ablations
    prop_simulation.py         # Monte Carlo prop sim

tests/
  leakage/                     # Look-ahead bias tests
  alpha/intraday/              # Strategy unit tests
  test_data/                   # Data module tests
  test_execution/              # Execution tests
  test_research/               # Statistical method tests

scripts/
  run_intraday_smc_campaign.py # Campaign runner
  run_prop_monte_carlo.py      # Prop Monte Carlo runner

docs/research/
  INTRADAY_SMC_PREREGISTRATION.md  # Pre-registered hypotheses
  INTRADAY_SMC_METHODS.md          # This file
```
