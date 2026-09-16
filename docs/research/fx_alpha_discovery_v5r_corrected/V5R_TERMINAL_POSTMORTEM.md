# FX M1 Structural Alpha Discovery — Terminal Postmortem

**Status:** `CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`
**Terminal SHA:** `36be4d30c0cb5316cd00fc8e8d4a0d30f82a17c4`
**Date:** 2026-09-13
**Program:** FX_STRUCTURAL_ALPHA_DISCOVERY (V1 → V5R)
**Data:** 13 FX pairs, M1, 2010–2017, digest `15a5c1af...`

---

## 1. Lineage Summary

| Version | Scope | Candidates | Verdict | Status |
|---------|-------|-----------|---------|--------|
| V1–V3 | Broad signal search (momentum, mean-reversion, volatility, session, calendar, ML) | 1,388 | `V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` | **Scientific null** |
| V4 | CME FX futures microstructure (Databento L2) | 0 (blocked) | `V4_CLOSED_NO_PAID_DATA_ACQUISITION` | **Never executed** (no API key) |
| V5 | "Structural models" (first attempt) | 160 | `V5_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` | **Invalid** (fidelity failure) |
| V5 Forensics | Engineering audit of V5 | — | `V5_FORENSICS_MIXED` | **Diagnostic only** |
| V5R | True structural models (Kalman, GMM, cross-sectional, PCA, GRU/TCN, cost-aware) | 88 | `V5R_TRUE_STRUCTURAL_MODELS_NO_PRE_HOLDOUT_EDGE` | **Invalid** (protocol deviations) |
| V5R Corrected | Protocol-conformance rerun of V5R | 88 | `V5R_CORRECTED_NO_PRE_HOLDOUT_EDGE` | **Scientific null** |

**Cumulative:** 1,564 candidate evaluations (1,388 + 160 + 88 + 88 corrected), 0 scientific survivors, 1 non-actionable positive (5 trades, Sharpe 0.002).

---

## 2. Tested Information Classes & Model Families

### Information Classes
- M1 OHLCV (bid/ask, mid, spread)
- Realized volatility, Parkinson volatility, ATR
- Range compression
- Trend slope (multi-scale)
- Momentum z-scores (multi-horizon)
- Distance z-scores
- Session/calendar features
- Cross-sectional relative strength (13 pairs)
- Factor residuals (USD common, PCA)
- Kalman state-space (level + slope)
- GMM regime probabilities
- Neural sequence representations (GRU, TCN)

### Model Families
- Linear momentum / mean-reversion
- Volatility-based signals
- Session/calendar effects
- Random Forest / Gradient Boosting
- Linear regression on engineered features
- **True Kalman filter** (recursive state-space)
- **Gaussian Mixture Model** (regime detection)
- **Cross-sectional ranking** (13-pair panel)
- **PCA factor residuals** (causal)
- **GRU** (1 layer, hidden=32, trained)
- **Causal TCN** (2 layers, channels=32, trained)
- **Cost-aware optimal stopping** (ENTER/WAIT/ABSTAIN)

### Horizons Tested
15 min, 30 min, 60 min, 120 min, 240 min

### Cost Models
- 0.40 bps round-trip (base)
- 0.60 bps (1.5x stress)
- 0.80 bps (2.0x stress)
- Bid/ask execution (spread included in gross)

---

## 3. Major Engineering Lessons

| # | Lesson | Impact |
|---|--------|--------|
| 1 | **Spread double-counting:** Bid/ask P&L already includes spread. Subtracting spread again inflates losses by ~34%. | Made V5 results 34% more negative than correct |
| 2 | **Date mask must be in aggregated data:** Computing mask at M1 level then discarding it during aggregation loses the date filter. | V5 included 2009–2013 in evaluation (60% of loss) |
| 3 | **Model fidelity matters:** Naming a model "Kalman" while implementing rolling OLS is NOT testing Kalman. | V5 verdicts were about proxies, not the named models |
| 4 | **Bid/ask variable ordering:** `bo, ao = a["ao"], a["bo"]` silently reverses all P&L signs. | V5R R5 had swapped bid/ask |
| 5 | **Candidate ID uniqueness:** `dyn[:4]` truncation caused "residual_momentum" and "residual_drift" to collide. | V5R R4 had 8 IDs instead of 16 |
| 6 | **Dimensional consistency:** Comparing raw returns to bps costs is dimensionally invalid. | V5R R7 produced zero trades |
| 7 | **Full-sample statistics in causal models:** Using median of full period as threshold leaks future into past. | V5 S2 had 28.8% threshold contamination |
| 8 | **Protocol must seal BEFORE execution:** Candidate universe must be immutable before first P&L. | V5 ran 160 candidates vs 144 planned |
| 9 | **Code must be in git:** Uncommitted runners make results irreproducible. | V5 code had no SHA |
| 10 | **Statistics must be computed, not placeholder:** WRC/SPA/PBO cannot be "1.0" by default. | V5 had no real statistics |
| 11 | **Numpy scalar conversion:** `float(H @ x)` fails for 1D arrays; use `.flatten()[0]`. | Caused test failures in Kalman/GRU |
| 12 | **Panel length alignment:** Different instruments have different bar counts; must use min length. | Caused index errors in cross-sectional/PCA |

---

## 4. Scientific Nulls vs Invalid/Intermediate Runs

