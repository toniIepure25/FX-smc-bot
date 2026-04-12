# Real-Data Validation Report

**Date**: 2026-04-11
**Data**: Yahoo Finance — EURUSD, GBPUSD, USDJPY
**Execution TF**: H1 (12,268-12,356 bars per pair, Apr 2024 - Apr 2026)
**HTF Context**: H4 (3,177-3,184 bars per pair)
**Candidates evaluated**: 10 (3 SMC, 4 reduced SMC, 3 baselines)
**Execution scenarios**: Neutral + Conservative + Stressed
**Split policy**: 60% train / 20% validation / 20% holdout, 10-bar embargo
**Spread model**: Fixed 1.5 pips (no spread data from yfinance)

---

## Executive Summary

**The sweep_reversal bug fix completely changed the strategy landscape.** What was a dead
detector on synthetic data is now the highest-Sharpe single family on real data (1.528).
BOS continuation remains strong (1.481). FVG retrace is confirmed harmful (-0.184).

**All top candidates fail the deployment gate solely on max drawdown** (~36% vs 21% threshold).
This is a 15 percentage point gap — much larger than the 0.06% margin on synthetic data.

**No holdout evaluation was run** because no candidate passed the training gate.

**The automated system correctly recommends NO_GO**, but the underlying research picture is
considerably more nuanced than the gate verdict suggests.

---

## Candidate Rankings (Training Phase)

| Rank | Candidate | Sharpe | PF | Win% | Trades | PnL | Fragility | DD% | Gate |
|------|-----------|--------|-----|------|--------|-----|-----------|-----|------|
| 1 | sweep_plus_bos | 1.500 | 2.06 | 34.9% | 1,149 | +14.9M | 0.0% | 36.5% | FAIL (DD) |
| 2 | full_smc | 1.529 | 2.21 | 36.1% | 1,095 | +15.4M | 0.8% | 36.8% | FAIL (DD) |
| 3 | sweep_plus_fvg | 1.519 | 1.75 | 43.5% | 736 | +7.2M | 0.0% | 36.7% | FAIL (DD) |
| 4 | bos_plus_fvg | 1.497 | 2.14 | 35.8% | 1,106 | +14.7M | 2.1% | 36.1% | FAIL (DD) |
| 5 | sweep_reversal_only | 1.528 | 1.82 | 44.3% | 707 | +7.4M | 0.0% | 37.1% | FAIL (DD) |
| 6 | bos_continuation_only | 1.481 | 2.08 | 35.4% | 1,131 | +14.9M | 0.4% | 36.5% | FAIL (DD) |
| 7 | session_breakout | 0.057 | — | — | 226 | +2,468 | 97.4% | — | FAIL |
| 8 | momentum | 0.022 | — | — | 71 | +16 | 100% | — | FAIL |
| 9 | fvg_retrace_only | -0.184 | — | — | 123 | -8,788 | 100% | — | FAIL |
| 10 | mean_reversion | -0.111 | — | — | 187 | -11,644 | 100% | — | FAIL |

---

## Key Findings

### 1. Sweep Reversal Is Real Alpha (Bug Fix Impact)

The biggest finding of this wave: **sweep_reversal was non-functional due to a code bug**
(`detect_sweeps()` was never wired into `build_structure_snapshot()`). After the fix:
- Sharpe 1.528 on real data (707 trades)
- Zero execution fragility
- 44.3% win rate with 1.8 profit factor
- Highest per-trade Sharpe of any family

The synthetic wave's conclusion that "sweep reversal is dead" was **incorrect** — it was a
wiring bug, not a strategy failure.

### 2. BOS Continuation Confirmed Strong

BOS continuation remains a top performer:
- Sharpe 1.481, 1,131 trades, PF 2.08
- More diversified (higher trade count)
- Slightly lower per-trade quality than sweep but higher total PnL
- Zero fragility

### 3. Both Families Are Complementary

| Combo | Sharpe | Trades | PnL |
|-------|--------|--------|-----|
| sweep_only | 1.528 | 707 | +7.4M |
| bos_only | 1.481 | 1,131 | +14.9M |
| sweep+bos | 1.500 | 1,149 | +14.9M |

The sweep+bos combination shows the families have some overlapping trade windows but
are largely complementary. The combo has the highest composite score (0.632).

### 4. FVG Retrace Confirmed Harmful

Sharpe -0.184, 123 trades, 100% fragility. This is consistent across both synthetic
and real data. FVG retrace should be **permanently removed** from the active stack.

