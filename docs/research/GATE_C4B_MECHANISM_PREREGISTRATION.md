# Gate C.4-B Mechanism Preregistration

Status: PREREGISTERED BEFORE NEW MECHANISM DIAGNOSTICS

Mechanism preregistration hash: `7d53f169ef3df460e04cc9d0d883f05c91a423b999dad4862e0baeef59d699c9`

Repository SHA at preregistration: `d9a9e513e6384a625b2c26a49e1a1d6e4e647a90`

## Scientific Status

This gate is outcome-informed hypothesis generation. It does not reinterpret,
overwrite, or promote the failed Gate C.4 Acceptance directional-alpha result.
No `CONFIRMED_ALPHA` decision is permitted.

## Source Artifacts

```json
{
  "c4_event_configuration_hash": "736428ec62cfb04efa5b5de6dc759f50c97b71bfa585f57c6b03a451c169b8f1",
  "c4_event_table_manifest_hash": "2e83eb47603c4ec1ae97a4cf040a92f2b8977f37f0a031c61dc500b6c2c37977",
  "c4_preregistration_hash": "508ad3540b0f8f82b710775a50781f3f936695c2978284edc13942658624a349",
  "c4a_research_stop_record_sha256": "b5fb43fd267a031dfbc115611c9b50e1107288b5c1f47bc5dc4c5b14df9c4c9f",
  "event_table_parquet_sha256": "a9f6cd1627f4ae13f738888f6f5fb5d82b02c3b01184c6e4748f5b596ac9d62c",
  "matched_control_parquet_sha256": "e5a7a97dbc0abce9ae8d3d8cbc81eb7648ece8d44ca931c86473fb5ec9f347ef"
}
```

## Allowed Mechanism Classes

```json
[
  "COST_LIMITED_CONTINUATION",
  "RELATIVE_RESILIENCE",
  "CONTRARIAN_ACCEPTANCE",
  "LATE_CONFIRMATION_DECAY",
  "NO_ACTIONABLE_MECHANISM"
]
```

## Allowed Diagnostic Horizons

`15`, `30`, `60`, `120`, and `240` minutes. These are diagnostics only and may
not be searched for the best effect.

## Candidate Selection Tree

```json
[
  {
    "class": "COST_LIMITED_CONTINUATION",
    "rank": 1,
    "rule": "select only if all cost_limited requirements pass"
  },
  {
    "class": "RELATIVE_RESILIENCE",
    "rank": 2,
    "rule": "select only if cost_limited fails and all relative_resilience requirements pass"
  },
  {
    "class": "CONTRARIAN_ACCEPTANCE",
    "rank": 3,
    "rule": "select only if prior classes fail and all contrarian requirements pass"
  },
  {
    "class": "LATE_CONFIRMATION_DECAY",
    "rank": 4,
    "rule": "select only if prior classes fail and timing_decay requirements pass"
  },
  {
    "class": "NO_ACTIONABLE_MECHANISM",
    "rank": 5,
    "rule": "select if no mechanism class passes"
  }
]
```

## Minimum Stability Requirements

```json
{
  "contrarian": [
    "flipped_executable_positive",
    "flipped_discovery_positive",
    "flipped_replication_positive",
    "non_overlap_positive",
    "not_dominated_by_single_year",
    "latency_supports_reversal"
  ],
  "cost_limited": [
    "primary_mid_return_positive",
    "discovery_mid_return_positive",
    "replication_mid_return_positive",
    "spread_drag_explains_executable_failure",
    "no_spread_threshold_required"
  ],
  "relative_resilience": [
    "absolute_event_markout_non_positive",
    "matched_control_difference_positive",
    "discovery_difference_positive",
    "replication_difference_positive",
    "non_overlap_difference_positive",
    "placebo_not_reproduced",
    "not_dominated_by_single_year"
  ],
  "timing_decay": [
    "pre_entry_move_fraction_material",
    "post_entry_continuation_non_positive",
    "discovery_replication_same_qualitative_decay",
    "no_retroactive_entry_rule"
  ]
}
```

## Forbidden Analyses

```json
[
  "validation_or_holdout_access",
  "threshold_search",
  "horizon_search_for_best_effect",
  "subgroup_selection",
  "full_strategy_backtest",
  "equity_curve",
  "sharpe",
  "sortino",
  "profit_factor",
  "drawdown",
  "retroactive_promotion_of_c4_acceptance"
]
```

## Split Rule

Validation and holdout market data must remain unopened in Gate C.4-B. Any
candidate frozen here is exploratory, development-informed, and requires a new
untouched validation handoff before validation access.
