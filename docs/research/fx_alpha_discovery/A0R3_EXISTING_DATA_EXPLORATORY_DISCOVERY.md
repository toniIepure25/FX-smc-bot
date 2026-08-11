# A0R3 Existing-Data Exploratory Discovery

Status: `EXPLORATORY_EXISTING_DATA_ONLY`

This run uses 2015-2017 only for exploratory discovery. It does not read or evaluate 2018+ price, return, strategy, confirmation, validation, replication, or quarantine outcomes.

Eligibility verdict: `BLOCKED`
Frozen dataset hash: `700874a50eb53c701edcafd061683f17bf54e40fbf7ce00a1f7f4381f8bad069`
Evaluated trials: `0` of `1200` candidate-equivalent registered trials.
Shortlist size: `0`
2018+ market/outcome data accessed: `False`

## Prospective Split

| Stage | Start | End | A0R3 access |
|---|---|---|---|
| Exploratory discovery | 2015-01-01 | 2017-12-31 | price/outcome allowed |
| Internal confirmation | 2018-01-01 | 2018-12-31 | metadata only |
| External validation | 2019-01-01 | 2019-12-31 | metadata only |
| Replication | 2020-01-01 | 2022-12-31 | not accessed |
| Quarantine | 2023-01-01 | 2025-12-31 | not accessed |

## Existing Data Inventory

Raw root: `D:\ComputaCenter\FX-smc-bot\data\raw\dukascopy-node`

| Pair | Year | Bid | Ask | Bid M1 rows | Ask M1 rows | Complete both-side days | Missing open-market days | M5 constructible | Spread executable | Manifest set hash |
|---|---:|---|---|---:|---:|---:|---:|---|---|---|
| EURUSD | 2015 | True | True | 368624 | 364132 | 302 | 11 | True | True | `51375f4f18140b4a` |
| EURUSD | 2016 | True | True | 326686 | 325682 | 246 | 66 | True | True | `6cd89b77b85737b8` |
| EURUSD | 2017 | True | True | 273287 | 273494 | 176 | 140 | True | True | `53e43aa3124b4c67` |
| EURUSD | 2018 | True | True | 310184 | 288864 | 197 | 117 | True | True | `eef701d500ff6d7d` |
| EURUSD | 2019 | True | True | 364795 | 363363 | 299 | 14 | True | True | `8ab059b66117d5f3` |
| GBPUSD | 2015 | True | True | 321627 | 322881 | 229 | 85 | True | True | `ba22a26b8960bc50` |
| GBPUSD | 2016 | True | True | 356847 | 352407 | 293 | 22 | True | True | `05c79231fd3e3047` |
| GBPUSD | 2017 | True | True | 373252 | 373252 | 312 | 0 | True | True | `ff8dcb31f3ea5160` |
| GBPUSD | 2018 | True | True | 373303 | 373303 | 313 | 0 | True | True | `a051edba1d07d434` |
| GBPUSD | 2019 | True | True | 364305 | 367479 | 302 | 11 | True | True | `2ab9a26f038c4eef` |
| USDJPY | 2015 | True | True | 372807 | 372807 | 313 | 0 | True | True | `61b14ece5179e39c` |
| USDJPY | 2016 | True | True | 373768 | 373768 | 312 | 0 | True | True | `2151caeee7ffb5be` |
| USDJPY | 2017 | True | True | 372641 | 372641 | 312 | 0 | True | True | `e44238dff53f2e5a` |
| USDJPY | 2018 | True | True | 371471 | 372791 | 312 | 1 | True | True | `8c07ddabda61a89a` |
| USDJPY | 2019 | True | True | 365218 | 370181 | 303 | 10 | True | True | `b8b9e5cf985bc603` |

## 2015-2017 Eligibility Gate

