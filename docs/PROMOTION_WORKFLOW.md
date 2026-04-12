# Promotion Workflow

## State Machine

```
RESEARCH -> CANDIDATE -> PAPER_TESTING -> APPROVED
              |              |
              v              v
          REJECTED       REJECTED
              |
              v
          RESEARCH (re-enter)
```

Any state except RETIRED can transition to RETIRED.

## Stage Definitions

### RESEARCH
Initial exploration with mutable configs. No holdout access. Results are informational only.

### CANDIDATE
Config is frozen (`FrozenCandidate`). Evaluated on training data with stress testing and gating. Must pass deployment gate to progress.

### PAPER_TESTING
Shortlisted candidates run through a paper trading campaign on holdout data. Discrepancy between paper and backtest must stay below 5% (configurable).

### APPROVED
Champion strategy cleared for live deployment. Config hash locked and validated before every run.

### REJECTED
Failed a gate or showed unacceptable fragility/overfitting. Can re-enter RESEARCH.

### RETIRED
Permanently decommissioned. No transitions out.

## Promotion Requirements

| Transition | Requirements |
|------------|-------------|
| RESEARCH -> CANDIDATE | Frozen config with valid hash, assumptions documented |
| CANDIDATE -> PAPER_TESTING | Pass or conditional-pass on deployment gate |
| PAPER_TESTING -> APPROVED | Paper-vs-backtest discrepancy < threshold, holdout gate pass |
| Any -> REJECTED | Gate failure, high fragility, or manual decision |

## Anti-Overfitting Safeguards

- `OverfittingGuard` warns when variant count exceeds evidence
- Holdout data is never seen during RESEARCH or CANDIDATE stages
- Config hash is re-validated before every evaluation
- Data split embargo prevents information leakage
