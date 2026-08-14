# FX_INTRADAY_ALPHA_DISCOVERY_V3 — Prospective Protocol (pre-discovery freeze)

**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V3`
**State:** `V3_ALPHA_DISCOVERY_READY` (architecture) · `V3_DATA_CERTIFICATION_IN_PROGRESS_BULK_ACQUISITION_PENDING` (data)
**Next gate:** `V3_ALPHA_DISCOVERY_RUN` (after bulk pre-2018 acquisition completes)
**Freeze hash:** `cdfb66a0b5388ace815d0dc90a0f6df0cf2b5ac078ca0c4dffebfea2809b1297` (was `ea8973…`; changed by the pre-outcome integrity hardening below)
**Machine-readable freeze:** [`results/gate_v3f/freeze_manifest.json`](../../../results/gate_v3f/freeze_manifest.json)
**Code:** [`src/fx_smc_bot/research/v3/`](../../../src/fx_smc_bot/research/v3/)

Everything in this protocol is **prospective**: chosen from methodology alone, frozen by
hash, and fixed before any V3 outcome is evaluated. No V3 discovery is run in this stage and
no 2018+ market/outcome byte is opened.

> **DO NOT RUN DISCOVERY IN THIS STAGE.** The next conversation executes `V3_ALPHA_DISCOVERY_RUN`.

## 0. Absolute holdout rule

`2018_plus_market_or_outcome_files_opened = 0` and `2018_plus_provider_requests_issued = 0`.
The V3 firewall ([`firewall.py`](../../../src/fx_smc_bot/research/v3/firewall.py)) makes both
structurally impossible: it blocks 2018+ **file reads** (V2 semantics) *and* 2018+
**provider/network requests** (URL, instrument-window, or bare date) before any I/O.

## 1. Clean-room reproduction (Apple M5)

New machine, reconstructed from scratch: macOS 26.5.2, Apple M5 (Mac17,4), arm64, 10 cores,
16 GiB. Native arm64 CPython 3.12.13 via `uv` (no Rosetta), NumPy on Apple **Accelerate**
BLAS. Hash-pinned lock in [`requirements.lock`](../../../requirements.lock).

Cross-machine reproduction splits exactly as anticipated:

* **Class A (byte-identical identity):** the V2 A0R5 `materialization_digest` reproduces
  byte-for-byte (`4ead4048…`), from configuration alone. Machine-independent.
* **Class B (float numerics):** the 244 V2 golden-kernel/dry-run tests pass on Accelerate;
  frozen ULP tolerances (`net_bps_abs_tol=1e-6`) bound any BLAS-driven difference.

See [`results/gate_v3f/environment_profile.json`](../../../results/gate_v3f/environment_profile.json)
and [`cross_machine_reproduction.json`](../../../results/gate_v3f/cross_machine_reproduction.json).

## 2. Data universe, exposure and time structure

**Universe (13 pairs):** 7 USD majors (EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD,
USDCHF) + 6 crosses (EURJPY, GBPJPY, AUDJPY, EURGBP, EURCHF, GBPCHF), chosen for liquidity
and cross-sectional/triangular structure, not quantity
([`capabilities.py`](../../../src/fx_smc_bot/research/v3/capabilities.py)).

**Exposure registry** ([`exposure.py`](../../../src/fx_smc_bot/research/v3/exposure.py)):
instrument × year × data-type → exposure level and class. "File existed" ≠ "outcome exposed".

| Class | Cells | Meaning |
| --- | --- | --- |
| `NEW_DEVELOPMENT_DATA` | 95 | never parsed/inspected before V3 |
| `PREVIOUSLY_EXPOSED_DEVELOPMENT_DATA` | 9 | EURUSD/GBPUSD/USDJPY × 2015–2017 (V2 selection) |
| `SEALED_HOLDOUT_DATA` | 26 | 2018–2019, exposure asserted NONE |

**Frozen time structure:** PRIMARY development = **2010–2014** (never used for any selection);
SECONDARY robustness = 2015–2017 (V2's selection window, conservative); SEALED = 2018+.
Boundaries frozen before outcomes, not by profitability.

**Acquisition:** pre-2018 only, resumable/checksummed/firewalled
([`acquisition.py`](../../../src/fx_smc_bot/research/v3/acquisition.py)). Estimate: 104
instrument-years, ~2,496 files, ~0.7 GiB canonical (~2 GiB source), transparent per-unit
constants in [`acquisition_plan.json`](../../../results/gate_v3f/acquisition_plan.json). Bulk
pull is deferred to the discovery-run session; the firewalled downloader is validated on the
synthetic path and the 2018+ block is tested. Tick data is **not** in this plan and M1 is
never represented as tick.

## 3. Multi-horizon program

| Class | Horizon | Holding | Financing | Executability |
| --- | --- | --- | --- | --- |
| H0 | micro/intraday | 1 min – 3 h | none | FULLY_EXECUTABLE |
| H1 | session/daily | 1 h – 1 day | none | FULLY_EXECUTABLE |
| H2 | intraweek | 1–5 days | required | PRICE_ALPHA_ONLY |
| H3 | intramonth | 5–20 days | required | PRICE_ALPHA_ONLY |

Overnight financing/carry cannot be reconstructed from Dukascopy price data with defensible
provenance, so **H2/H3 are `PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE`** and cannot
become executable scientific survivors. Zero overnight financing is never assumed
([`execution_contract.py`](../../../src/fx_smc_bot/research/v3/execution_contract.py)).

## 4. Feature DAG

A typed, causal DAG ([`feature_dag.py`](../../../src/fx_smc_bot/research/v3/feature_dag.py)):
17 nodes / 11 edges, every node `causal_endpoint` (right-aligned, available at bar close t).
The validator rejects centered/full-sample transforms and cycles, resolves capability
dependencies, and hashes each node by immutable identity for safe caching. DAG hash
`1b9cd856…`.

## 5. Family registry and composition grammar

**17 admitted families across 12 domains (A–L)**, each an explicit economic hypothesis with a
mechanism, causal feature nodes, parameter families, expected turnover, cost sensitivity, a
failure mode and a falsification criterion
([`families.py`](../../../src/fx_smc_bot/research/v3/families.py)). Two deliberately-listed
tick/order-book families are **rejected** (`REJECTED_PRE_OUTCOME`) because their signal inputs
are unsupported — proving admission is a real gate.

**Composition grammar** ([`composition.py`](../../../src/fx_smc_bot/research/v3/composition.py)):
a *closed whitelist* of 6 archetypes (e.g. trend + pullback + vol-regime + spread-gate),
each with one SIGNAL and typed REGIME/FILTER/GATE roles and a bounded budget. There is no
signal×filter×regime cross-product operator.

## 6. Candidate budget, denominator and lineage

Hierarchical budget domain → family → parameter-neighbourhood → instrument-scope
([`budget.py`](../../../src/fx_smc_bot/research/v3/budget.py)), with a frozen anti-overpopulation
per-family ceiling (`PARAM_COMBO_CEILING = 25`). Single-pair families register only on the 3
tier-1 majors; the other 10 pairs enter via cross-sectional families and leave-one-out
robustness, never as separately-registered survivor candidates (no hidden denominator).

Claim-class universes are frozen and disjoint, with counts derived from the compiler +
composition grammar (see [`universes.py`](../../../src/fx_smc_bot/research/v3/universes.py)):

| Universe | Definition | Count | Consumed by |
| --- | --- | --- | --- |
| **A** executable scientific-alpha | FULLY_EXECUTABLE standalone (920) + composition (72) | **992** | executable WRC/SPA/RW/Holm/BH-FDR/PSR/DSR/PBO |
| **B** price-alpha-only | H2/H3 PRICE_ALPHA_ONLY standalone (40) + composition (12) | **52** | price-alpha analysis only; never executable survivors |
| **C** total V3 registry | A + B (disjoint) | **1044** | — |
| **D** lineage | V1 (8) + V2 (336) + V3 (1044) | **1388** | program-level sequential procedure |

A + B = C exactly. The executable multiple-testing matrix consumes **only universe A (992)**;
V1/V2 are controlled by a separate frozen program-level sequential procedure, never as
imaginary columns in the V3 matrix. 1044 ≤ inherited per-version ceiling 1200. A shrink
invariant proves no runtime failure, zero-trade candidate, or outcome can shrink a frozen
universe. Outcome-driven candidate deletion is forbidden.

**Pre-outcome integrity hardening (this gate):** `program_protocol` is now an independent
artifact (previously mis-aliased to `statistics_hash()`); readiness criteria are
evidence-derived (double-hash determinism, denominator agreement, all-H2/H3 financing paths,
causal-leakage perturbation, deterministic ML/regime refit). These are pre-outcome
corrections; no V3 outcome informed them. Freeze hash `ea8973…` → `cdfb66a0…`.

## 7. Statistical protocol and survivor predicates

**Hierarchical** error control global → domain → family → candidate
([`statistics.py`](../../../src/fx_smc_bot/research/v3/statistics.py)): family-level
Romano-Wolf gatekeeper, domain-level BH-FDR, global White Reality Check + Hansen SPA over the
frozen denominator; PSR/DSR risk-adjustment; CSCV PBO; stationary block bootstrap (block 5d,
999 iters). Frozen pre-outcome; **not** chosen to maximise survivors.

**Survivor predicates by horizon** ([`survivor.py`](../../../src/fx_smc_bot/research/v3/survivor.py)):
trade-count floors scale with horizon (H0 ≥ 250 … H3 ≥ 30); per-trade net-edge floors rise
with holding; 2.0× cost-stress survival; multiple-testing significance required. H2/H3 are
price-alpha-only and cannot be executable survivors.

## 8. Robustness, portfolio, adversarial audit

Robustness battery: instrument/year/session leave-one-out, parameter-neighbourhood stability,
cost/spread/delayed-entry/execution-degradation stress, regime/subperiod stability, and (for
multi-day) overnight-cost and weekend-gap stress. Portfolio rules (max positions, per-currency
and gross/net-USD/net-JPY caps, vol-scaling) frozen; both individual-alpha and
portfolio-combination evidence are reported.

Adversarial audit ([`adversarial_audit.json`](../../../results/gate_v3f/adversarial_audit.json)):
23 attack vectors examined, **0 unresolved material findings**, each mapped to a concrete
implemented control.

## 9. V2 → V3 information boundary

V2 is exposed and may inform V3 *hypotheses* (cost matters, sparse/event structure, liquidity
shocks, seasonality-as-filter), but never V3 *fits*: no V2 trial is copied, no V3 parameter is
centred on a V2 result, no V2 candidate is promoted
([`boundary.py`](../../../src/fx_smc_bot/research/v3/boundary.py)).

## 10. Why V3 is materially more capable than V2

V2 = 3 pairs, intraday-only, 2 executable families, 336 flat-corrected candidates. V3 = 13
pairs, 4 horizon classes, 12 domains / 17 families / 6 composition archetypes, a causal typed
feature DAG, cross-sectional/currency-factor and statistical-arbitrage structure, cost-aware
abstention, interpretable ML meta-filtering, hierarchical multiple testing, and per-horizon
survivor predicates — all within the inherited 1200 candidate ceiling. Complexity is admitted
only where a hypothesis needs it (H2/H3 price-alpha honesty, tick/order-book families rejected,
composition a closed whitelist), so the added structure expresses market hypotheses rather
than degrees of freedom.