| Pair | Year | Verdict | M1 rows | Coverage | Missing open-market days | Longest gap minutes | Negative spreads | M1 hash | M5 hash |
|---|---:|---|---:|---:|---:|---:|---:|---|---|
| EURUSD | 2015 | PASS | 359813 | 0.957357 | 11 | 5941 | 0 | `b2a4f52e2b1e4269` | `5dd64a14a54bcde1` |
| EURUSD | 2016 | FAIL | 289700 | 0.770807 | 66 | 19981 | 0 | `d3127b1c23fcd34a` | `e9613e78f57cf609` |
| EURUSD | 2017 | FAIL | 210681 | 0.562716 | 140 | 36001 | 0 | `2e72c189b416620b` | `dff419a87027ccb1` |
| GBPUSD | 2015 | FAIL | 272681 | 0.725524 | 85 | 18721 | 0 | `253f571edee37cc8` | `a978e0023a471a62` |
| GBPUSD | 2016 | FAIL | 352407 | 0.937652 | 22 | 33241 | 0 | `c546aa010436203c` | `bd444e224a438b4d` |
| GBPUSD | 2017 | PASS | 373252 | 0.996934 | 0 | 2942 | 0 | `081c145277db47fe` | `8900f92e6f7274b0` |
| USDJPY | 2015 | PASS | 372807 | 0.991930 | 0 | 3724 | 0 | `38453d65afca4f23` | `b9bd7f470bb517fb` |
| USDJPY | 2016 | PASS | 373768 | 0.994487 | 0 | 2941 | 0 | `5d375b5706fa1597` | `82ce9b32fb8d7ea6` |
| USDJPY | 2017 | PASS | 372641 | 0.995302 | 0 | 2941 | 0 | `ae985d13e00efd63` | `e17fcb9b2e37cdb9` |

Blockers: `EURUSD-2016:EXPLORATORY_MINIMUM_QUALITY_FAILED`, `EURUSD-2017:EXPLORATORY_MINIMUM_QUALITY_FAILED`, `GBPUSD-2015:EXPLORATORY_MINIMUM_QUALITY_FAILED`, `GBPUSD-2016:EXPLORATORY_MINIMUM_QUALITY_FAILED`

This is not confirmatory A0R2 certification, and the unresolved tick-audit criterion is not required for the frozen families that need only M1 bid/ask-derived fields.

## Dataset Freeze

Freeze status: `BLOCKED`
Frozen pair-years: `5` of `9` exploratory pair-years.
No raw market data was modified.

## Trial Eligibility By Family

| Family | Eligible | Ineligible |
|---|---:|---:|
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | 14 | 106 |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | 10 | 86 |
| F03_VOLATILITY_BREAKOUT | 11 | 85 |
| F04_LIQUIDITY_SHOCK_REVERSAL | 7 | 89 |
| F05_SPREAD_AWARE_EXECUTION_GATING | 9 | 75 |
| F06_CROSS_PAIR_LEAD_LAG | 0 | 120 |
| F07_CURRENCY_FACTOR_RESIDUALS | 11 | 85 |
| F08_TRIANGULAR_CONSISTENCY_RESIDUALS | 0 | 84 |
| F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL | 11 | 85 |
| F10_INTRADAY_SEASONALITY | 9 | 75 |
| F11_REGIME_CONDITIONED_TREND_REVERSAL | 12 | 96 |
| F12_COST_SENSITIVE_ML_ABSTENTION | 14 | 106 |

## Multiple Testing

- White Reality Check p: `NOT_RUN_BLOCKED`
- Hansen SPA p: `NOT_RUN_BLOCKED`
- PBO: `NOT_RUN_BLOCKED`

## Cost Stress

- 1.5x cost survivors: `NOT_RUN_BLOCKED`
- 2.0x cost survivors: `NOT_RUN_BLOCKED`

## Top Exploratory Shortlist

| Trial | Family | Pair | Net bps | Sharpe | BH-FDR | DSR |
|---|---|---|---:|---:|---:|---:|
