# Real Data Readiness Report

**Generated**: 2026-04-11T19:03:25Z
**Source**: Yahoo Finance (yfinance)
**Pairs**: EURUSD, GBPUSD, USDJPY

## Dataset Inventory

| Pair | TF | Bars | Date Range | Missing% | Dups | Quality |
|------|----|------|------------|----------|------|---------|
| EURUSD | 1h | 12,354 | 2024-04-10T23:00:00 -> 2026-04-10T21:00:00 | 29.5% | 0 | 0.656 |
| EURUSD | 4h | 3,184 | 2024-04-10T20:00:00 -> 2026-04-10T20:00:00 | 27.3% | 0 | 0.681 |
| EURUSD | 15m | 5,673 | 2026-01-19T00:00:00 -> 2026-04-10T21:15:00 | 27.8% | 0 | 0.617 |
| GBPUSD | 1h | 12,356 | 2024-04-10T23:00:00 -> 2026-04-10T21:00:00 | 29.5% | 0 | 0.666 |
| GBPUSD | 4h | 3,184 | 2024-04-10T20:00:00 -> 2026-04-10T20:00:00 | 27.3% | 0 | 0.689 |
| GBPUSD | 15m | 5,673 | 2026-01-19T00:00:00 -> 2026-04-10T21:15:00 | 27.8% | 0 | 0.677 |
| USDJPY | 1h | 12,268 | 2024-04-10T23:00:00 -> 2026-04-10T20:00:00 | 30.0% | 0 | 0.679 |
| USDJPY | 4h | 3,177 | 2024-04-10T20:00:00 -> 2026-04-10T20:00:00 | 27.5% | 0 | 0.675 |
| USDJPY | 15m | 5,579 | 2026-01-19T00:00:00 -> 2026-04-10T20:45:00 | 29.0% | 0 | 0.680 |

## Per-Dataset Diagnostics

=== Data Quality: EURUSD / 1h ===
  Bars:           12,354
  Date range:     2024-04-10T23:00:00 -> 2026-04-10T21:00:00
  Missing bars:   5,163 (29.5%)
  Duplicates:     0
  Zero-range:     94
  Extreme returns: 50 (>5.0σ)
  Stale prices:   2
  Quality score:  0.656
  Issues:
    - High missing bar rate: 29.5%
    - 50 extreme returns (>5.0σ)
    - 2 stale-price sequences (>=5 bars)

=== Data Quality: EURUSD / 4h ===
  Bars:           3,184
  Date range:     2024-04-10T20:00:00 -> 2026-04-10T20:00:00
  Missing bars:   1,196 (27.3%)
  Duplicates:     0
  Zero-range:     5
  Extreme returns: 10 (>5.0σ)
  Stale prices:   0
  Quality score:  0.681
  Issues:
    - High missing bar rate: 27.3%
    - 10 extreme returns (>5.0σ)

=== Data Quality: EURUSD / 15m ===
  Bars:           5,673
  Date range:     2026-01-19T00:00:00 -> 2026-04-10T21:15:00
  Missing bars:   2,188 (27.8%)
  Duplicates:     0
  Zero-range:     27
  Extreme returns: 13 (>5.0σ)
  Stale prices:   7
  Quality score:  0.617
  Issues:
    - High missing bar rate: 27.8%
    - 13 extreme returns (>5.0σ)
    - 7 stale-price sequences (>=5 bars)

=== Data Quality: GBPUSD / 1h ===
  Bars:           12,356
  Date range:     2024-04-10T23:00:00 -> 2026-04-10T21:00:00
  Missing bars:   5,162 (29.5%)
  Duplicates:     0
  Zero-range:     104
  Extreme returns: 32 (>5.0σ)
  Stale prices:   1
  Quality score:  0.666
  Issues:
    - High missing bar rate: 29.5%
    - 32 extreme returns (>5.0σ)
    - 1 stale-price sequences (>=5 bars)

=== Data Quality: GBPUSD / 4h ===
  Bars:           3,184
  Date range:     2024-04-10T20:00:00 -> 2026-04-10T20:00:00
  Missing bars:   1,196 (27.3%)
  Duplicates:     0
  Zero-range:     3
  Extreme returns: 6 (>5.0σ)
  Stale prices:   0
  Quality score:  0.689
  Issues:
    - High missing bar rate: 27.3%
    - 6 extreme returns (>5.0σ)

=== Data Quality: GBPUSD / 15m ===
  Bars:           5,673
  Date range:     2026-01-19T00:00:00 -> 2026-04-10T21:15:00
  Missing bars:   2,188 (27.8%)
  Duplicates:     0
  Zero-range:     24
  Extreme returns: 17 (>5.0σ)
  Stale prices:   0
  Quality score:  0.677
  Issues:
    - High missing bar rate: 27.8%
    - 17 extreme returns (>5.0σ)

=== Data Quality: USDJPY / 1h ===
  Bars:           12,268
  Date range:     2024-04-10T23:00:00 -> 2026-04-10T20:00:00
  Missing bars:   5,250 (30.0%)
  Duplicates:     0
  Zero-range:     33
  Extreme returns: 39 (>5.0σ)
  Stale prices:   0
  Quality score:  0.679
  Issues:
    - High missing bar rate: 30.0%
    - 39 extreme returns (>5.0σ)

=== Data Quality: USDJPY / 4h ===
  Bars:           3,177
  Date range:     2024-04-10T20:00:00 -> 2026-04-10T20:00:00
  Missing bars:   1,203 (27.5%)
  Duplicates:     0
  Zero-range:     0
  Extreme returns: 16 (>5.0σ)
  Stale prices:   0
  Quality score:  0.675
  Issues:
    - High missing bar rate: 27.5%
    - 16 extreme returns (>5.0σ)

=== Data Quality: USDJPY / 15m ===
  Bars:           5,579
  Date range:     2026-01-19T00:00:00 -> 2026-04-10T20:45:00
  Missing bars:   2,281 (29.0%)
  Duplicates:     0
  Zero-range:     10
  Extreme returns: 18 (>5.0σ)
  Stale prices:   0
  Quality score:  0.680
  Issues:
    - High missing bar rate: 29.0%
    - 18 extreme returns (>5.0σ)

## Overall Assessment

Issues detected in the following datasets:
- **EURUSD/1h**: High missing bar rate: 29.5%; 50 extreme returns (>5.0σ); 2 stale-price sequences (>=5 bars)
- **EURUSD/4h**: High missing bar rate: 27.3%; 10 extreme returns (>5.0σ)
- **EURUSD/15m**: High missing bar rate: 27.8%; 13 extreme returns (>5.0σ); 7 stale-price sequences (>=5 bars)
- **GBPUSD/1h**: High missing bar rate: 29.5%; 32 extreme returns (>5.0σ); 1 stale-price sequences (>=5 bars)
- **GBPUSD/4h**: High missing bar rate: 27.3%; 6 extreme returns (>5.0σ)
- **GBPUSD/15m**: High missing bar rate: 27.8%; 17 extreme returns (>5.0σ)
- **USDJPY/1h**: High missing bar rate: 30.0%; 39 extreme returns (>5.0σ)
- **USDJPY/4h**: High missing bar rate: 27.5%; 16 extreme returns (>5.0σ)
- **USDJPY/15m**: High missing bar rate: 29.0%; 18 extreme returns (>5.0σ)

**Minimum quality score**: 0.617
**Verdict**: REVIEW NEEDED