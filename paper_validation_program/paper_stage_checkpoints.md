# Paper Stage Review Checkpoints

## Candidate: bos_only_usdjpy
## Schedule: 6-week program with 5 formal checkpoints

---

## Checkpoint 1: Day 1 Sanity Check

**When**: End of first trading day
**Purpose**: Confirm the system is operational and generating signals

### Required Checks
- [ ] Paper trading runner started without errors
- [ ] Config fingerprint matches frozen champion config
- [ ] At least 1 signal generated (or reasonable explanation for 0)
- [ ] No system errors in journal
- [ ] Risk parameters loaded correctly (0.30%/trade, 12.5% CB)
- [ ] USDJPY data feed active
- [ ] Journal writing to correct session directory

### Pass/Warn/Fail
| Condition | Verdict |
|-----------|---------|
| All checks pass, signals seen | **PASS** |
| System running but 0 signals | **WARN** — monitor for 48h |
| System errors or config mismatch | **FAIL** — halt and investigate |

---

## Checkpoint 2: End of Week 1 — Signal Integrity Review

**When**: End of trading day 5
**Purpose**: Verify signal generation matches backtest expectations

### Required Checks
- [ ] Total signals generated this week
- [ ] Total signals rejected and rejection reasons
- [ ] Trade count vs expected baseline (5-12 trades/week)
- [ ] No sustained signal drought (> 2 days with 0 signals)
- [ ] Signal-to-trade conversion rate recorded
- [ ] Operational state remained ACTIVE throughout
- [ ] No circuit breaker activations

### Required Artifacts
- `week_1_signal_integrity_review.md`
- `week_1_metrics.json`

### Pass/Warn/Fail
| Condition | Verdict |
|-----------|---------|
| 5-12 trades, no errors, signal funnel active | **PASS** |
| 2-4 or 13-20 trades, no errors | **WARN** — note deviation, continue |
| 0-1 trades or > 20 trades | **WARN** — investigate signal funnel |
| System errors or operational halt | **FAIL** — halt program |

---

## Checkpoint 3: End of Week 2 — Discrepancy & Signal Funnel Review

**When**: End of trading day 10
**Purpose**: First meaningful performance check and discrepancy audit

### Required Checks
- [ ] Cumulative trade count vs expected (10-24 trades over 2 weeks)
- [ ] Win rate vs expected range (22-38%)
- [ ] PnL direction (positive, flat, or slightly negative are all acceptable)
- [ ] Signal funnel comparison: paper vs backtest signal frequency
- [ ] Spread/execution discrepancy if measurable
- [ ] Drawdown path (must be < 10% for warning, < 15% for fail)
- [ ] Risk-state transitions (throttle/lockout events)
- [ ] No behavioral drift detected

### Required Artifacts
- `week_2_discrepancy_review.md`
- `week_2_metrics.json`
- `week_2_signal_funnel_summary.md`

### Pass/Warn/Fail
| Condition | Verdict |
|-----------|---------|
| Trade count in range, no hard stops triggered | **PASS** |
| Signal frequency deviation 30-50% from backtest | **WARN** — investigate |
| Drawdown > 10% | **WARN** — increase monitoring frequency |
| Signal frequency deviation > 50% | **WARN** — consider suspension |
| Drawdown > 15% or circuit breaker fires | **FAIL** — suspend |

---

## Checkpoint 4: End of Week 4 — First Performance Review

**When**: End of trading day 20
**Purpose**: First formal performance assessment with go/no-go decision

### Required Checks
- [ ] Running Sharpe estimate (must be > 0.0 to continue)
- [ ] Cumulative PnL trajectory
- [ ] Win rate over full 4-week window
- [ ] Trade count vs expected (20-48 over 4 weeks)
- [ ] Maximum drawdown experienced
- [ ] Discrepancy trend (improving, stable, or worsening)
- [ ] Risk event count (throttles, lockouts, near-CB events)
- [ ] Comparison to holdout baseline (Sharpe 0.850, PF 1.96)

### Required Artifacts
- `week_4_performance_review.md`
- `week_4_metrics.json`
- `week_4_recommendation.md`

### Pass/Warn/Fail
| Condition | Verdict |
|-----------|---------|
| Sharpe > 0.0, no hard stops, trade count adequate | **PASS** — continue to week 6 |
| Sharpe near 0 but positive trend, minor concerns | **WARN** — continue with close monitoring |
| Sharpe < 0.0 | **FAIL** — hard stop, suspend paper trading |
| Drawdown > 15% at any point | **FAIL** — hard stop |
| Win rate < 15% over any 2-week window | **FAIL** — hard stop |

### Decision
- **CONTINUE**: All major criteria met
- **EXTEND**: Borderline — extend paper period by 2 weeks
- **SUSPEND**: Hard stop triggered

---

## Checkpoint 5: End of Week 6 — Full Paper Stage Promotion Review

**When**: End of trading day 30
**Purpose**: Final assessment — promote to live, extend paper, or reject

### Required Checks
- [ ] Full 6-week Sharpe estimate
- [ ] Full 6-week PF estimate
- [ ] Full 6-week win rate
- [ ] Maximum drawdown over entire period
- [ ] Discrepancy vs backtest baseline
- [ ] Signal funnel consistency over time
- [ ] Risk event history
- [ ] Trend analysis: improving, stable, or degrading
- [ ] Comparison to OOS distribution (mean 1.599, 63% positive)

### Required Artifacts
- `week_6_final_paper_review.md`
- `week_6_metrics.json`
- `final_paper_stage_decision.md`
- `final_paper_stage_decision.json`

### Pass/Warn/Fail
| Condition | Verdict |
|-----------|---------|
| Sharpe > 0.3, trade count adequate, no major concerns | **PROMOTE** to live |
| Sharpe 0.0-0.3, positive trend, no hard stops | **EXTEND** paper by 2-4 weeks |
| Sharpe < 0.0 | **REJECT** — strategy does not translate to paper |
| Persistent discrepancy > 40% vs backtest | **REJECT** — paper/backtest divergence too high |
| Sharpe > 0.0 but major operational concerns | **HOLD** — fix issues first |
