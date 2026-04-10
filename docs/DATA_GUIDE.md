# FX Data Guide

This document explains how to obtain, import, normalize, and inspect historical FX data for use with the framework.

## Data Directory Structure

```
data/
  raw/            # Downloaded CSVs (Dukascopy exports, MT4 exports)
  interim/        # Normalized CSVs after format conversion
  processed/      # Final Parquet files (canonical schema)
  manifests/      # JSON manifests per dataset
```

## Canonical Schema

All data in `data/processed/` follows this schema:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | `datetime64[ns, UTC]` | Bar open time in UTC |
| `open` | `float64` | Opening price |
| `high` | `float64` | High price |
| `low` | `float64` | Low price |
| `close` | `float64` | Closing price |
| `volume` | `float64` (optional) | Tick volume |
| `spread` | `float64` (optional) | Spread at bar close |

Files are organized as:
```
data/processed/
  EURUSD/
    1m.parquet
    5m.parquet
    15m.parquet
    1h.parquet
    4h.parquet
    1d.parquet
  GBPUSD/
    ...
```

## Supported Data Sources

### 1. Dukascopy (Recommended)

Dukascopy provides free historical FX data. Export data from their [Historical Data Feed](https://www.dukascopy.com/swiss/english/marketwatch/historical/).

**Import steps:**
1. Download CSV files from Dukascopy
2. Place them in `data/raw/EURUSD/`, `data/raw/GBPUSD/`, etc.
3. Run the import script:

```bash
python scripts/download_data.py --mode import --input-dir data/raw --output-dir data/processed
```

### 2. MetaTrader 4/5 Exports

Export OHLCV history from your MT4/MT5 platform as CSV. The normalizer auto-detects the MT4/5 format.

### 3. Generic CSV

Any CSV with columns: `timestamp` (or `date`/`datetime`), `open`, `high`, `low`, `close`, optionally `volume`, `spread`.

### 4. Synthetic Data (Development)

Generate realistic synthetic data for all pairs and timeframes:

```bash
python scripts/download_data.py --mode generate --output-dir data/processed --start 2023-01-02 --end 2024-12-31
```

This produces M1 base data and resamples to M5, M15, H1, H4, D1.

## Generating Data

```bash
# Generate 2 years of synthetic M1 data, resample to all timeframes
python scripts/download_data.py --mode generate --output-dir data/processed

# Custom date range
python scripts/download_data.py --mode generate --start 2020-01-02 --end 2023-12-31 --seed 123
```

## Inspecting Data Quality

```bash
python scripts/download_data.py --mode inspect --output-dir data/processed
```

This runs comprehensive diagnostics on every dataset and reports:
- Total bars and date range
- Missing bars and gap analysis
- Duplicate timestamps
- Zero-range bars
- Extreme return detection
- Stale price sequences
- Spread statistics
- Overall quality score (0.0-1.0)

## Dataset Manifest

Each processed dataset includes a `manifest.json` tracking:
- Per-pair, per-timeframe metadata
- Date ranges and bar counts
- Source provenance
- Data quality scores

Load the manifest programmatically:

```python
from fx_smc_bot.data.manifest import DataManifest

manifest = DataManifest.load("data/processed/manifest.json")
print(manifest.summary())
```

## Using Data in Backtests

```bash
# Run backtest with Parquet data
python scripts/run_backtest.py --data-dir data/processed --output-dir results/

# The script auto-detects Parquet vs CSV format
```

Or programmatically:

```python
from fx_smc_bot.data.providers.parquet_provider import ParquetProvider
from fx_smc_bot.config import TradingPair, Timeframe

provider = ParquetProvider("data/processed")
series = provider.load(TradingPair.EURUSD, Timeframe.M15)
```

## Deriving Higher Timeframes

The framework supports resampling from lower to higher timeframes:

```python
from fx_smc_bot.data.resampling import resample
from fx_smc_bot.config import Timeframe

m1_series = provider.load(TradingPair.EURUSD, Timeframe.M1)
h1_series = resample(m1_series, Timeframe.H1)
```

## Data Quality Best Practices

1. Always inspect data before running backtests
2. Prefer M1 base data resampled up (avoids resampling artifacts)
3. Check for weekend gaps and missing trading hours
4. Be aware of spread widening during off-hours (Asian late, rollover)
5. Use the quality score to flag suspicious datasets (score < 0.8)
