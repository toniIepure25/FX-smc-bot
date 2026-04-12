# Discrepancy Monitoring Specification

## Candidate: bos_only_usdjpy

Discrepancy tracking compares paper-trading behavior against backtest expectations
to detect when the live environment diverges from research conditions.

---

## What "Discrepancy" Means

A discrepancy is a measurable difference between:
- **Paper trading results** (actual signals, fills, PnL in the paper environment)
- **Backtest expectations** (holdout metrics, signal funnel statistics from research)

Small discrepancies are expected due to:
- Bar-by-bar vs batch processing differences
- Fill timing differences
- Spread model vs actual spread differences
- State management differences

Large discrepancies indicate potential problems:
- Strategy logic not behaving as tested
- Data feed differences affecting signal generation
- Execution environment introducing unexpected friction
- Market regime has changed since the holdout period

---

## Discrepancy Metrics

### Signal Frequency Discrepancy
- **Measure**: (Paper signals/week) / (Expected signals/week from backtest)
- **Expected baseline**: 5-12 trades/week (derived from 220 holdout trades)
- **Warning**: Ratio < 0.5 or > 2.0
- **Block**: Ratio < 0.3 or > 3.0 sustained for 2 weeks

### Win Rate Discrepancy
- **Measure**: |Paper WR - Backtest WR|
- **Expected baseline**: 29.1% (holdout)
- **Warning**: Delta > 8 percentage points
- **Block**: Delta > 15 percentage points sustained for 3 weeks

### PnL Discrepancy
- **Measure**: Paper cumulative PnL vs pro-rated backtest PnL expectation
- **Warning**: > 40% deviation from expected trajectory
- **Block**: > 60% deviation sustained for 2 consecutive review periods

### Execution Discrepancy
- **Measure**: Paper average fill slippage vs configured slippage_pips (0.5)
- **Warning**: Paper fills consistently 2x wider than configured
- **Block**: Paper fills consistently 3x wider

---

## Discrepancy Thresholds

| Metric | OK | Warning | Block |
|--------|-----|---------|-------|
| Signal frequency ratio | 0.5-2.0 | 0.3-0.5 or 2.0-3.0 | < 0.3 or > 3.0 |
| Win rate delta | < 8pp | 8-15pp | > 15pp |
| PnL trajectory deviation | < 40% | 40-60% | > 60% |
| Fill slippage ratio | < 2x | 2-3x | > 3x |

---

## Discrepancy Trend Tracking

At each weekly review, compute:
1. Current discrepancy values for all metrics above
2. Direction of change vs prior week (improving / stable / worsening)
3. Number of consecutive weeks each metric has been in warning or block

A metric that stays in WARNING for 3 consecutive weeks should be treated as a BLOCK.

---

## Discrepancy Response Actions

| Level | Action |
|-------|--------|
| All OK | Standard weekly review |
| 1 metric in WARNING | Document, increase monitoring for that metric |
| 2+ metrics in WARNING | Escalate, consider shortening review interval |
| Any metric in BLOCK | Escalate, consider suspension |
| BLOCK sustained 2 weeks | Suspend paper trading |
