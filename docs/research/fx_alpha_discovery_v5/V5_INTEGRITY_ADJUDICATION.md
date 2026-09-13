# V5 Integrity Adjudication

**Artifact:** V5_INTEGRITY_ADJUDICATION_V1  
**Date:** 2026-09-13  
**Starting SHA:** `4570d939d8424d50c2ffa3fdddc4a3276eb7c118`  
**Prospective Seal SHA:** `d3016853f4bcfe488617aa9fb719bd876654c850`  
**Adjudication Verdict:** **C — V5_RESULT_INVALID_REQUIRES_ENGINEERING_FORENSICS**  
**Next Gate:** `V5_ENGINEERING_FORENSICS`

---

## 1. Candidate Universe Reconciliation

| Family | Planned | Executed | Status |
|--------|---------|----------|--------|
| S1 | 24 | 24 | MATCH |
| S2 | 24 | 24 | MATCH |
| S3 | 24 | 24 | MATCH |
| S4 | 24 | 16 | MISSING_FROM_RUN (-8) |
| S5 | 24 | 48 | UNPLANNED_IN_RUN (+24) |
| S6 | 0 | 0 | MATCH |
| S7 | 24 | 24 | MATCH |
| **Total** | **144** | **160** | **+16** |

**Why 144 became 160:**
- S4: Protocol specifies "2 factors x 2 dynamics x 6 horizons/variants = 24." Script implements only 4 horizons (30/60/120/240 min) instead of 6, yielding 2x2x4=16.
- S5: Protocol specifies "2 arch x 2 context x 6 horizon/seed variants = 24." Script implements 2 arch x 2 context x 4 horizons x 3 signal variants = 48. The 3 variants (full, half-amplitude, sign-only) were added beyond the planned 6.

Net: -8 + 24 = +16. 144 + 16 = 160.

**Was the 160-candidate universe fixed before outcomes?** NO. The execution registry was defined in uncommitted code written after the seal.

---

## 2. Timing

| Event | SHA | Time |
|-------|-----|------|
| Prospective seal (144 candidates) | `d301685` | 2026-09-12 20:16:26 +0300 |
| Run script written (160 candidates) | UNCOMMITTED | ~20:17-20:56 (unrecorded) |
| First outcome computation | — | 2026-09-12 20:56:09 (script start) |
| Results committed | `4570d93` | 2026-09-12 21:47:26 +0300 |

**Finding:** POST_OUTCOME_PROTOCOL_DEVIATION. The 160-candidate universe was not immutably fixed before outcomes.

---

## 3. Reproducibility

| Component | Location | In Git? | SHA |
|-----------|----------|---------|-----|
| Signal generation | `D:\ComputaCenter\v3_processing\run_v5_discovery.py` | NO | — |
| Candidate registry | Same file | NO | — |
| Execution engine | Same file | NO | — |
| P&L computation | Same file | NO | — |
| Statistics | Same file (placeholder) | NO | — |

**Finding:** POST_OUTCOME_REPRODUCIBILITY_DEFECT. All execution code is uncommitted, outside the repository. No SHA exists. Independent reproduction is impossible.

---

## 4. Date Roles Audit

**Protocol:** 2010-2013=dev, 2014=selection, 2015-2016=robustness, 2017=replication, 2018+=SEALED.

**Actual implementation (line 136 of run script):**
```python
mask_a = exec_a & ~np.isnan(mid_a)
```

The M1-level date filter (`ny_date >= "2014-01-01" & ny_date <= "2017-12-31"`) was computed but **DISCARDED**. The aggregated mask contains no date filter and no `obs` flag.

**Evidence:**
- Data spans 2009-12-31 to 2017-12-29 (8 years)
- 2014-2017 = 49.9% of bars; 2010-2013 = 50.1%
- Mask passes 97.7% of aggregated bars (vs 50% expected if date-filtered)
- n_days = 32,537 summed / 13 instruments = 2,503 per instrument
- Max possible for 4 years: 1,460 days. 2,503 is impossible for 4 years.
- 2,503 is consistent with 8 years (2009-2017).

**DID 2010-2013 ENTER EVALUATED P&L? YES.**

---

## 5. Model Leakage

| Family | Leakage | Detail |
|--------|---------|--------|
| S1 (Kalman) | NONE | Recursive, causal by construction |
| S2 (Regime) | **YES** | `vol_med = np.nanmedian(rv[mask])` uses full-sample (2009-2017) median as static threshold. Future data influences past gating. |
| S3 (XSectional) | NONE | Rolling 6-bar momentum, causal |
| S4 (Factor) | NONE | Rolling 24-bar window, causal |
| S5 (Sequence) | NONE | Rolling context window, causal |
| S7 (Stopping) | NONE | Rolling 6-bar expected move, causal |