### Valid Scientific Nulls (evidence that no edge exists)
- **V3 (1,388 candidates):** Broad search across momentum, mean-reversion, volatility, session, calendar, ML. All negative after costs. WRC p≈1.0.
- **V5R Corrected (88 candidates):** True structural models (Kalman, GMM, cross-sectional, PCA, GRU, TCN, cost-aware). All negative after costs except 1 candidate with 5 trades (not actionable). WRC p=0.485, DSR=0.0.

### Invalid/Intermediate Runs (do NOT constitute evidence)
- **V5 (160 candidates):** Implementation fidelity failure. Rolling OLS ≠ Kalman, vol threshold ≠ GMM, per-pair momentum ≠ cross-sectional, fixed formula ≠ neural network. Result is about the proxies, not the named models.
- **V5 Forensics:** Diagnostic only. Confirmed execution engine was correct but identified spread double-counting, date mask bug, and S2 leakage.
- **V5R (80 candidates, pre-correction):** Protocol deviations (bid/ask swap, ID collision, no cost threshold, wrong GMM labels). Result invalidated by conformance correction.
- **V4:** Never executed. No data acquired. No evidence either way.

---

## 5. Why Further Same-Data Alpha Search Is Prohibited

1. **Exhaustive coverage:** 1,564 candidates across 12+ model families, 5 horizons, 3 cost levels, 13 instruments, 8 years of data. The search space for M1 FX structural signals has been thoroughly explored.
2. **Consistent null:** Every valid evaluation (V3, V5R Corrected) produces the same result: no candidate survives costs + multiplicity. The null is robust across model families, horizons, and time periods.
3. **Diminishing returns:** Each additional candidate family tested adds negligible new information. The market microstructure at M1 frequency for these 13 pairs does not contain exploitable structural alpha at the tested cost levels.
4. **Overfitting risk:** Any further search on the same data increases the probability of finding spurious "survivors" through multiple testing. The multiplicity burden (1,564+ trials) makes the bar for survival extremely high.
5. **Data limitation:** M1 OHLCV does not contain order flow, imbalance, or queue position information. Without L2 data (which V4 was designed to test but never executed), the information available in this dataset has been fully exploited.

**Policy:** `NO_NEW_MARKET_DATA = TRUE`. No new symbols, periods, providers, or data classes.

---

## 6. 2018+ Holdout Status

**Status:** UNUSED. SEALED.

- 2018+ data was never accessed, read, or used in any computation.
- No 2018+ provider requests were made.
- No 2018+ market data was read.
- The holdout remains intact for potential future use under a new protocol with new data classes or new markets.

**Firewall counters (all runs):**
- 2018_plus_provider_requests = 0
- 2018_plus_market_reads = 0
- V4_Databento_requests = 0
- V4_Databento_downloads = 0
- V4_paid_data_purchases = 0

---

## 7. Reusable Infrastructure

The following components are reusable for future research programs (different markets, data classes, or time periods):

| Component | Location | Reuse For |
|-----------|----------|-----------|
| **Execution engine** (bid/ask, 1-bar latency, max 3/day, no spread double-count) | `src/fx_smc_bot/research/v5r/execution.py` | Any market with bid/ask data |
| **Leakage tests** (causal window enforcement, full-sample detection) | `tests/test_gate_v5r/test_v5r_models.py` | Any model with fitted parameters |
| **Multiplicity framework** (WRC, SPA, RW, Holm, BH, PSR, DSR, PBO) | `src/fx_smc_bot/research/v5r/statistics.py` | Any candidate evaluation |
| **Candidate registry/sealing** (prospective protocol + hash + hard gate) | `results/gate_v5r/v5r_prospective_protocol.json` pattern | Any discovery program |
| **Walk-forward framework** (train/eval/robustness/replication splits) | `src/fx_smc_bot/research/v5r/data.py` | Any time-series research |
| **Cost accounting** (explicit commission/slippage, stress multipliers) | `src/fx_smc_bot/research/v5r/execution.py` | Any executable strategy |
| **True Kalman filter** (scalar, fast) | `scripts/v5r/run_v5r_corrected.py` | Any state-space signal |
| **Causal GMM** (refit schedule, future-H labels) | `scripts/v5r/run_v5r_corrected.py` | Any regime model |
| **Cross-sectional panel** (13-pair synchronized ranking) | `src/fx_smc_bot/research/v5r/cross_sectional.py` | Any multi-asset panel |
| **Causal PCA** (fit on past only) | `src/fx_smc_bot/research/v5r/pca_factor.py` | Any factor model |
| **GRU/TCN** (numpy, manual backprop, Adam) | `src/fx_smc_bot/research/v5r/sequence_models.py` | Any sequence model |
| **Golden execution tests** (A-H) | `tests/test_gate_v5/test_v5_forensic_golden.py` | Any execution engine |
| **Protocol conformance correction** pattern | `results/gate_v5r_corrected/v5r_protocol_conformance_correction.json` | Any post-outcome audit |

---

## 8. Program Closure

**The FX M1 structural alpha-discovery program is TERMINALLY CLOSED.**

- No V6 FX.
- No new parameter sweeps.
- No signal inversions.
- No candidate rescues.
- No post-hoc threshold tuning.
- No new markets/symbols on this data.
- No 2018+ inspection.

The isolated positive R7 candidate (5 trades, +675 bps gross, Sharpe 0.002) is **not actionable alpha**. It is a statistical artifact of 5 trades and does not survive any reasonable multiple-testing correction.

**Terminal status:** `CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`

**No next alpha gate.**

---

*End of postmortem.*
