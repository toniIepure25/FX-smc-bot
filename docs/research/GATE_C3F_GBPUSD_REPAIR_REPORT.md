# Gate C.3F — GBPUSD June 2023 Repair Report

## Problem Statement

Gate C.3R reported GBPUSD June 2023 with:
- 7,186 bid-only rows
- 6,654 ask-only rows
- Approximately 36% session coverage missing

## Root Cause Analysis

The unpaired rows are caused by **independent bid/ask download failures at
the day level**. The Gate C.3R download system downloaded day-by-day but
accumulated all rows in memory, retrying each day up to 2 times. When a
retry failed for a specific day on one side but succeeded on the other,
the result was days with only bid or only ask data.

### Day-Level Diagnosis

| Date | Bid Rows | Ask Rows | Issue |
|------|----------|----------|-------|
| 2023-06-01 | 1,436 | 0 | Ask download failed |
| 2023-06-02 | 0 | 1,260 | Bid download failed |
| 2023-06-06 | 0 | 1,434 | Bid download failed |
| 2023-06-07 | 1,438 | 0 | Ask download failed |
| 2023-06-08 | 1,434 | 0 | Ask download failed |
| 2023-06-09 | 0 | 1,260 | Bid download failed |
| 2023-06-13 | 1,438 | 0 | Ask download failed |
| 2023-06-14 | 1,440 | 0 | Ask download failed |
| 2023-06-27 | 0 | 1,440 | Bid download failed |
| 2023-06-30 | 0 | 1,260 | Bid download failed |

All 10 affected days had one side succeed and the other fail due to
transient network errors (`fetch failed` from the Dukascopy CDN).

### Root Cause

1. **Failed day downloads** — transient network errors during the initial
   acquisition caused individual day+side combinations to fail.
2. **Independent bid/ask requests** — bid and ask are downloaded as
   separate operations, so one can succeed while the other fails.
3. **No day-level repair** — the old system lacked targeted repair that
   could identify and re-download only the missing day+side combinations.

This is **not** a timestamp mismatch, flat-bar filtering issue, provider
content difference, or parsing error.

## Repair Strategy

The Gate C.3F daily checkpoint system with targeted repair mode can fix
this by:

1. Identifying the 10 days with missing sides
2. Re-downloading only the missing day+side combinations
3. Recompacting the month with all days present
4. Re-validating the alignment

## Certification Status

Even after repair, June 2023 partitions may only receive:
- `PARTITION_STRUCTURALLY_VALIDATED` (structural quality OK)
- `HOLDOUT_QUALITY_INSPECTED_ONLY` (2023 is holdout period)

They must **never** receive development certification.

## EURUSD and USDJPY Status

- **EURUSD**: 5,550 bid-only rows (ask download failed for some days).
  Same root cause — transient network failures.
- **USDJPY**: 0 unpaired rows. Perfect alignment. No repair needed.
