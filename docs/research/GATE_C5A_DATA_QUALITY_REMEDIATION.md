# Gate C5-A Data Quality Remediation

## Status

Final validation decision remains:

`BLOCKED_BY_VALIDATION_DATA_QUALITY`

This remediation did not run validation event detection, outcomes, inference,
placebo analysis, strategy backtests, PnL, equity, Sharpe, or holdout access.

## Remediation Scope

- Scope: USDJPY validation acquisition quality only.
- Interval inspected for repair: 2020-01-01 through 2020-02-29.
- Sides: bid and ask.
- Holdout: not accessed.
- Raw validation market data: not committed.

## Software Finding

The daily checkpoint compaction path allowed a month to become
`compacted=true` even when all days were `failed`. For Jan/Feb 2020 USDJPY
validation partitions, that produced monthly `data.json` files containing
`[]` with `compacted_rows=0`.

The runner then treated `compacted=true` as complete, so follow-up resume/repair
attempts could skip or incorrectly count these partitions.

## Software Fix

The acquisition checkpoint logic now requires all expected days to be either
`complete` or `market_closed`, with at least one row available, before monthly
compaction is allowed.

Repair detection now treats failed days, pending days, missing days, and
zero-row business days as repairable. Existing invalid compacted manifests are
normalized back to non-compacted state before scheduling.

## Repair Attempt

Command class:

`python scripts/run_persistent_acquisition.py --pairs USDJPY --start 2020-01-01 --end 2020-02-29 --workers 4 --raw-dir data/raw/gate_c5a/dukascopy-node --state-dir data/acquisition_state/gate_c5a_repair_janfeb_v2 --log-dir logs/gate_c5a/acquisition_repair_janfeb_v2 --repair-missing`

Result:

- Total partitions: 4
- Completed: 0
- Failed: 4
- Skipped: 0
- Total rows: 0
- Max observed concurrent tasks: 4
- Workers configured: 4

## Direct Provider Probe

Direct `dukascopy-node` probes on USDJPY M1 returned `Unknown error` for:

- 2020-01-06 bid, cache disabled
- 2020-01-06 ask, cache disabled
- 2020-03-02 bid, cache disabled
- 2020-03-02 bid, cache enabled

The March probe shows the current provider/tool path is unable to fetch fresh
USDJPY M1 data during this remediation attempt, not only the Jan/Feb repair
partitions.

## Verification

- `pytest tests/test_gate_c3f/test_daily_checkpoint.py tests/test_gate_c3f/test_runner_corrected.py tests/test_gate_c5a`: PASS, 42 passed.
- `pytest tests/`: PASS, 715 passed.
- `ruff check` on touched acquisition files/tests: PASS.

## Scientific Boundary

Because the validation dataset still cannot be certified, no validation
events, controls, outcomes, inference, placebo, stability diagnostics, or
decision criteria were computed after this remediation attempt.
