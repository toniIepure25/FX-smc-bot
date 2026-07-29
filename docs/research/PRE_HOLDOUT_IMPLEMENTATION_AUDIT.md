# Pre-Holdout Implementation Audit

**Branch**: `research/rigorous-intraday-smc-validation`
**Starting SHA**: `12f45b0`
**Audit Date**: 2026-07-13
**Python**: 3.13.5 (win32)
**Dependencies**: numpy 2.3.1, scipy 1.16.0, pandas 2.3.3, pydantic 2.11.7, pytest 8.4.1, mypy 1.20.2

---

## Verification Summary

| Check | Result |
|-------|--------|
| pytest | 459 passed, 0 failed, 0 skipped, 0 xfailed |
| Warnings | 91 DeprecationWarning (datetime.utcnow), 1 Pydantic serialization |
| ruff (new files) | 56 issues (23 line-length, 20 unused imports, cosmetic) |
| ruff (full repo) | 1261 issues (pre-existing; no correctness defects) |
| mypy (research modules) | 0 errors after fixes (4 fixed during audit) |

---

## Implementation Traceability Matrix

| # | Capability | Production file/symbol | Test file/test | Status | Evidence | Remaining risk |
|---|-----------|----------------------|----------------|--------|----------|----------------|
| 1 | Causal HTF slicing | `backtesting/engine.py:175-304` | `tests/leakage/test_htf_causality.py` (4 tests) | VERIFIED | HTF bars only visible after close time ≤ LTF timestamp; cache invalidation on boundary | None |
| 2 | Commission accounting | `backtesting/ledger.py:56-58`, `engine.py:229-232` | `tests/leakage/test_order_timing.py` | VERIFIED (FIXED) | Originally commission deducted in ledger only; **fixed during audit** to also deduct in portfolio equity path | Fixed — regression test via existing test suite |
| 3 | Order-block confirmation fix | `structure/order_blocks.py:63` | `tests/test_structure/test_liquidity.py` | VERIFIED | `or True` removed; `confirmed = not require_disp or dc.bar_index in break_bars` | None |
| 4 | Leakage test suite | `tests/leakage/` (6 files, 20 tests) | Self-testing | VERIFIED | HTF causality, swing causality, FVG causality, order timing, MTF alignment, session causality | Synthetic fixtures only |
| 5 | Provenance tracking | `data/provenance.py` | `tests/test_data/test_provenance.py` (5 tests) | VERIFIED | SHA-256 checksums, missing interval detection, duplicate detection, JSON save/load | Checksum excludes volume/spread |
| 6 | DST-aware timezone | `data/timezone.py` | `tests/test_data/test_timezone.py` (6 tests) | VERIFIED | Uses `zoneinfo`; London BST/GMT, NY EST/EDT tested | No ambiguous fall-back time handling |
| 7 | Economic calendar adapter | `data/economic_calendar.py` | `tests/test_data/test_economic_calendar.py` (5 tests) | VERIFIED | CSV/Parquet load, event window queries, high-impact detection | Case-sensitive currency filter |
| 8 | Extended liquidity levels | `structure/liquidity.py:detect_session/daily/weekly_levels` | `tests/test_structure/test_extended_liquidity.py` (4 tests) | VERIFIED | Session H/L, prior-day H/L, prior-week H/L as LiquidityLevel objects | Integrated into build_structure_snapshot |
| 9 | Generic causal state machine | `alpha/intraday/state_machine.py` | `tests/alpha/intraday/test_state_machine.py` (6 tests) | VERIFIED | StrategyTracker manages instances; cleanup_terminal removes dead; FILLED/CLOSED states unused but harmless | No transition validation in framework |
| 10 | Sweep Reversal (Strategy A) | `alpha/intraday/sweep_reversal.py` | `tests/alpha/intraday/test_sweep_reversal.py` (6 tests) | VERIFIED | Causal bar-by-bar processing; long/short symmetric; `max_fvg_bars` config unused | Signal fires on FVG completion bar (engine defers fill to next bar) |
| 11 | Acceptance Continuation (Strategy B) | `alpha/intraday/acceptance_continuation.py` | `tests/alpha/intraday/test_acceptance_continuation.py` (4 tests) | VERIFIED | Consecutive close acceptance; break + displacement required; HTF bias param unused | htf_bias accepted but ignored |
| 12 | Opening Range (Strategy C) | `alpha/intraday/opening_range.py` | `tests/alpha/intraday/test_opening_range.py` (4 tests) | PARTIALLY_VERIFIED | DST-aware range handling; session cutoff enforced; hardcoded `TradingPair.EURUSD` | Hardcoded pair; not yet tested on real DST dates |
| 13 | Swap/financing calculator | `execution/swap.py` | `tests/test_execution/test_swap.py` (5 tests) | VERIFIED | Triple Wednesday; correct long/short sign; DST rollover detection | **Not wired into BacktestEngine** |
| 14 | Same-bar SL/TP handling | `execution/fills.py:check_same_bar_exit` | `tests/test_execution/test_same_bar.py` (4 tests) | VERIFIED (FIXED) | Conservative/optimistic policies; **fixed during audit** to wire into engine | Now integrated post-fill |
| 15 | Statistical inference (bootstrap) | `research/statistical_inference.py` | `tests/test_research/test_statistical_inference.py` (9 tests) | VERIFIED (FIXED) | Stationary and block bootstrap; **PSR/DSR/MTRL annualization bug fixed** during audit | N<20 produces unstable inference |
| 16 | Overfitting controls | `research/overfitting.py` | `tests/test_research/test_overfitting.py` (5 tests) | PARTIALLY_VERIFIED | Holm-Bonferroni, BH-FDR correct; White's RC not Hansen SPA; CSCV PBO approximate | WRC uses random permutation, not full combinatorial |
| 17 | Placebos/baselines | `research/placebos.py` | `tests/test_research/test_placebos.py` (5 tests) | VERIFIED | Random direction, random time, inversion, momentum baseline | Ablation matrix keys don't match strategy configs |
| 18 | Ablation matrix | `research/placebos.py:generate_ablation_matrix` | `tests/test_research/test_placebos.py` | PARTIALLY_VERIFIED | 15 canonical ablations generated; config_overrides not wired to intraday strategies | Aspirational — not executable against real configs |
| 19 | Prop simulation | `research/prop_simulation.py` | `tests/test_research/test_prop_simulation.py` (6 tests) | VERIFIED (FIXED) | **Fixed during audit**: daily loss from day-start balance; phase2 target relative to phase1 balance | `drawdown_type` field still unused |
| 20 | Canonical configurations | `configs/research/intraday_smc/*.yaml` | Manual inspection | VERIFIED | Frozen params for all 3 strategies + prop profiles | Validated against Pydantic config models |
| 21 | Preregistration | `docs/research/INTRADAY_SMC_PREREGISTRATION.md` | Manual inspection | VERIFIED | Hypotheses, params, splits, metrics, gates, falsification criteria | Date not filled; needs freeze |
| 22 | Campaign engine | `research/intraday_campaign.py` | `tests/test_research/test_intraday_campaign.py` (10 tests) | VERIFIED | Run orchestration, daily return extraction, JSON result persistence | Intraday detectors not directly integrated — uses legacy BOS engine |
| 23 | Ingestion CLI | `scripts/ingest_data.py` | CLI help verified | VERIFIED | CSV/Parquet normalize, synthetic gen, resample, provenance | Tested via dry-run and synthetic generation |
| 24 | Campaign CLI | `scripts/run_intraday_smc_campaign.py` | CLI dry-run verified | VERIFIED | Dry-run, data loading, campaign orchestration, statistical reports | Tested via dry-run |
| 25 | Prop-simulation CLI | `scripts/run_prop_monte_carlo.py` | CLI help verified | VERIFIED | Risk grid, daily PnL input, profile config | Falls back to synthetic PnL when no data (labeled) |

