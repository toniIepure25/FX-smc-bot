# FX_INTRADAY_ALPHA_DISCOVERY_V2 — Final Closure

**Status:** `V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR`
**Next gate at V2 close:** `STOP_NO_2018_CONFIRMATION`
**Successor:** `FX_INTRADAY_ALPHA_DISCOVERY_V3`
**Canonical machine-readable evidence:** [`results/gate_a0r5/`](../../../results/gate_a0r5/)

V2 history is immutable evidence. This document formally closes V2 without rewriting,
reinterpreting or re-running any V2 result. Every figure below was re-verified from the
canonical A0R5 artifacts on the new Apple M5 machine.

## 1. Registered search universe (verified)

| Quantity | Value | Source artifact |
| --- | --- | --- |
| Expected trials | 336 | `discovery_summary.json` |
| Evaluated trials | 336 | `evaluation_status.json` |
| Evaluation failures | 0 | `evaluation_status.json` |
| Registered candidate-equivalent denominator | 336 | `discovery_summary.json` |
| Materialization digest | `4ead4048…f38fd1a1` | `discovery_summary.json` |

The materialization digest was **reproduced byte-identically** on the M5 from configuration
alone (no market data), proving the universe is machine-independent.

## 2. Outcome distribution (verified)

| Quantity | Value |
| --- | --- |
| Positive-net trials | 17 |
| 1.5× cost survivors | 8 |
| 2.0× cost survivors | 4 |
| White Reality Check p | 1.0 |
| Hansen SPA p | 0.460921844 |
| Romano-Wolf significant | 0 |
| Holm significant | 0 |
| BH-FDR significant | 0 |
| CSCV PBO | 0.128571 |
| **Scientific survivors** | **0** |

## 3. Terminal decision (unchanged)

```
V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR
STOP_NO_2018_CONFIRMATION
```

No V2 candidate produced a positive, cost-robust, multiple-testing-significant net return in
the 2015–2017 development region. Under the frozen V2 protocol this forbids any 2018+
confirmation: **no V2 candidate was promoted to the holdout.**

## 4. Holdout integrity at V2 close (verified)

`2018_plus_market_or_outcome_files_opened = 0` (`holdout_firewall_audit.json`). The sealed
2018–2019 region remains unopened. This is the program's most valuable remaining scientific
asset and is preserved unchanged into V3.

## 5. What is and is not claimed

* **Claimed:** `NO_SCIENTIFIC_SURVIVOR` across the 336-trial registered V2 universe.
* **Explicitly NOT claimed:** that the broader hypothesis space is unprofitable. V2 was
  constrained to three USD majors and intraday-only horizons; most cross-pair, multi-horizon
  and statistical-arbitrage structure was never testable for lack of data.

V3 is the response: a larger, multi-horizon, cross-sectional program built on reconstructed
pre-2018 data — with the 2018+ holdout still sealed.
