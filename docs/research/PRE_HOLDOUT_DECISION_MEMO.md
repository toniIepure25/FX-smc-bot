# Pre-Holdout Decision Memo

**Branch**: `research/rigorous-intraday-smc-validation`
**Starting SHA**: `12f45b0`
**Audit Date**: 2026-07-13

---

## 1. Branch and Commit State

- **Current branch**: `research/rigorous-intraday-smc-validation`
- **Starting commit SHA**: `12f45b0`
- **Uncommitted files**: 7 new files (configs, docs, scripts, campaign engine, tests) + bug fixes in engine/statistical_inference/prop_simulation
- **Base branch**: `main` at `8742c93`

## 2. Test / Lint / Type-Check Results

| Tool | Result |
|------|--------|
| `python -m pytest tests/ -q` | **459 passed**, 0 failed, 0 skipped, 0 xfailed |
| Warnings | 91 DeprecationWarning (`datetime.utcnow`), 1 Pydantic serialization |
| `ruff check` (new files) | 56 cosmetic issues (line length, unused imports) |
| `ruff check` (full repo) | 1261 pre-existing cosmetic issues |
| `mypy` (research modules) | **0 errors** (4 fixed during audit) |

## 3. Data Source and Certification

**Source**: Yahoo Finance (yfinance)
**Certification**: **`REJECTED`** for final research

| Deficiency | Detail |
|------------|--------|
| No M5/M1 data | Strategies designed for M5; only M15 (3 months) and H1 (2 years) available |
| No bid/ask spread | Mid-price only; cannot certify execution realism |
| Insufficient coverage | 3 months M15 / 2 years H1 vs 8-10 year target |
| Single source | No cross-validation possible |
| Zero volume | Volume analysis impossible |

## 4. Date Split Boundaries

**Cannot be defined.** No certified real data is available at the required resolution (M5) and coverage (8-10 years).

## 5. Preregistration and Configuration Hashes

| Artifact | SHA-256 |
|----------|---------|
| `INTRADAY_SMC_PREREGISTRATION.md` | `5f41964f...` |
| `sweep_reversal.yaml` | `405b5a9a...` |
| `acceptance_continuation.yaml` | `c1d27cd7...` |
| `opening_range.yaml` | `91c1e63c...` |
| `prop_profiles.yaml` | `9bb9b7f8...` |

Full hashes in `results/pre_holdout/research_freeze.json`.

## 6. Strategies Evaluated

| Strategy | Implementation | Unit Tests | Campaign Integration |
|----------|---------------|------------|---------------------|
| Sweep Reversal (Strategy A) | Complete | 6 tests pass | **NOT WIRED** into BacktestEngine |
| Acceptance Continuation (Strategy B) | Complete | 4 tests pass | **NOT WIRED** into BacktestEngine |
| Opening Range (Strategy C) | Complete | 4 tests pass | **NOT WIRED** into BacktestEngine |

## 7. Number of Tested Variants

Zero variants have been tested in an end-to-end campaign because:
1. The V2 intraday detectors are not integrated into `generate_candidates` or `BacktestEngine`
2. No certified M5 real data is available

## 8-9. Development and Validation Results

**Not available.** Blocked by issues #6 (integration) and #3 (data).

## 10-16. Placebo, Baseline, Cost, Fill, Statistical, PBO, Parameter Results

**Not available.** All downstream analyses are blocked.

## 17. Pair/Year/Session/Regime Dependence

**Not available.**

## 18. Remaining Implementation Risks

| # | Risk | Severity | Impact |
|---|------|----------|--------|
| R1 | **V2 intraday detectors not integrated into campaign engine** | BLOCKING | No end-to-end campaign can test the actual SMC strategies |
| R2 | Swap calculator not wired into BacktestEngine | Medium | Overnight swap not deducted; affects multi-day holds |
| R3 | Ablation matrix config keys don't match strategy configs | Medium | Cannot run preregistered ablations automatically |
| R4 | `max_fvg_bars` config unused in sweep reversal | Low | No timeout between displacement and FVG detection |
| R5 | `htf_bias` unused in acceptance continuation | Low | HTF filter not applied |
| R6 | Hardcoded `TradingPair.EURUSD` in opening range | Low | Cosmetic label error |
| R7 | CSCV PBO uses random permutations, not full combinatorial | Low | Approximate PBO values |

## 19. Remaining Data Risks

| # | Risk | Severity |
|---|------|----------|
| D1 | **No M5/M1 data available** | BLOCKING |
| D2 | **No bid/ask spread data** | BLOCKING |
| D3 | Only 2 years H1 data (Yahoo) | HIGH — insufficient multi-regime coverage |
| D4 | No independent data source for cross-validation | MEDIUM |
| D5 | 27-30% missing bars in Yahoo data | LOW (mostly weekends) |

---

## 20. Gate-by-Gate Scorecard

### Implementation Gate

| Check | Status | Detail |
|-------|--------|--------|
| No unresolved material causal defect | **PASS** | Causal HTF slicing verified; leakage tests pass |
| Full test suite passes | **PASS** | 459 passed |
| Ruff passes | **PARTIAL** | Cosmetic issues only; no correctness defects |
| Mypy passes | **PASS** | 0 errors after fixes |
| No silent synthetic fallback | **PASS** | All synthetic paths are explicitly labeled |
| No unfinished HTF leakage | **PASS** | Verified by 4 dedicated leakage tests |
| No premature order activation | **PASS** | Engine fills on next bar after order creation |
| No impossible fill behavior | **PASS** | Conservative fill policy verified |
| **V2 detectors integrated into campaign** | **FAIL** | NOT WIRED — blocking |