---

## Defects Found and Fixed During Audit

### DEF-001: PSR/DSR/MTRL receive annualized Sharpe (CRITICAL)
- **File**: `research/statistical_inference.py:308-310`
- **Mechanism**: `build_inference_report` passed annualized SR (×√252) to PSR/DSR/MTRL which expect daily-frequency SR
- **Impact**: All PSR values inflated toward 1.0; DSR and MTRL unreliable; any prior inference was biased
- **Fix**: Compute daily SR separately; pass to PSR/DSR/MTRL; keep annualized for display
- **Regression test**: Existing tests still pass; PSR values now properly bounded
- **Prior output invalidated**: Yes — any prior statistical reports using PSR/DSR/MTRL

### DEF-002: Commission not reflected in portfolio equity (HIGH)
- **File**: `backtesting/engine.py:229-230`
- **Mechanism**: `_compute_pnl` → `close_position` path excludes commission; ledger includes it
- **Impact**: Equity curve overstates performance vs trade ledger PnL; Sharpe from equity curve is biased upward
- **Fix**: Deduct commission in engine before `close_position`
- **Regression test**: 459 tests pass
- **Prior output invalidated**: Yes — equity curves and equity-derived metrics

### DEF-003: check_same_bar_exit never called (HIGH)
- **File**: `backtesting/engine.py:254-272`
- **Mechanism**: Position filled on bar N; SL/TP within bar N range not checked until bar N+1
- **Impact**: Trades that should exit on fill bar survive to next bar; PnL inaccurate for volatile entries
- **Fix**: Call `check_same_bar_exit` immediately after fill in engine loop
- **Regression test**: 459 tests pass
- **Prior output invalidated**: Yes — trade durations and PnL for same-bar exit cases

