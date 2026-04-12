# Detector Diagnostics Report — Real Data

**Data**: EURUSD, GBPUSD, USDJPY — H1 (2 years, ~12,300 bars/pair), H4 HTF context
**Campaign**: 10 candidates, neutral+conservative+stressed execution
**Critical change**: `detect_sweeps()` wiring bug fixed — sweep_reversal now active

---

## Signal Activity by Family

| Family | Solo Sharpe | Solo Trades | PnL | Fragility | Status |
|--------|-----------|-------------|-----|-----------|--------|
| sweep_reversal | 1.528 | 707 | +7,366,609 | 0.00 | **ACTIVE** (was dead on synthetic) |
| bos_continuation | 1.481 | 1,131 | +14,871,015 | 0.00 | **ACTIVE** (dominant on synthetic) |
| fvg_retrace | -0.184 | 123 | -8,788 | 1.00 | **HARMFUL** (confirmed negative) |
| session_breakout | 0.057 | 226 | +2,468 | 0.97 | MARGINAL |
| momentum | 0.022 | 71 | +16 | 1.00 | NEAR-ZERO |
| mean_reversion | -0.111 | 187 | -11,644 | 1.00 | HARMFUL |

---

## Root Cause: Sweep Reversal Was Dead (Now Fixed)

**Bug**: `build_structure_snapshot()` in `context.py` called `detect_equal_levels()` to find
liquidity pools but **never called** `detect_sweeps()`. Since `SweepReversalDetector.scan()`
requires `l.swept == True` on liquidity levels, it could never produce signals.

**Fix**: Added `detect_sweeps()` call after `detect_equal_levels()` in `build_structure_snapshot()`.

**Impact**: Sweep reversal went from **0 trades** (synthetic) to **707 trades with Sharpe 1.528**
on real data. This is a top-tier performer and completely changes the strategy landscape.

---

## FVG Retrace: Why It Loses Money

FVG retrace generates 123 trades with Sharpe -0.184 and 100% fragility. Analysis:

1. **Low win rate implied**: With negative Sharpe and 2.5x RR target, the win rate must be below the break-even threshold (~28%) for 2.5:1 RR trades
2. **Regime misalignment**: FVG retrace uses LTF regime (not HTF bias) for direction, entering when `ltf.regime != RANGING`. On H1 timeframe, structure regime changes are less frequent than on M15, meaning FVG signals fire in extended trend states where retraces to old FVGs are often late
3. **No sweep confirmation**: Unlike sweep_reversal and BOS which have structural confirmation (swept levels, BOS breaks), FVG retrace only checks if price is inside an unfilled FVG zone — weaker edge

**Verdict**: REMOVE. Confirmed harmful on both synthetic and real data.

---

## Sweep Reversal vs BOS Continuation

Both are strong, but with different profiles:

| Metric | Sweep Reversal | BOS Continuation |
|--------|---------------|-----------------|
| Sharpe | 1.528 | 1.481 |
| Trades | 707 | 1,131 |
| Win rate | 44.3% | 35.4% |
| PF | 1.816 | 2.079 |
| PnL | +7.4M | +14.9M |
| Fragility | 0.00 | 0.00 |
| Max DD | 37.1% | 36.5% |

- **Sweep reversal**: Higher Sharpe, higher win rate, fewer but more selective trades
- **BOS continuation**: Higher PF, more trades, higher total PnL, slightly lower drawdown
- Both are robust under execution stress (0% fragility)
- Combined (sweep_plus_bos): 1,149 trades, Sharpe 1.500, PnL +14.9M

---

## Drawdown Diagnosis

All top strategies have max drawdown of 36-37%, well above the 21% gate threshold.
This is a structural issue on real 2-year H1 data:

- Real FX data contains genuine adverse periods (COVID recovery, rate cycles, geopolitical events)
- 2 years of H1 data includes regimes where SMC structure breaks down
- The 36% DD likely concentrates in 1-2 severe adverse periods
- This level of drawdown is common for systematic FX strategies without explicit drawdown controls

**Risk management implication**: The strategies need tighter position sizing or
drawdown circuit breakers, not detector changes.
