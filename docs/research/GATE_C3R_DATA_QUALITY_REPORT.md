# Gate C.3R — Data Quality Report

## Overview

Data quality analysis of M1 bid/ask data acquired via `dukascopy-node` 1.46.4.
All timestamps are UTC. Data was downloaded with `utcOffset=0`, `ignoreFlats=true`.

## Acquisition Summary

| Pair   | Months | Bid Rows | Ask Rows | Joined Rows |
|--------|--------|----------|----------|-------------|
| EURUSD | 1      | 31,282   | 25,732   | 25,732      |
| GBPUSD | 1      | 24,751   | 24,219   | 17,565      |
| USDJPY | 1      | 31,375   | 31,375   | 31,375      |
| **Total** | **3** | **87,408** | **81,326** | **74,672** |

## Structural Integrity

### All pairs pass:
- Monotonic timestamps: YES
- Valid bid OHLC (high ≥ low, high ≥ open/close, low ≤ open/close): YES
- Valid ask OHLC: YES
- No negative or zero prices: YES
- No negative spread at open: YES (0 violations)
- No negative spread at close: YES (0 violations)

### Bid/Ask Alignment

| Pair   | Both Present | Bid Only | Ask Only | Unpaired Rate |
|--------|-------------|----------|----------|---------------|
| EURUSD | 25,732      | 5,550    | 0        | 17.7%         |
| GBPUSD | 17,565      | 7,186    | 6,654    | 44.0%         |
| USDJPY | 31,375      | 0        | 0        | 0.0%          |

## Spread Statistics

| Pair   | Median  | P90     | P95     | P99     | Max      |
|--------|---------|---------|---------|---------|----------|
| EURUSD | 0.3 pip | 0.4 pip | 0.6 pip | 3.0 pip | 7.1 pip  |
| GBPUSD | 1.0 pip | 1.3 pip | 2.3 pip | 7.3 pip | 36.9 pip |
| USDJPY | 0.6 pip | 0.9 pip | 1.3 pip | 5.4 pip | 27.7 pip |

All spreads are plausible for institutional-grade M1 FX data.

## Session Coverage

| Pair   | Expected Session Min | Observed Min | Session Missing % |
|--------|---------------------|-------------|-------------------|
| EURUSD | 31,560              | 25,732      | 18.47%            |
| GBPUSD | 27,480              | 17,565      | 36.08%            |
| USDJPY | 31,560              | 31,375      | 0.59%             |

Weekend minutes are excluded from the session-missing calculation.

## Market Calendar Integration

The `market_calendar.py` module classifies gaps as:
- **Weekend**: Saturday/Sunday closure (excluded from missing %)
- **Holiday**: New Year's Day, Christmas (excluded from missing %)
- **Normal micro-gap**: ≤5 minutes (acceptable)
- **Minor gap**: ≤1 hour (flagged but acceptable)
- **Unexplained gap**: >1 hour during expected session (concerning)

## Certification

| Pair   | Status                              | Notes                    |
|--------|-------------------------------------|--------------------------|
| EURUSD | CERTIFIED_PRIMARY_DEVELOPMENT_DATA  | Good coverage, 0 invariant violations |
| GBPUSD | CERTIFIED_EXPLORATORY_ONLY          | High unpaired rate (44%), needs re-acquisition |
| USDJPY | CERTIFIED_PRIMARY_DEVELOPMENT_DATA  | Near-perfect coverage (99.4%) |

### Certification Criteria
- **CERTIFIED_PRIMARY_DEVELOPMENT_DATA**: Genuine bid/ask, ≥80% session coverage,
  correct scaling, correct UTC timestamps, 0 invariant violations
- **CERTIFIED_EXPLORATORY_ONLY**: Data present but incomplete or has quality issues
- **REJECTED**: Fundamental quality problems

## Resampling Verification

All three pairs successfully resampled from M1 to:
- M5 (5-minute bars)
- M15 (15-minute bars)
- H1 (hourly bars)
- H4 (4-hour bars)

Bid and ask are resampled independently — ask OHLC is never derived from
bid plus average spread.
