# Gate C.3R — Split Boundaries and Holdout Policy

## Split Boundaries

```
development: 2015-01-01 through 2019-12-31  (5 years)
validation:  2020-01-01 through 2022-12-31  (3 years)
holdout:     2023-01-01 through 2025-12-31  (3 years)
```

### Rationale

- **Development** (2015-2019): Covers pre-COVID markets with diverse rate
  environments and sufficient history for structural analysis
- **Validation** (2020-2022): Includes COVID shock (2020), recovery, and
  2022 monetary tightening regime — tests robustness across regime breaks
- **Holdout** (2023-2025): Most recent data, untouched until final evaluation

### Coverage Assessment
- Data availability: Dukascopy M1 bid/ask confirmed available for all three
  periods (verified with 2023-06 sample)
- Regime diversity: The three splits naturally capture distinct FX regimes
- COVID period: Fully contained in validation split, not leaking into
  development or holdout
- 2022 monetary-policy regime: Contained in validation split
- Independent days: Each split contains >700 trading days

## Holdout Access Control

### Implementation

File: `src/fx_smc_bot/data/holdout_access.py`

### Access Rules

| Purpose            | Holdout Access | Enforcement           |
|--------------------|--------------|-----------------------|
| DATA_QUALITY       | PERMITTED     | Automatic pass-through |
| ALPHA_RESEARCH     | DENIED        | ValueError raised      |
| EVENT_DETECTION    | DENIED        | ValueError raised      |
| STRATEGY_BACKTEST  | DENIED        | ValueError raised      |
| CAMPAIGN           | DENIED        | ValueError raised      |

### API

```python
from fx_smc_bot.data.holdout_access import (
    check_holdout_access,
    guard_holdout,
    AccessPurpose,
)

# Check without raising
violation = check_holdout_access("2024-01-01", "2024-06-30", AccessPurpose.ALPHA_RESEARCH)
if violation:
    print(violation.message)  # "Access DENIED: ..."

# Guard with exception
guard_holdout("2024-01-01", "2024-06-30", AccessPurpose.CAMPAIGN)
# Raises ValueError if holdout is locked

# Filter timestamps to a split
from fx_smc_bot.data.holdout_access import filter_to_split
mask = filter_to_split(timestamps_array, "development")
```

### Test Coverage
- `test_development_access_permitted`: Development dates always accessible
- `test_holdout_alpha_access_denied`: Alpha research blocked on holdout
- `test_holdout_quality_access_permitted`: Quality checks pass on holdout
- `test_holdout_event_detection_denied`: Event detection blocked
- `test_holdout_campaign_denied`: Campaign access raises ValueError
- `test_unlock_permits_access`: unlock_holdout() enables access
- `test_filter_to_split`: Timestamp filtering works correctly
- `test_get_split_for_timestamp`: Split lookup works correctly

## Proof Holdout Alpha Remained Untouched

1. No event detection, strategy backtest, or campaign code accessed any
   data in the 2023-01-01 to 2025-12-31 range
2. Data quality inspection of the 2023-06 holdout sample is permitted and
   was used solely for bid/ask alignment, spread statistics, and OHLC
   invariant validation
3. No Sharpe, profit factor, win rate, expectancy, or PnL was computed
   on any data
4. The `holdout_access.py` module enforces these boundaries programmatically
