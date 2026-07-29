# Gate C.3F — Certification Protocol

## Preregistered before data inspection

All thresholds in this document were frozen before viewing quality results
from any partition beyond June 2023 (which served as engineering smoke test
only, never for development certification).

## Certification Vocabulary

| Status | Scope | Meaning |
|--------|-------|---------|
| `PARTITION_STRUCTURALLY_VALIDATED` | Single month | Both sides present, aligned, no negative spreads, Parquet roundtrip OK |
| `PARTITION_EXPLORATORY_ONLY` | Single month | No data on either side (empty month) |
| `PARTITION_REJECTED` | Single month | Failed one or more structural checks |
| `DATASET_CERTIFIED_FOR_DEVELOPMENT` | Full split | All development years represented and pass pair-year gates |
| `DATASET_CERTIFIED_FOR_VALIDATION` | Full split | All validation years pass |
| `HOLDOUT_QUALITY_INSPECTED_ONLY` | Holdout | Structural quality confirmed; no alpha access permitted |
| `DATASET_REJECTED` | Any split | Failed certification requirements |

## Rules

1. A holdout partition (2023-01 through 2025-12) may receive structural
   quality inspection only. It must never be labeled development data.
2. A single month cannot certify an entire pair-level multi-year dataset.
3. Certification must be scope-aware: partition → pair-year → split → dataset.
4. No certification may be inherited automatically from one scope to another.
5. Certification output must include the exact scope and interval.

## Partition Structural Gate

All of the following must hold:

- Both bid and ask data available
- Timestamp alignment ratio ≥ 80%
- Zero negative spreads
- Zero invalid OHLC bars (high < low or close outside [low, high])
- Zero duplicate timestamps after deterministic resolution
- Plausible prices (EURUSD: 0.5–2.5, GBPUSD: 0.5–3.0, USDJPY: 50–250)
- Deterministic checksum
- Successful Parquet round trip
- Successful bid/ask resampling to M5

## Pair-Year Gate

All of the following must hold:

- At least 11 structurally validated months (unless a documented provider
  limitation exists, e.g., pair not available before a certain date)
- Acceptable expected-session coverage (≥ 70%)
- No unexplained month-scale gaps
- Unpaired-row ratio ≤ 20%
- All months structurally validated or explicitly bounded exclusions

## Development-Dataset Gate

All of the following must hold:

- Coverage from 2015-01-01 through 2019-12-31
- All five years represented
- Minimum 85% pair-year coverage threshold
- Tick audit pass for available 2019 windows
- Stable transformation hashes
- No holdout access
- Sufficient session coverage
- No unresolved severe provider anomalies

## Tick-Audit Tolerances (Preregistered)

These tolerances are frozen before executing any tick audit:

| Metric | Tolerance | Justification |
|--------|-----------|---------------|
| Timestamps | Exact match | M1 bars must align exactly |
| Number of bars | Exact after common filtering | Same filtering rules applied |
| Open price | Exact after price quantization | Same source |
| Close price | Exact after price quantization | Same source |
| High price | Exact | Maximum is deterministic |
| Low price | Exact | Minimum is deterministic |
| EURUSD/GBPUSD quantization | 5-decimal raw points (0.00001) | Pip/10 precision |
| USDJPY quantization | 3-decimal raw points (0.001) | Pip/10 precision |

Floating-point equality is not used directly. All comparisons use
integer raw-point representation.

Tolerances must not be changed after viewing tick-audit outcomes.

## Amendment History

- **2026-07-14**: Initial protocol frozen before 2019 acquisition.
