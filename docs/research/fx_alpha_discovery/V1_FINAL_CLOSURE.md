# FX_INTRADAY_ALPHA_DISCOVERY_V1 — Final Closure

**Status:** `CLOSED_NO_CERTIFIED_V1_ALPHA`
**Lineage:** `FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1`
**Successor:** `FX_INTRADAY_ALPHA_DISCOVERY_V2`
**Machine-readable artifact:** [`results/gate_a0r4/v1_final_closure.json`](../../../results/gate_a0r4/v1_final_closure.json)

V1 history is immutable evidence. This document formally closes V1 without rewriting any
earlier result and without inventing semantics retroactively attributed to V1.

## 1. What was actually executable

Only two of the twelve conceptual families were ever given complete, exact, pre-outcome
executable semantics and run through the certified side-correct event state machine:

| Family | Disposition in V1 |
| --- | --- |
| F01 Session-opening momentum/reversal | Executed (certified) |
| F02 Quote-run continuation/exhaustion | Executed — **M1 signed-return run-length variant only** |

At the A0R3F terminal checkpoint: **8 certified executable trials**, **0 scientific
exploratory survivors**, WRC p ≈ 0.99599, SPA p = 1.0, cost-stress survivors (1.5x / 2.0x)
= 0 / 0. The A0R3E→A0R3F regression check was byte-stable (max abs delta 0.0).

## 2. Which families were incompletely specified

Six families remained `IMPLEMENTATION_BLOCKED` at A0R3F because V1 froze them at the
idea/search-space level without a complete executable pre-outcome formula:

`F03_VOLATILITY_BREAKOUT`, `F04_LIQUIDITY_SHOCK_REVERSAL`,
`F05_SPREAD_AWARE_EXECUTION_GATING`, `F10_INTRADAY_SEASONALITY`,
`F11_REGIME_CONDITIONED_TREND_REVERSAL`, `F12_COST_SENSITIVE_ML_ABSTENTION`.

## 3. Which inputs were unavailable

The V1 program *planned* nine instruments across 2010–2025. Only **three USD majors**
(EURUSD, GBPUSD, USDJPY) at **M1 bid/ask** for **2015–2019** were ever acquired. This gap
— not a coding defect — is the true root cause of most V1 blockers:

* tick-level quote arrival / update-rate semantics (F02 tick variants, F04 quote-gap) were
  never acquired and cannot be faked from M1 (`M1 bar count != quote update count`);
* JPY crosses (EURJPY/GBPJPY/AUDJPY) and AUD/other majors required by cross-pair (F06),
  currency-factor (F07), triangular (F08) and cross-sectional (F09) families were never
  acquired.

## 4. What was discovered / what was NOT established

* **Discovered:** zero certified V1 alpha. No executable trial produced a positive,
  cost-robust, statistically significant net return in the development region.
* **NOT established:** that every conceptual family is unprofitable.

```
Claimed:              NO_CERTIFIED_V1_ALPHA
Explicitly NOT claimed: ALL_CONCEPTUAL_FAMILIES_PROVEN_UNPROFITABLE
```

Six families were never given complete executable pre-outcome semantics, so their
profitability was **never tested**. The absence of a certified survivor among the two
executable families is *not* evidence of alpha absence for the unspecified families. The
remaining ambiguity is a **protocol-design limitation**, not evidence of no alpha.

## 5. Why zero A0R3E survivors means no V1 confirmation

Because A0R3E/A0R3F found **zero** scientific exploratory survivors, no candidate was ever
eligible for a 2018+ confirmation. Consequently **no 2018+ V1 confirmation was warranted or
run**, and `2018_plus_market_or_outcome_files_opened = 0` was preserved. A negative-net
`REVIEW_RANKING` entry is reviewable but was never a survivor and was never promoted.

## 6. Immutability

All V1/A0/A0R1/A0R2/A0R3 artifacts are retained as historical evidence and are not
rewritten by this closure or by V2. V2 begins a *new, prospective* protocol rather than
retrofitting semantics onto V1.
