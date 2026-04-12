# Data Source Comparison and Spread Sensitivity Report

Generated: 2026-04-12T13:31:50.454098

## Data Quality Diagnostics (Yahoo Finance 1H)

### EURUSD

```
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
```

### GBPUSD

```
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
```

### USDJPY

```
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
```


## Cost Sensitivity — Train Period

| Cost Mult |   Sharpe |     PF |          PnL |   Win% |
|-----------|----------|--------|--------------|--------|
|      0.50 |    2.107 |   5.75 | 8,681,165.62 | 70.6% |
|      0.75 |    2.091 |   5.66 | 8,617,149.50 | 68.2% |
|      1.00 |    2.076 |   5.58 | 8,553,133.38 | 56.3% |
|      1.25 |    2.060 |   5.47 | 8,489,117.25 | 54.2% |
|      1.50 |    2.045 |   5.37 | 8,425,101.13 | 53.6% |
|      2.00 |    2.014 |   5.17 | 8,297,068.89 | 52.2% |
|      3.00 |    1.951 |   4.80 | 8,041,004.40 | 49.9% |

## Cost Sensitivity — Holdout Period

| Cost Mult |   Sharpe |     PF |          PnL |   Win% |
|-----------|----------|--------|--------------|--------|
|      0.50 |    0.231 |   1.17 |     6,343.17 | 43.1% |
|      0.75 |    0.192 |   1.14 |     5,279.09 | 41.9% |
|      1.00 |    0.154 |   1.11 |     4,215.01 | 31.2% |
|      1.25 |    0.115 |   1.08 |     3,150.93 | 29.6% |
|      1.50 |    0.076 |   1.05 |     2,086.84 | 28.5% |
|      2.00 |   -0.002 |   1.00 |       -41.32 | 26.5% |
|      3.00 |   -0.157 |   0.90 |    -4,297.65 | 24.1% |

## Execution Stress Scenarios — Holdout

| Scenario        | Trades |   Sharpe |     PF |   MaxDD |          PnL |
|-----------------|--------|----------|--------|---------|--------------|
| optimistic      |    257 |    0.187 |   1.14 |   13.0% |     5,173.81 |
| neutral         |    253 |    0.154 |   1.11 |   12.7% |     4,215.01 |
| conservative    |    187 |    0.123 |   1.10 |   12.8% |     3,062.39 |
| stressed        |    178 |    0.029 |   1.01 |   12.8% |       427.99 |

### Degradation vs Neutral Baseline

- **optimistic**: PnL +22.8%, Sharpe +0.034
- **conservative**: PnL -27.4%, Sharpe -0.031
- **stressed**: PnL -89.8%, Sharpe -0.124

## Spread Assumption Analysis

Current fixed spread: 1.5 pips for all pairs.

Typical institutional spreads:

- EURUSD: 0.1-0.3 pips
- GBPUSD: 0.3-0.8 pips
- USDJPY: 0.2-0.5 pips

Yahoo Finance data does not include spreads. The 1.5 pip assumption is 
conservative for major pairs (3-15x wider than institutional), which 
means the strategy faces **higher costs than institutional reality**.

Strategy breaks even at ~2.0x current spread (3.0 pips equivalent).


## Key Findings

1. Yahoo Finance provides adequate data quality for structure detection, 
but lacks bid/ask spreads.

2. Fixed 1.5 pip spread is conservative for major pairs — 
actual performance may be better under institutional execution.

3. Cost sensitivity analysis above shows how Sharpe degrades with higher costs.
