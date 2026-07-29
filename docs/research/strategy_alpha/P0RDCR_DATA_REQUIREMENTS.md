# Gate P0-R-DCR Data Requirements

Status: `FAIL`

Resolved requirements: permitted dates are 2015-01-01 through 2022-12-31; primary execution instruments are EURUSD and GBPUSD; sessions and M5 bid/ask execution fields are recorded in the frozen artifacts.

The exact acquisition contract cannot be reconstructed without changing the freeze.

## Unresolved Provenance

- `SMC_A_SWEEP_REVERSAL_V1` / `instrument_role.USDJPY`: P0 does not freeze whether the YAML control instrument is required.
- `SMC_A_SWEEP_REVERSAL_V1` / `timezone.london`: No timezone identifier is frozen for this session.
- `SMC_A_SWEEP_REVERSAL_V1` / `timezone.new_york`: No timezone identifier is frozen for this session.
- `SMC_A_SWEEP_REVERSAL_V1` / `source_resolution`: P0-R records M1/tick as alternatives and does not select one exact source.
- `SMC_A_SWEEP_REVERSAL_V1` / `warm_up_duration`: No exact duration is frozen; detector and ATR history needs are not quantified.
- `SMC_A_SWEEP_REVERSAL_V1` / `exit_horizon`: P0 explicitly records maximum holding/session cutoff implementation as PARTIAL.
- `SMC_A_SWEEP_REVERSAL_V1` / `session_calendar_coverage`: No complete holiday, weekend, and DST calendar contract is frozen.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `instrument_role.USDJPY`: P0 does not freeze whether the YAML control instrument is required.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `timezone.london`: No timezone identifier is frozen for this session.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `timezone.new_york`: No timezone identifier is frozen for this session.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `source_resolution`: P0-R records M1/tick as alternatives and does not select one exact source.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `warm_up_duration`: No exact duration is frozen; detector and ATR history needs are not quantified.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `exit_horizon`: P0 explicitly records maximum holding/session cutoff implementation as PARTIAL.
- `SMC_B_ACCEPTANCE_CONTINUATION_V1` / `session_calendar_coverage`: No complete holiday, weekend, and DST calendar contract is frozen.
- `SMC_C_LONDON_OPENING_RANGE_V1` / `instrument_role.USDJPY`: P0 does not freeze whether the YAML control instrument is required.
- `SMC_C_LONDON_OPENING_RANGE_V1` / `source_resolution`: P0-R records M1/tick as alternatives and does not select one exact source.
- `SMC_C_LONDON_OPENING_RANGE_V1` / `warm_up_duration`: No exact duration is frozen; detector and ATR history needs are not quantified.
- `SMC_C_LONDON_OPENING_RANGE_V1` / `exit_horizon`: P0 explicitly records maximum holding/session cutoff implementation as PARTIAL.
- `SMC_C_LONDON_OPENING_RANGE_V1` / `session_calendar_coverage`: No complete holiday, weekend, and DST calendar contract is frozen.
- `SMC_C_NEWYORK_OPENING_RANGE_V1` / `instrument_role.USDJPY`: P0 does not freeze whether the YAML control instrument is required.
- `SMC_C_NEWYORK_OPENING_RANGE_V1` / `source_resolution`: P0-R records M1/tick as alternatives and does not select one exact source.
- `SMC_C_NEWYORK_OPENING_RANGE_V1` / `warm_up_duration`: No exact duration is frozen; detector and ATR history needs are not quantified.
- `SMC_C_NEWYORK_OPENING_RANGE_V1` / `exit_horizon`: P0 explicitly records maximum holding/session cutoff implementation as PARTIAL.
- `SMC_C_NEWYORK_OPENING_RANGE_V1` / `session_calendar_coverage`: No complete holiday, weekend, and DST calendar contract is frozen.

No local market-data storage was inventoried and no provider request was sent.
