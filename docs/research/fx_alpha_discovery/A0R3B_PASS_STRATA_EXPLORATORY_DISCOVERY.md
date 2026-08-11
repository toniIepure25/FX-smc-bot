# A0R3B Pass-Strata Exploratory Discovery

Status: `EXPLORATORY_NOT_VALIDATED_ALPHA`

Freeze hash: `c8207b7e49eccfdc03542855b7f9a34a948241c9eee43fa01f632641e9467510`
Evaluated trials: `86` of `1200` registered trials.
Shortlist size: `0`
2018+ market/outcome files opened: `[]`

## PASS Strata

| Pair | Year | M1 rows | M5 rows | M1 hash | M5 hash |
|---|---:|---:|---:|---|---|
| EURUSD | 2015 | 359813 | 72070 | `1bec582fb8af0511` | `5dd64a14a54bcde1` |
| GBPUSD | 2017 | 373252 | 74694 | `6579ae4579100172` | `8900f92e6f7274b0` |
| USDJPY | 2015 | 372807 | 74698 | `56958856f4ef1641` | `b9bd7f470bb517fb` |
| USDJPY | 2016 | 373768 | 74873 | `d0f1c6ed53ddf778` | `82ce9b32fb8d7ea6` |
| USDJPY | 2017 | 372641 | 74667 | `5f5f71ca19bb7923` | `e17fcb9b2e37cdb9` |

Excluded failed strata: `EURUSD-2016`, `EURUSD-2017`, `GBPUSD-2015`, `GBPUSD-2016`

## Trial Eligibility By Family

| Family | Eligible | Ineligible |
|---|---:|---:|
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | 14 | 106 |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | 10 | 86 |
| F03_VOLATILITY_BREAKOUT | 11 | 85 |
| F04_LIQUIDITY_SHOCK_REVERSAL | 7 | 89 |
| F05_SPREAD_AWARE_EXECUTION_GATING | 9 | 75 |
| F06_CROSS_PAIR_LEAD_LAG | 0 | 120 |
| F07_CURRENCY_FACTOR_RESIDUALS | 0 | 96 |
| F08_TRIANGULAR_CONSISTENCY_RESIDUALS | 0 | 84 |
| F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL | 0 | 96 |
| F10_INTRADAY_SEASONALITY | 9 | 75 |
| F11_REGIME_CONDITIONED_TREND_REVERSAL | 12 | 96 |
| F12_COST_SENSITIVE_ML_ABSTENTION | 14 | 106 |

## Multiple Testing

- White Reality Check p: `1.0`
- Hansen SPA p: `0.0`
- PBO: `NOT_APPLICABLE`
- PBO note: `fewer_than_two_multi_stratum_candidates`

## Cost Stress

- 1.5x survivors: `0`
- 2.0x survivors: `0`

## Top 10 Exploratory Candidates

| Trial | Family | Units | Tier | Trades | Net bps | Net/trade | Sharpe | BH-FDR | PSR | DSR | 1.5x | 2.0x |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| A0R1-01-0092 | F01_SESSION_OPENING_MOMENTUM_REVERSAL | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3595 | -1059.984 | -0.294849 | -3.165 | 1.000000 | 0.183463 | 0.148822 | False | False |
| A0R1-03-0029 | F03_VOLATILITY_BREAKOUT | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3707 | -1862.836 | -0.502519 | -3.042 | 1.000000 | 0.195765 | 0.161124 | False | False |
| A0R1-03-0065 | F03_VOLATILITY_BREAKOUT | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3707 | -1862.836 | -0.502519 | -3.042 | 1.000000 | 0.195765 | 0.161124 | False | False |
| A0R1-03-0011 | F03_VOLATILITY_BREAKOUT | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3888 | -1902.059 | -0.489213 | -3.125 | 1.000000 | 0.187533 | 0.152892 | False | False |
| A0R1-03-0047 | F03_VOLATILITY_BREAKOUT | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3888 | -1902.059 | -0.489213 | -3.125 | 1.000000 | 0.187533 | 0.152892 | False | False |
| A0R1-03-0083 | F03_VOLATILITY_BREAKOUT | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3888 | -1902.059 | -0.489213 | -3.125 | 1.000000 | 0.187533 | 0.152892 | False | False |
| A0R1-01-0056 | F01_SESSION_OPENING_MOMENTUM_REVERSAL | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 5004 | -2289.430 | -0.457520 | -6.883 | 1.000000 | 0.000000 | 0.000000 | False | False |
| A0R1-01-0110 | F01_SESSION_OPENING_MOMENTUM_REVERSAL | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 3580 | -2445.958 | -0.683228 | -6.019 | 1.000000 | 0.000000 | 0.000000 | False | False |
| A0R1-01-0074 | F01_SESSION_OPENING_MOMENTUM_REVERSAL | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 4440 | -2522.615 | -0.568156 | -6.221 | 1.000000 | 0.000000 | 0.000000 | False | False |
| A0R1-01-0119 | F01_SESSION_OPENING_MOMENTUM_REVERSAL | 1 | SINGLE_STRATUM_EXPLORATORY_LEAD | 7702 | -2529.729 | -0.328451 | -6.110 | 1.000000 | 0.000000 | 0.000000 | False | False |

## Top Exploratory Shortlist

| Trial | Family | Units | Tier | Trades | Net bps | Net/trade | Sharpe | BH-FDR | PSR | DSR | 1.5x | 2.0x |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|

## Interesting Single-Stratum Leads

| Trial | Family | Stratum | Net bps | Sharpe | BH-FDR | DSR |
|---|---|---|---:|---:|---:|---:|