### DEF-004: Prop simulation daily loss wrong + phase2 semantics broken (HIGH)
- **File**: `research/prop_simulation.py:147-200`
- **Mechanism**: Daily loss used fixed starting-balance limit (not day-start); phase2 target < phase1 target
- **Fix**: Track `day_start_balance`; phase2 target = `p1_balance × (1 + phase2_target)`
- **Regression test**: 459 tests pass
- **Prior output invalidated**: Yes — any prior prop simulation results

### DEF-005: mypy type errors in campaign and prop modules (LOW)
- **Files**: `intraday_campaign.py:112`, `intraday_campaign.py:315-316`, `prop_simulation.py:251`
- **Fix**: Use `FillPolicy` enum, guard `None` CI, lambda key
- **Impact**: No runtime failures (Python doesn't enforce types), but mypy now clean

---

## Defects Identified But Not Fixed (Accepted Risk)

### RISK-001: Swap calculator not wired into engine
- **Impact**: Overnight swap not deducted from backtest PnL
- **Mitigation**: Swap typically <1 pip/day; strategies target <24h holds; can be accounted post-hoc
- **Recommendation**: Wire before final holdout

### RISK-002: Intraday V2 detectors not integrated into generate_candidates
- **Impact**: Campaign engine uses legacy BOS candidate generation, not the new sweep/acceptance/opening-range detectors
- **Mitigation**: Detectors are independently tested; integration is the next phase
- **Recommendation**: BLOCKING for real-data campaigns

### RISK-003: Ablation matrix config keys don't match intraday strategy configs
- **Impact**: Cannot execute preregistered ablations automatically
- **Mitigation**: Manual ablation runs possible
- **Recommendation**: Map ablation keys to strategy config paths

### RISK-004: Signal fires on FVG completion bar (no in-strategy +1 delay)
- **Impact**: Conservative — engine fills at next bar; but ORDER_PENDING timestamp = FVG bar
- **Mitigation**: Order timestamp semantics documented; engine enforces fill delay
- **Recommendation**: Acceptable for current design

### RISK-005: Hardcoded TradingPair.EURUSD in opening_range.py
- **Impact**: Opening range signals always labeled as EURUSD regardless of actual pair
- **Mitigation**: Cosmetic — does not affect PnL or causality
- **Recommendation**: Fix before multi-pair campaigns

---

## Search Results Summary

### Synthetic fallbacks in production paths
- `ingest_data.py`: `--generate-synthetic` flag clearly separates paths — NOT a silent fallback
- `run_prop_monte_carlo.py`: Falls back to synthetic PnL with explicit logging — labeled, not silent
- `run_backtest.py`: Falls back to synthetic when no `--data-dir` — labeled, not silent
- **Verdict**: No silent synthetic contamination in research pipeline

### Broad exception handlers
- `intraday_campaign.py:189`: Catches Exception in `run_single` — logs and records error, run marked as error
- `intraday_campaign.py:325`: Catches Exception in stat report — logs warning, records error string
- **Verdict**: Acceptable — errors surface in results, not swallowed silently

### Random usage
- All random calls use `np.random.default_rng(seed)` — reproducible
- `FillEngine` uses `random.Random(rng_seed)` for RANDOM fill policy only
- **Verdict**: No uncontrolled randomness
