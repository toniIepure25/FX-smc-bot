# Gate C.4 Final Decision Memo

Final decision: `USDJPY_EVENT_ALPHA_MIXED_EXPLORATORY_ONLY`

## Family Decisions
```json
{
  "liquidity_acceptance_fvg_continuation": {
    "decision": "MIXED_EXPLORATORY_SIGNAL",
    "holm_adjusted_p_value": 0.021989005497251374,
    "mean_event_minus_control_points": 13.754508196721174,
    "n_non_overlap_events": 2440,
    "placebo_reproduces_primary_direction": false,
    "replication_events": 996,
    "replication_mean_event_minus_control_points": 7.2751004016060214
  },
  "liquidity_sweep_mss_fvg_reversal": {
    "decision": "NULL_SUPPORTED",
    "holm_adjusted_p_value": 0.03798100949525238,
    "mean_event_minus_control_points": -13.451403887688675,
    "n_non_overlap_events": 1389,
    "placebo_reproduces_primary_direction": false,
    "replication_events": 414,
    "replication_mean_event_minus_control_points": -6.345410628019312
  },
  "opening_range_london": {
    "decision": "MIXED_EXPLORATORY_SIGNAL",
    "holm_adjusted_p_value": 0.03748125937031484,
    "mean_event_minus_control_points": 15.15994236311225,
    "n_non_overlap_events": 694,
    "placebo_reproduces_primary_direction": true,
    "replication_events": 279,
    "replication_mean_event_minus_control_points": 4.727598566307897
  },
  "opening_range_new_york": {
    "decision": "MIXED_EXPLORATORY_SIGNAL",
    "holm_adjusted_p_value": 0.9885057471264368,
    "mean_event_minus_control_points": 0.0950000000001873,
    "n_non_overlap_events": 800,
    "placebo_reproduces_primary_direction": false,
    "replication_events": 318,
    "replication_mean_event_minus_control_points": -9.327044025157035
  }
}
```

Validation and holdout integrity: no validation or holdout years were loaded,
counted, analyzed, or reported. Gate C.4 remains development-only.