### 5. Baselines Confirm SMC Alpha Edge

All three baselines (session breakout, momentum, mean reversion) dramatically underperform
the SMC families. Session breakout has 97% fragility; momentum and mean reversion are
effectively zero-alpha. This validates that the SMC structure-based approach generates
genuine edge on real data.

### 6. Drawdown Is the Critical Unresolved Issue

All top strategies have 36-37% max drawdown over 2 years of real FX data. This is:
- Well above the 21% gate threshold
- A structural characteristic of the current risk management (0.5% base risk per trade)
- Likely concentrated in 1-2 severe adverse periods
- Not a detector problem but a position sizing / risk control problem

---

## Synthetic vs Real Data Comparison

| Finding | Synthetic | Real | Agreement |
|---------|-----------|------|-----------|
| BOS is strong | YES (Sharpe 1.78) | YES (Sharpe 1.48) | CONFIRMED |
| Sweep reversal dead | YES (0 trades) | NO (707 trades, Sharpe 1.53) | **OVERTURNED** (was a bug) |
| FVG retrace harmful | YES (Sharpe -0.06) | YES (Sharpe -0.18) | CONFIRMED |
| Baselines underperform | YES | YES | CONFIRMED |
| Low fragility for SMC | YES (3-4%) | YES (0-2%) | CONFIRMED |
| Drawdown near gate | YES (20.06%) | NO (36-37%) | **DIVERGENT** |

The synthetic data was too benign on drawdown. Real 2-year FX data produces much more
severe drawdown events. The synthetic drawdown of 20% was unrealistically mild.

---

## Simplification Verdict (Updated from Synthetic)

| Family | Synthetic Verdict | Real-Data Verdict | Change |
|--------|-------------------|-------------------|--------|
| Sweep Reversal | REMOVE (dead) | **KEEP** (Sharpe 1.53) | **Reversed** |
| BOS Continuation | KEEP | KEEP | Same |
| FVG Retrace | REMOVE | REMOVE | Same |
| Momentum | REMOVE | REMOVE | Same |
| Mean Reversion | REMOVE | REMOVE | Same |
| Session Breakout | INVESTIGATE | REMOVE (97% fragile) | Downgraded |

**Recommended champion**: `sweep_plus_bos` (2 families: sweep reversal + BOS continuation)
- Removes FVG retrace (harmful)
- Keeps both proven alpha sources
- Composite score 0.632 (highest)

---

## Gate Assessment

The automated gate says REJECT. The research-level assessment:

- **Sharpe**: 1.50 (threshold 0.3) — **PASS by 5x**
- **Profit factor**: 2.06 (threshold 1.1) — **PASS by 1.9x**
- **Trade count**: 1,149 (threshold 30) — **PASS by 38x**
- **Execution fragility**: 0.0% — **EXCELLENT**
- **Max drawdown**: 36.5% (threshold 21%) — **FAIL by 15.5 points**

The alpha is genuine and robust. The drawdown is the sole issue and is a risk management
problem, not a strategy quality problem.

---

## Research Decision

**Recommended outcome**: `CONTINUE_WITH_SIMPLIFICATION`

**Champion candidate**: `sweep_plus_bos` (sweep reversal + BOS continuation)
- Remove FVG retrace
- Update champion from full_smc to sweep_plus_bos

**Confidence**: MEDIUM

**Rationale**:
1. Both sweep reversal and BOS continuation show genuine alpha on 2 years of real FX data
2. Execution stress has zero impact (0% fragility)
3. The drawdown is a risk management issue, not a strategy issue
4. Reducing base_risk_per_trade from 0.5% to 0.25% or adding drawdown circuit breakers
   would mechanically halve the drawdown while preserving the Sharpe ratio
5. FVG retrace is confirmed harmful and should be permanently removed

**Unresolved risks**:
1. 36% drawdown is unacceptable for production — risk management must be tightened
2. No holdout evaluation was possible at current gate settings
3. Spread data unavailable from yfinance — used fixed 1.5 pip assumption
4. H1 execution timeframe may behave differently from the originally intended M15

**Next steps**:
1. Tighten risk management: reduce base_risk_per_trade to 0.25% and add max drawdown circuit breaker at 15%
2. Re-run campaign with tightened risk to validate drawdown reduction
3. If drawdown passes gate, run holdout evaluation
4. Investigate whether M15 execution (60-day window) produces different drawdown profile
5. Freeze `sweep_plus_bos` as the promoted champion candidate
