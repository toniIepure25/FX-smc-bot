# Gate C.3R — Acquisition Report

## Acquisition Summary

| Metric | Value |
|--------|-------|
| Provider | dukascopy-node 1.46.4 |
| Pairs | EURUSD, GBPUSD, USDJPY |
| Acquired period | 2023-06-01 to 2023-06-30 |
| Intended period | 2015-01-01 to 2025-12-31 |
| Timeframe | M1 |
| Sides | bid, ask |
| Total partitions | 6 |
| Total rows | 168,734 |

## Per-Pair Results

### EURUSD
- Bid rows: 31,282
- Ask rows: 25,732
- Joined rows: 25,732
- Bid-only rows: 5,550 (ask download gaps from network failures)

### GBPUSD
- Bid rows: 24,751
- Ask rows: 24,219
- Joined rows: 17,565
- Bid-only: 7,186, Ask-only: 6,654

### USDJPY
- Bid rows: 31,375
- Ask rows: 31,375
- Joined rows: 31,375 (perfect alignment)

## Acquisition Architecture

Daily download → monthly aggregation. Each day is downloaded as a separate
Node.js subprocess call to avoid network timeout failures on larger ranges.

## Network Reliability

The Dukascopy CDN shows intermittent `fetch failed` errors, especially
for GBPUSD. Retry logic (2 retries per day at the Python level, plus
5 internal retries in dukascopy-node) recovers most failures.

## Commands Used

```bash
python scripts/acquire_dukascopy_node_history.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2023-06-01 --end 2023-06-30 \
  --output-dir data/real
```

## Disk Usage

Raw JSON: ~20 MB (6 partition files)
Canonical Parquet (M1): ~3 MB
Resampled (M5/M15/H1/H4): ~2 MB

## Limitation

Full 2015-2025 acquisition requires extended runtime (~100+ hours at
current download speeds). The pipeline is validated and resumable.
