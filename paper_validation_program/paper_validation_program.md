# Paper Validation Program: BOS-Only USDJPY

## Overview

This document describes the complete paper-trading validation program for the
`bos_only_usdjpy` candidate. The program runs for 4-6 weeks with structured
checkpoints, explicit invalidation criteria, and a final promotion decision.

---

## Candidate Summary

| Property | Value |
|----------|-------|
| Strategy | bos_only_usdjpy |
| Family | bos_continuation |
| Pair | USDJPY |
| Timeframe | H1 (with H4 HTF confirmation) |
| Risk per trade | 0.30% |
| Circuit breaker | 12.5% |
| Promotion gate score | 8/8 (revised gate) |
| Holdout Sharpe | 0.850 |
| OOS mean Sharpe | 1.599 (27 folds, 63% positive) |
| Confidence | low-medium |

---

## How to Run

### Starting a new paper validation session
```bash
python scripts/run_paper_validation.py
```

### Resuming an existing session
```bash
python scripts/run_paper_validation.py --resume <session_id>
```

### Creating a named checkpoint
```bash
python scripts/run_paper_validation.py --checkpoint week_2
```

### Session artifacts
All artifacts are stored in `paper_validation_program/sessions/<session_id>/`:
- `session_manifest.json` — session metadata and checkpoint history
- `runs/` — paper trading run outputs (journal, state)
- `checkpoints/` — named checkpoint directories with metrics

---

## Program Schedule

| Checkpoint | When | Purpose | Template |
|-----------|------|---------|----------|
| Day 1 | End of day 1 | Sanity check | paper_stage_checkpoints.md |
| Week 1 | Day 5 | Signal integrity | week_1_signal_integrity_review.md |
| Week 2 | Day 10 | Discrepancy review | week_2_discrepancy_review.md |
| Week 4 | Day 20 | Performance review | week_4_performance_review.md |
| Week 6 | Day 30 | Final review | week_6_final_paper_review.md |

---

## Key Documents

### Governance
- `paper_stage_checkpoints.md` — Full checkpoint schedule with pass/warn/fail
- `checkpoint_decision_matrix.md` — Exact decision logic at each checkpoint
- `paper_stage_escalation_rules.md` — Escalation levels and response protocol

### Metrics & Monitoring
- `paper_stage_metrics_spec.md` — All metrics tracked with expected ranges
- `discrepancy_monitoring_spec.md` — Paper vs backtest comparison methodology
- `risk_event_monitoring_spec.md` — Risk events tracked and thresholds
- `paper_stage_invalidation_rules.md` — Hard stops, soft warnings, continue rules

### Review Templates
- `weekly_review_template.md` — Standard weekly review form
- `week_1_signal_integrity_review.md` — Week 1 specific template
- `week_2_discrepancy_review.md` — Week 2 specific template
- `week_4_performance_review.md` — Week 4 specific template
- `week_6_final_paper_review.md` — Week 6 final review template
- `final_paper_stage_decision_template.md` — Final decision form

### Configuration
- `paper_program_manifest.json` — Machine-readable program definition
- `results/final_promotion_gate/bos_only_usdjpy_champion_bundle/champion_config.json` — Frozen config

---

## Decision Outcomes

At the end of the program, the decision will be one of:

| Decision | Meaning | Next Step |
|----------|---------|-----------|
| **PROMOTE** | Paper stage passed | Prepare live deployment |
| **EXTEND** | Need more data | Run 2-4 more weeks of paper |
| **REJECT** | Strategy failed | Archive, document failure mode |
| **HOLD** | Operational issues | Fix issues, then re-evaluate |

---

## Invalidation Summary

### Hard Stops (immediate halt)
1. Paper Sharpe < 0.0 after 4 weeks
2. Drawdown > 15%
3. Win rate < 15% (2-week window)
4. Zero signals for 5 days
5. Circuit breaker fires
6. Config fingerprint mismatch

### Soft Warnings (increased monitoring)
- Trade frequency outside 3-15/week range
- Signal rejection rate > 80%
- Win rate drift below 20% (3-week window)
- Drawdown > 10%

See `paper_stage_invalidation_rules.md` for the complete specification.
