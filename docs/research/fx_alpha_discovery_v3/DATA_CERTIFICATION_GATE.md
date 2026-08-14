# V3 Data-Certification & Freeze-Hardening Gate

**Terminal verdict:** `V3_DATA_CERTIFICATION_IN_PROGRESS_BULK_ACQUISITION_PENDING`
**Next gate:** `COMPLETE_BULK_PRE_2018_ACQUISITION` → then `V3_ALPHA_DISCOVERY_RUN`
**Machine-readable:** [`results/gate_v3f/data_certification_gate.json`](../../../results/gate_v3f/data_certification_gate.json)

This gate performs the four freeze-hardening corrections and certifies the acquisition
pipeline on real data. It does **not** run discovery, compute any V3 P&L, or open any 2018+
byte. The verdict is the honest partial state: every non-data condition passes; only full
bulk acquisition remains, blocked this session by a provider throttle.

## 1. Freeze-hash bug fixed (independent program protocol)

`program_protocol` previously aliased `statistics_hash()`, so it carried no independent
identity. It is now the distinct [`program_protocol.py`](../../../src/fx_smc_bot/research/v3/program_protocol.py)
artifact (program identity, gate sequence, holdout governance, claim-class governance,
cross-version sequential multiplicity procedure). Result:

* `program_protocol` hash: `b9f6bbf5…` (bug, == statistics) → `e9ce6e6e…` (independent)
* `statistical_protocol` hash: `b9f6bbf5…` → `cde77f9d…` (denominator policy corrected)
* **top-level freeze hash: `ea8973…` → `cdfb66a0…`**

No outcome information informed the change; it is a pure pre-outcome integrity correction.

## 2. Denominator / claim-class semantics (universes A/B/C/D)

[`universes.py`](../../../src/fx_smc_bot/research/v3/universes.py) makes every "denominator"
unambiguous, with counts derived from the compiler + composition (never assumed):

| Universe | Count | Rule |
| --- | --- | --- |
| A executable scientific-alpha | **992** | only denominator for executable WRC/SPA/RW/Holm/BH-FDR/PSR/DSR/PBO |
| B price-alpha-only | **52** | analysed against \|B\|; can NEVER be an executable survivor |
| C total V3 registry | **1044** | A + B (disjoint; A + B = C proven) |
| D lineage | **1388** | V1(8)+V2(336)+V3(1044); program-level sequential control |

Every statistical routine exposes the exact universe it consumes (`denominator_for`).
Invariants forbid any runtime failure, zero-trade candidate or outcome from shrinking a
frozen universe. H2/H3 (financing unsupported) live in B and cannot become executable
survivors.

## 3. Evidence-derived readiness

`_internal_criteria()` no longer contains unconditional `True`s. Each material claim is
computed: feature-DAG determinism (hash twice), denominator agreement
(compiler/budget/universes), all admitted H2/H3 financing paths checked, causal no-leakage
perturbation test, deterministic ML/regime refit, cross-pair alignment fixture, protocol
independence. See [`evidence.py`](../../../src/fx_smc_bot/research/v3/evidence.py). Architecture
freeze: **36/36 criteria**, verdict `V3_ALPHA_DISCOVERY_READY`.

## 4. Real acquisition pipeline + certified sample

[`acquisition_pipeline.py`](../../../src/fx_smc_bot/research/v3/acquisition_pipeline.py):
self-contained Dukascopy `.bi5` tick → canonical M1 bid/ask, firewalled (2018+ blocked
before I/O), resumable, checksummed, with a full per-partition manifest (provider, request
identity, source/canonical checksums, byte/row counts, timestamp bounds, duplicate/missing
audit, bid/ask validity, JPY/non-JPY scaling verification, parser/canonicalizer version,
status). Parses and validates integrity **only** — no signals, P&L, ranking or selection.

**Certified real sample:** EURUSD + USDJPY, 2014-06-10, 08:00–15:59 UTC, 480 M1 bars/pair,
**4/4 partitions CERTIFIED**, 0 integrity anomalies, JPY + non-JPY scaling verified,
synchronized timestamps. `2018_plus_files_opened = 0`, `2018_plus_requests = 0`.

**Full coverage is PENDING.** 13 instruments × 2010–2017 = 2,496 monthly bid/ask partitions
(~649k tick requests). `datafeed.dukascopy.com` returns HTTP 503 after ~2 rapid requests
through the corporate proxy (successful requests 13–20 s each), making full acquisition a
multi-day, resumable, background operation — not completable this session. No coverage is
fabricated.

## 5. Real-data resource benchmarks & concurrency

Seeded from the certified real M1 and tiled to representative development scale
([`mac_real_benchmarks.json`](../../../results/gate_v3f/mac_real_benchmarks.json)):

* peak RSS for a 1-year 13-pair panel: **0.74 GiB**; extrapolated per-worker over the full
  8-year development span: **~5.9 GiB** (cross-pair panel families are the memory driver);
* slowest component: GMM (~4.9 s); all others < 0.5 s;
* **recommended heavy (cross-pair) workers: 2** (RAM-bound), not the synthetic guess of 6;
  single-pair families tolerate more. Policy: adaptive bounded concurrency, BLAS threads = 1
  per worker, no swap.

## 6. Terminal conditions

10 / 11 gate conditions pass; the only open condition is full acquisition coverage
(0 / 2,496 monthly partitions; 4 real day-partitions certified as proof). All identity,
denominator, readiness, holdout, determinism and quality conditions pass. The single
remaining step is bulk pre-2018 acquisition on an unthrottled network.
