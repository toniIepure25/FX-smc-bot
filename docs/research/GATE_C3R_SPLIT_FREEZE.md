# Gate C.3R — Split and Holdout Freeze

## Proposed Split Boundaries

| Split | Start | End |
|-------|-------|-----|
| Development | 2015-01-01 | 2019-12-31 |
| Validation | 2020-01-01 | 2022-12-31 |
| Holdout | 2023-01-01 | 2025-12-31 |

## Rationale

- Development (5 years): covers diverse regimes (2015 SNB shock, 2016
  Brexit, 2017–2019 low-vol environment)
- Validation (3 years): includes COVID crash (2020), post-COVID recovery,
  2022 rate-hiking cycle
- Holdout (3 years): recent market regime, untouched for final evaluation

## Holdout Access Control

### Permitted
- Data quality inspection (coverage, spread statistics, gap analysis)
- Structural validation (timestamp ordering, OHLC invariants)
- Acquisition and integrity tools

### Prohibited
- Strategy execution on holdout data
- Detector event analysis on holdout data
- Any alpha-related inspection
- Parameter optimization using holdout data

### Technical Enforcement
- Split boundaries defined in `results/gate_c3r/dataset_freeze.json`
- Campaign commands must check timestamps against split boundaries
- Only a future dedicated unlock command may access holdout for execution

## Proof Holdout Untouched

No detector, strategy, or campaign code was executed on any data from
the holdout period (2023-01-01 onwards) during this gate. The only
operations on 2023-06 data were:
1. Download (data acquisition)
2. Alignment (bid/ask join by timestamp)
3. Quality validation (spread statistics, OHLC invariants)
4. Parquet conversion (format transformation)

No strategy signals, trade intents, fills, or PnL were computed.
