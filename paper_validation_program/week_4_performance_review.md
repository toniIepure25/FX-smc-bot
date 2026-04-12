# Week 4 Performance Review

## Candidate: bos_only_usdjpy
## Period: [Start date] — [End date]

---

## Purpose

First formal go/no-go performance assessment. The key question:
**Does the strategy have positive expectancy in paper trading?**

---

## Performance Summary (4 weeks)

| Metric | Paper (4 weeks) | Holdout Baseline | OOS Distribution |
|--------|----------------|-----------------|------------------|
| Running Sharpe | __ | 0.850 | Mean 1.599 |
| Profit Factor | __ | 1.96 | — |
| Win Rate | __% | 29.1% | — |
| Total Trades | __ | 220 (holdout) | — |
| Max Drawdown | __% | 12.6% | — |
| Cumulative PnL | __ | — | — |

## Hard Stop Check

| Rule | Threshold | Current | Status |
|------|-----------|---------|--------|
| HSI-1: Sharpe < 0 at wk4 | < 0.0 | __ | PASS/FAIL |
| HSI-2: Drawdown > 15% | > 15% | __% | PASS/FAIL |
| HSI-3: Win rate < 15% (2wk) | < 15% | __% | PASS/FAIL |
| HSI-4: Signal drought (5d) | 5 days | __ days max | PASS/FAIL |
| HSI-5: CB fires | Any | 0 / N | PASS/FAIL |

## Discrepancy Trend

| Metric | Wk 1 | Wk 2 | Wk 3 | Wk 4 | Trend |
|--------|------|------|------|------|-------|
| Trade freq ratio | __ | __ | __ | __ | ↑/→/↓ |
| Win rate delta | __ | __ | __ | __ | ↑/→/↓ |
| PnL trajectory dev | __ | __ | __ | __ | ↑/→/↓ |

## Risk Event Summary

| Category | Total (4 wks) | Trend |
|----------|--------------|-------|
| Drawdown warnings | __ | — |
| Throttle activations | __ | — |
| Lockout activations | __ | — |
| Loss streaks > 5 | __ | — |
| Operational incidents | __ | — |

## Comparison to Expectations

Based on the promotion gate evidence:
- Holdout Sharpe was 0.850 — paper should ideally be > 0.0 (minimum) to > 0.3 (good)
- OOS distribution showed 63% positive folds — a negative 4-week window is possible but concerning
- Win rate of 22-38% was expected — significant deviation needs explanation

## Week 4 Decision

- [ ] **CONTINUE** — Sharpe > 0.0, no hard stops, trade count adequate
- [ ] **CONTINUE with monitoring** — Sharpe near 0, positive trend, minor concerns
- [ ] **EXTEND** — Inconclusive, need 2 more weeks of data
- [ ] **SUSPEND** — Hard stop triggered: _______________

**Decision rationale**: _______________________________________________

**Should confidence be upgraded?**
- [ ] YES — paper confirms backtest edge (Sharpe > 0.3, low discrepancy)
- [ ] NO CHANGE — adequate but not conclusive
- [ ] DOWNGRADE — paper weaker than expected