**Implementation Gate: FAIL** (R1 blocking)

### Data Gate

| Check | Status |
|-------|--------|
| Real-data manifest complete | **FAIL** — no certified data |
| Required pairs available | **FAIL** — no M5 data |
| Time zones certified | **PARTIAL** — DST tests pass on synthetic dates |
| Dataset status appropriate | **FAIL** — REJECTED |

**Data Gate: FAIL** (D1, D2 blocking)

### Sample Gate

| Check | Status |
|-------|--------|
| ≥100 closed trades per combination | **UNKNOWN** — cannot run campaigns |
| ≥50 independent trading days | **UNKNOWN** |
| Multiple years represented | **UNKNOWN** |

**Sample Gate: UNKNOWN** (blocked)

### Economic Gate

| Check | Status |
|-------|--------|
| Positive validation net expectancy | **UNKNOWN** |
| Profit factor above threshold | **UNKNOWN** |
| Survives 1.5× cost stress | **UNKNOWN** |

**Economic Gate: UNKNOWN** (blocked)

### Statistical Gate

| Check | Status |
|-------|--------|
| PSR and DSR reported | **UNKNOWN** |
| Multiple-testing corrected | **UNKNOWN** |
| Placebo comparisons | **UNKNOWN** |

**Statistical Gate: UNKNOWN** (blocked)

### Robustness Gate

**UNKNOWN** (blocked)

### Incremental-Value Gate

**UNKNOWN** (blocked)

---

## 21. Final Decision for Each Strategy

| Strategy | Decision | Reason |
|----------|----------|--------|
| Sweep Reversal | **BLOCKED_BY_DATA_OR_IMPLEMENTATION** | V2 detector not integrated into campaign engine; no M5 bid/ask data available |
| Acceptance Continuation | **BLOCKED_BY_DATA_OR_IMPLEMENTATION** | Same as above |
| Opening Range (London) | **BLOCKED_BY_DATA_OR_IMPLEMENTATION** | Same as above |
| Opening Range (New York) | **BLOCKED_BY_DATA_OR_IMPLEMENTATION** | Same as above |

## 22. Exact Reasons

### Primary blocking issues:

1. **Integration gap (R1)**: The three intraday SMC strategy detectors (`SweepReversalDetectorV2`, `AcceptanceContinuationDetector`, `OpeningRangeDetector`) in `alpha/intraday/` are fully implemented and unit-tested, but they are NOT registered in `generate_candidates()` or wired into `BacktestEngine`. The campaign engine therefore runs the legacy `SweepReversalDetector` from `alpha/setup_families.py`, which is a different, simpler detector. No end-to-end campaign can test the actual intraday SMC strategies until this integration is completed.

2. **Data gap (D1, D2)**: No M5 or M1 bid/ask data is available. The only data is Yahoo Finance mid-price at M15 (3 months) and H1/H4 (2 years). The strategies require M5 execution timeframe with realistic spread modeling. Without certified data, no development/validation/holdout split can be defined and no statistical evaluation can be performed.

### What was accomplished:

- Complete independent implementation audit with 5 critical bugs found and fixed
- Full test suite verified (459 tests, 0 failures)
- Mypy type checking clean on research modules
- Data certification completed (REJECTED)
- Research freeze artifact generated
- All required report templates created

### What must happen before re-evaluation:

1. Wire V2 detectors into `BacktestEngine` via a dedicated intraday campaign engine or `generate_candidates` registration
2. Acquire M5 or M1 bid/ask FX data (Dukascopy, FXCM, or broker) covering ≥5 years
3. Run data quality certification
4. Define development/validation/holdout date boundaries
5. Freeze preregistration with actual dates
6. Re-run this entire pre-holdout validation gate

---

## 23. Exact Unexecuted Final-Holdout Command

```bash
# DO NOT EXECUTE — final holdout command (not yet implemented)
# Requires: certified data, integrated detectors, frozen protocol, passed dev+val gates
python scripts/run_intraday_smc_holdout.py \
    --unlock-final-holdout \
    --data-dir data/real \
    --config configs/research/intraday_smc/ \
    --preregistration docs/research/INTRADAY_SMC_PREREGISTRATION.md \
    --freeze results/pre_holdout/research_freeze.json \
    --output-dir results/final_holdout/
```

This command does not yet exist. It must be created as part of the holdout isolation implementation (Stage 18) after the blocking issues are resolved.

---

## Confirmation

- **Final holdout remained untouched**: YES — no holdout data exists, no holdout command was executed
- **No strategy thresholds were changed based on results**: YES — no results were observed
- **No preregistration was silently modified**: YES — document unchanged from Phase 9
- **All defects found during audit are documented above**: YES

---

## Reports and Artifacts

| Artifact | Location |
|----------|----------|
| Implementation audit | `docs/research/PRE_HOLDOUT_IMPLEMENTATION_AUDIT.md` |
| Synthetic control report | `docs/research/SYNTHETIC_CONTROL_REPORT.md` |
| Real data certification | `docs/research/REAL_DATA_CERTIFICATION.md` |
| Data quality report | `results/pre_holdout/data_quality/data_quality.json` |
| Research freeze | `results/pre_holdout/research_freeze.json` |
| Decision memo | `docs/research/PRE_HOLDOUT_DECISION_MEMO.md` (this file) |
| Preregistration | `docs/research/INTRADAY_SMC_PREREGISTRATION.md` |
| Methods reference | `docs/research/INTRADAY_SMC_METHODS.md` |
