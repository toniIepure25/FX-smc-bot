# Gate C.3 — Split and Holdout Policy

## Proposed Chronological Boundaries

Based on data availability assessment (pending full acquisition):

| Partition | Period | Years | Purpose |
|-----------|--------|-------|---------|
| Development | 2015-01-01 → 2019-12-31 | 5 | Strategy development, parameter tuning |
| Validation | 2020-01-01 → 2022-12-31 | 3 | Frozen strategy evaluation |
| Holdout | 2023-01-01 → 2025-12-31 | 3 | Locked final test |

### Regime Considerations
- **2015-2019**: Pre-COVID, multiple rate cycles, low volatility late period
- **2020**: COVID shock, extreme volatility, stress test
- **2021-2022**: Post-COVID recovery, aggressive monetary tightening (2022)
- **2023-2025**: Post-tightening regime, potentially different dynamics

### Holdout Access Policy
- Development commands cannot read holdout data
- Validation commands cannot read holdout data
- Final holdout requires explicit `--unlock-final-holdout` flag
- Split boundaries stored in `results/gate_c3/dataset_freeze.json`
- Tests verify holdout isolation

### If Data Period is Shorter
If only 2015-2025 is available:
- Development: 2015-01-01 → 2019-12-31
- Validation: 2020-01-01 → 2022-12-31
- Holdout: 2023-01-01 → 2025-12-31

If only 2018-2025:
- Development: 2018-01-01 → 2021-06-30
- Validation: 2021-07-01 → 2023-06-30
- Holdout: 2023-07-01 → 2025-12-31

The exact boundaries will be frozen after data acquisition confirms
coverage.
