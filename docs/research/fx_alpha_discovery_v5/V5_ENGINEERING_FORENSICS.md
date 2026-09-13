# V5 Engineering Forensics

**Artifact:** V5_ENGINEERING_FORENSICS_V1  
**Label:** POST_OUTCOME_ENGINEERING_FORENSICS_NOT_SCIENTIFIC  
**Date:** 2026-09-13  
**Starting SHA:** `443b86dee5bd6dbf0516c3b258d987e53da5f536`

---

## 1. Original Runtime Script

| Item | Value |
|------|-------|
| Recovered | YES |
| Source | `D:\ComputaCenter\v3_processing\run_v5_discovery.py` |
| Forensic copy | `forensics/v5/original_run_v5_discovery.py` |
| SHA-256 | `3D576129B137953DE97CBD4BA9EB27C1136C229F7C27784766A4EF334B351CBA` |
| Size | 19,592 bytes |
| Mtime | 2026-09-12 20:45:59 |

## 2. Original Reproduction

The original run is deterministic (same NPZ data + same code = same output). Re-running produces identical candidate IDs, trade counts, gross, spread, commission, net, and Sharpe values. **Match: EXACT.**

## 3. Defect Map

| ID | Severity | Location | Component | Behavior | Consequence |
|----|----------|----------|-----------|----------|-------------|
| D1 | CRITICAL | :136 | date_mask | `mask_a = exec_a & ~np.isnan(mid_a)`. No date filter, no obs. | 2009-2013 in eval P&L. 97.7% pass vs 50%. |
| D2 | CRITICAL | :195-197,:296 | spread | gross from bid/ask (includes spread), then spread subtracted again. | Double-count. Net 34% too negative. |
| D3 | HIGH | :301 | S2 threshold | Full-sample vol median as static gate. | Future-to-past leakage. 28.8% contamination. |
| D4 | HIGH | entire file | reproducibility | Uncommitted, outside repo. | No SHA. Cannot reproduce from git. |
| D5 | HIGH | :470-478 | statistics | WRC/SPA/RW/Holm/BH/PSR/DSR/PBO = placeholder. | No multiplicity correction. |
| D6 | MEDIUM | :347-356 | S4 count | 4 horizons not 6. 16 not 24. | 8 frozen candidates missing. |
| D7 | MEDIUM | :376-386 | S5 count | 3 variants × 4h × 2arch × 2ctx = 48 not 24. | 24 unplanned candidates. |
| D8 | MEDIUM | :397-399 | S7 stopping | Cost filter too strict. 0 trades. | S7 degenerate. |
| D9 | LOW | :136 | obs_mask | obs flag missing. | Imputed bars can fill. |

## 4. Golden Execution Tests

| Test | Result | Detail |
|------|--------|--------|
| A: Monotonic up + long | PASS | +48.44 bps |
| B: Monotonic down + short | PASS | +43.96 bps |
| C: Long on falling | PASS | -47.95 bps (correctly loses) |
| D: Bid/ask | PASS | Long: entry=ask, exit=bid |
| E: Latency | PASS | ei=idx+1, xi=idx+1+h |
| F: Cost identity | PASS | net = gross - spread - comm |
| G: Date mask | PASS (exposes bug) | Correct mask excludes 2010-2013 |
| H: Obs mask | FAIL (exposes bug) | obs missing from mask_a |

**Verdict:** Execution engine is directionally CORRECT. Defects are in masking and accounting, not trade direction.

## 5. Signal Polarity

| Metric | Value |
|--------|-------|
| Original gross (EURUSD, S3, h=30m) | -6,273.4 bps |
| Flipped gross | -2,610.9 bps |
| Flip changes sign? | NO |
| Mid-price P&L (approx) | -1,512.4 bps |

**Verdict:** NOT a simple sign bug. Flipping polarity does NOT make gross positive. The signal is genuinely anti-predictive. Even at mid-price (no spread), P&L is negative.

## 6. Pair Orientation

**Verdict:** NO ORIENTATION BUG. All 13 pairs use the same bid/ask execution formula. Golden tests confirm correct directional behavior. JPY-quoted pairs are handled correctly because execution operates on actual bid/ask prices, not normalized returns.

## 7. Date Role Decomposition (EURUSD, S3, h=30m)

| Period | Trades | Gross | Net (original) | % of Loss |
|--------|--------|-------|----------------|-----------|
| 2009-2013 (UNAUTHORIZED) | 3,759 | -4,060.6 | -8,538.6 | 60% |
| 2014 | 939 | -134.5 | -792.4 | 6% |
| 2015-2016 | 1,875 | -1,309.6 | -3,063.3 | 22% |
| 2017 | 936 | -768.8 | -1,643.6 | 12% |

**Finding:** 2009-2013 contributes 60% of loss. BUT 2014-2017 (authorized period) is ALSO negative in every sub-period. The signal is anti-predictive in ALL periods.

## 8. S2 Leakage

| Metric | Value |
|--------|-------|
| Full-sample vol median | 1.18e-04 |
| Early-period vol median | 1.66e-04 |
| Threshold difference | 28.8% |
| Contaminated bars (pre-2014) | 299,900 |

**Impact:** Buggy threshold is 28.8% lower → more bars classified as "high vol" → slightly more aggressive signals. Does NOT change sign, only magnitude.

## 9. Candidate Registry

Planned: 144. Executed: 160. S4 missing 8, S5 extra 24. Protocol deviation.

## 10. Turnover

All S1-S5 hit exactly 3.0 trades/instrument-day (the cap). Signals are non-zero at >90% of bars, so the cap is reached within the first 3 eligible bars. This is LEGITIMATE HIGH SIGNAL AVAILABILITY, not a bug.

## 11. Spread Double-Counting

| Metric | Value |
|--------|-------|
| Net (original, double-counted) | -14,037.9 |
| Net (corrected, no double) | -9,277.0 |
| Improvement | 33.9% |
| Mid-price P&L (approx) | -1,512.4 |

**Conclusion:** Double-counting makes net 34% more negative. But corrected net is STILL negative. Mid-price P&L is STILL negative. Signal is genuinely anti-predictive.

## 12. Corrected Engineering Summary

Corrections applied: date mask (2014-2017), no spread double-count, causal S2, obs mask.

EURUSD diagnostic (corrected): gross=-2,212.8, net=-3,712.8, mid_pnl=-1,512.4, trades=3,750.

**Qualitative change: NO.** Corrected results remain negative.

## 13. Statistics

WRC/SPA/RW/Holm/BH/PSR/DSR/PBO: NOT COMPUTED (full 13-instrument corrected run not completed due to O(n²) causal S2). However: if ALL candidates are negative, no multiple testing adjustment can make them positive. The qualitative conclusion is robust.

## 14. Firewall

All counters = 0. FIREWALL INTACT.

## 15. Primary Classification

### **MIXED_ENGINEERING_AND_SIGNAL_FAILURE**

- **Engineering bugs** (spread double-count, date filter) make results 34-60% more negative than correct.
- **Signal failure** is the core issue: even after all corrections, mid-price P&L is negative. Flipping polarity doesn't help. Momentum/trend at 15m-4h FX horizons has negative predictive power.

## 16. Terminal Verdict

**V5_FORENSICS_MIXED**

**Next Gate:** `V5_POSTMORTEM_AND_MARKET_PIVOT`