**S2 leakage severity: HIGH.** The vol threshold includes 2016-2017 data when gating 2010 bars.

---

## 6. Panel Accounting

- n_instrument_results = 160 x 13 = 2,080
- Each candidate evaluated independently per instrument, then SUMMED
- WRC/SPA were NEVER COMPUTED (placeholder p=1.0)
- No daily P&L matrix was constructed for cross-candidate comparison
- The 13 instrument results per candidate are not statistically independent, but since no cross-candidate statistics were computed, this had no effect

**Verdict:** PANEL_ACCOUNTING_ADEQUATE (no statistics computed that could be affected)

---

## 7. Economic Reconciliation

Formula: `net = gross - spread - explicit_cost`

| Family | Gross | Spread | Comm | Net | Calc | Match | Net/trade |
|--------|-------|--------|------|-----|------|-------|-----------|
| S1 | -188,390 | 186,683 | 39,044 | -414,118 | -414,118 | YES | -4.24 bps |
| S2 | -254,800 | 186,683 | 39,044 | -441,481 | -441,481 | YES | -4.52 bps |
| S3 | -237,952 | 186,683 | 39,044 | -424,635 | -424,635 | YES | -4.35 bps |
| S4 | -170,684 | 186,683 | 39,044 | -357,368 | -357,368 | YES | -3.66 bps |
| S5 | -209,532 | 186,683 | 39,044 | -386,217 | -386,217 | YES | -3.96 bps |

The -300k to -450k bps values are **cumulative sums across ~97,000 trades**, not portfolio returns. Per-trade net is -3.7 to -4.5 bps.

**Verdict:** ECONOMIC_RECONCILIATION_PASSES

---

## 8. Turnover Audit

| Family | Trades/Day (median) | P90 | Max | Classification |
|--------|---------------------|-----|-----|----------------|
| S1 | 3.0 | 3.0 | 3.0 | AT_CAP |
| S2 | 3.0 | 3.0 | 3.0 | AT_CAP |
| S3 | 3.0 | 3.0 | 3.0 | AT_CAP |
| S4 | 3.0 | 3.0 | 3.0 | AT_CAP |
| S5 | 3.0 | 3.0 | 3.0 | AT_CAP |
| S7 | 0.0 | 0.0 | 0.0 | ZERO_TRADES |

All active families hit the 3-entry cap exactly. S7's cost filter was too strict, blocking all trades.

**Verdict:** TURNOVER_WITHIN_PROTOCOL

---

## 9. Statistics Audit

| Test | Computed? | Value | Note |
|------|-----------|-------|------|
| WRC | NO | 1.0 | Placeholder |
| SPA | NO | 1.0 | Placeholder |
| Romano-Wolf | NO | — | Never computed |
| Holm | NO | — | Never computed |
| BH-FDR | NO | — | Never computed |
| PSR | NO | — | Never computed |
| DSR | NO | — | Never computed |
| CSCV PBO | NO | — | Never computed |
| Stationary Bootstrap (999x5) | NO | — | Never computed |
| Daily P&L Matrix | NO | — | Never constructed |

**Verdict:** ALL_FROZEN_STATISTICS_UNCOMPUTED

---

## 10. Firewall

| Counter | Value |
|---------|-------|
| 2018+ provider requests | 0 |
| 2018+ market reads | 0 |
| V4 Databento requests | 0 |
| V4 Databento downloads | 0 |
| V4 paid data purchases | 0 |

**Verdict:** FIREWALL_INTACT

---

## 11. Terminal Adjudication

### VERDICT: C — V5_RESULT_INVALID_REQUIRES_ENGINEERING_FORENSICS

The negative result (0 survivors) is **NOT reliable** due to:

1. **CRITICAL:** Date filter missing — 2010-2013 data in evaluated P&L
2. **CRITICAL:** Execution code uncommitted, unreproducible
3. **HIGH:** 160-candidate universe not fixed before outcomes
4. **HIGH:** S2 future-to-past leakage
5. **HIGH:** All frozen statistics uncomputed
6. **MEDIUM:** S7 degenerate (zero trades)
7. **MEDIUM:** S4/S5 candidate count deviation

The true 2014-2017-only result is unknown and could differ from the reported negative.

**Next Gate:** `V5_ENGINEERING_FORENSICS`
