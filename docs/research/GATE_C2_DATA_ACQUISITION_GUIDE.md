# Gate C.2 — Data Acquisition Guide

## Provider Summary

| Provider | Type | Bid/Ask | Automated | Credentials |
|----------|------|---------|-----------|-------------|
| Dukascopy | Tick → M1/M5 | Yes | Partial | None (public) |
| OANDA | M1 candles | Yes | Yes | OANDA_API_TOKEN |
| MT5 | CSV export | Mid-only | No | Broker account |

## Dukascopy (Primary)

### Automated Download

```python
from fx_smc_bot.data.historical_providers import DukascopyProvider

provider = DukascopyProvider(cache_dir=Path("data/raw/dukascopy"))
result = provider.download(
    pair=TradingPair.EURUSD,
    start=datetime(2020, 1, 1),
    end=datetime(2020, 1, 31),
    resolution="M1",
)
```

Downloads bi5-compressed tick files from `datafeed.dukascopy.com`.
Resumable (caches to local files). Resamples ticks to requested resolution.

### Manual Fallback (JForex)

If automated download fails (rate limiting, server issues):

1. Download JForex from https://www.dukascopy.com/trading-tools/jforex-platform/
2. Open Historical Data Export tool
3. Configure:
   - Instrument: EUR/USD, GBP/USD, USD/JPY
   - Period: Ticks or M1
   - Date range: as needed
   - **Bid/Ask: Both** (critical)
   - Format: CSV
4. Export to `data/raw/dukascopy/<PAIR>/`

## OANDA (Secondary)

### Setup

```bash
export OANDA_API_TOKEN="your-token-here"
```

### Usage

```python
from fx_smc_bot.data.historical_providers import OandaProvider

provider = OandaProvider(practice=True)
if provider.is_configured:
    result = provider.download(
        pair=TradingPair.EURUSD,
        start=datetime(2023, 1, 1),
        end=datetime(2023, 1, 31),
        resolution="M1",
    )
```

Requests bid and ask components (`price=BA`). Batches requests to
respect the 5000-candle limit. De-duplicates at batch boundaries.
Rejects incomplete candles.

**The project must remain usable without OANDA credentials.**

## MT5 (Broker Calibration)

### Usage

```python
from fx_smc_bot.data.historical_providers import MT5CsvImporter

importer = MT5CsvImporter(broker_timezone="UTC")
series = importer.import_csv(
    path=Path("data/raw/mt5/EURUSD_M1.csv"),
    pair=TradingPair.EURUSD,
)
```

**Note**: MT5 CSV exports are typically mid-price only.
The importer sets `ask = bid` (zero spread). Consumers must apply
spread separately.

## Cross-Validation

```python
from fx_smc_bot.data.historical_providers import cross_validate_providers

result = cross_validate_providers(
    dukascopy_series, oanda_series,
    "dukascopy", "oanda",
)
# Returns: common timestamps, price diff, return correlation, spread comparison
```

## Next Steps for Full Data Acquisition

1. Attempt Dukascopy download for EURUSD 2015-2024
2. If successful, download GBPUSD and USDJPY
3. Cross-validate against OANDA if credentials available
4. Run data quality diagnostics
5. Create data manifests with SHA-256 checksums
6. Certify datasets for research use
