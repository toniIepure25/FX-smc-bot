# Gate C.3R — Acquisition Report

## Tool

- **Package**: `dukascopy-node` 1.46.4 (MIT license)
- **Source**: [github.com/Leo4815162342/dukascopy-node](https://github.com/Leo4815162342/dukascopy-node)
- **Node.js**: v20.9.0
- **npm**: 10.1.0
- **npm audit**: 0 vulnerabilities

## Architecture

```
Dukascopy M1 bid download (day-by-day)
+
Dukascopy M1 ask download (day-by-day)
→ Python aggregation to monthly partitions
→ timestamp alignment (exact UTC join)
→ BidAskBarSeries M1
→ independent bid/ask resampling
→ M5, M15, H1, H4
```

## Acquisition Settings

```
timeframe: m1
utcOffset: 0
ignoreFlats: true
useCache: true
batchSize: 5
pauseBetweenBatchesMs: 1000
retryCount: 5
pauseBetweenRetriesMs: 1000
```

## Download Strategy

Due to intermittent `fetch failed` errors from the Dukascopy CDN,
acquisition downloads day-by-day with Python-level retries (up to 2
additional attempts per day). Daily data is then aggregated into
monthly partitions with atomic writes (os.replace).

## Acquired Data

### Target
- EURUSD, GBPUSD, USDJPY
- M1 bid and ask
- 2015-01-01 through 2025-12-31

### Actually Acquired
- EURUSD, GBPUSD, USDJPY
- M1 bid and ask
- **2023-06** only (6 partitions, 168,734 total M1 bars)
- Background acquisition of 2019-01, 2020-01, 2024-06 in progress

### Partition Counts
| Pair   | Side | Months | Rows   |
|--------|------|--------|--------|
| EURUSD | bid  | 1      | 31,282 |
| EURUSD | ask  | 1      | 25,732 |
| GBPUSD | bid  | 1      | 24,751 |
| GBPUSD | ask  | 1      | 24,219 |
| USDJPY | bid  | 1      | 31,375 |
| USDJPY | ask  | 1      | 31,375 |

## Acquisition Commands

```bash
# Dry-run planning
python scripts/acquire_dukascopy_node_history.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2015-01-01 --end 2025-12-31 \
  --output-dir data/real --dry-run

# Full acquisition (resumable)
python scripts/acquire_dukascopy_node_history.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2015-01-01 --end 2025-12-31 \
  --output-dir data/real

# Validation and certification
python scripts/validate_and_certify.py
```

## Resumability

- Completed partitions (data.json with non-zero size) are skipped
- Partially downloaded files use .tmp suffix and atomic rename
- Acquisition can be interrupted and resumed safely
- Cache is maintained by dukascopy-node in `tools/dukascopy-node/.cache/`

## Limitations

1. Network latency: ~2-4 minutes per day with retries
2. Full dataset (792 partitions) estimated at 100+ hours
3. CDN reliability varies by year (older data shows more failures)
4. GBPUSD has higher failure rate than EURUSD/USDJPY
