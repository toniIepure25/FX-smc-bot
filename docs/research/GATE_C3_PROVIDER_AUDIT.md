# Gate C.3 — Provider Audit

## Dukascopy Provider

### Bug Found: Universal Price Scaling
**File**: `src/fx_smc_bot/data/historical_providers.py`
**Original**: `ask_raw / 100000.0` for all pairs
**Impact**: USDJPY prices would be ~0.001 instead of ~140.0

**Fix**: Added `InstrumentMeta` model with per-pair `raw_price_scale`:
- EURUSD, GBPUSD: `100,000` (5 decimal places)
- USDJPY, GBPJPY: `1,000` (3 decimal places)

Added plausible price range validation to reject implausible values.

### Improvements
- `_parse_bi5` now accepts `pair` parameter for correct scaling
- Rejects ticks where ask < bid
- Rejects spreads > 100 pips
- Rejects prices outside plausible range

### Remaining Limitations
- Acquisition is not yet streamed/chunked for multi-year downloads
- Parallelism not yet implemented (configurable workers planned)
- Weekend no-data intervals treated the same as network failures

## OANDA Provider

### Bug Found: Invalid from+to+count
**File**: `src/fx_smc_bot/data/historical_providers.py`
**Original**: `?from=...&to=...&count=5000`
**Impact**: OANDA API prohibits specifying count when both from and to are set

**Fix**: Removed `count` parameter. Implemented bounded time-window batching
using `batch_delta = granularity_minutes * 4500`. Added `smooth=false`
and `includeFirst=true` parameters.

### Improvements
- Valid bounded batching without count
- De-duplication of boundary candles
- Incomplete candle rejection
- Request continues if empty batch returned

## MT5 Importer

### Bug Found: Timezone Not Applied
**File**: `src/fx_smc_bot/data/historical_providers.py`
**Original**: `broker_timezone` parameter accepted but never used
**Impact**: All timestamps treated as UTC regardless of broker timezone

**Fix**: Applied IANA timezone conversion using `zoneinfo.ZoneInfo`.
Timestamps are converted to UTC before storage.

### Improvements
- Returns `MT5ImportResult` with metadata (price_type, spread status,
  duplicate count, non-monotonic count)
- Distinguishes `BID_ONLY_OR_MID` vs `BID_ASK` price type
- Reports `historical_spread_available` flag
- `BID_ONLY_OR_MID` data cannot receive final research certification
