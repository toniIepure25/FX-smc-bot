# Gate C.5-A Execution Protocol

Protocol hash: `25455b31140d47b559c9fb5bd2d5d6c195742ad536dd7132dfb325026562be30`

This protocol freezes the amended C5 validation execution before any validation
access. Scientific code and decision rules are immutable after validation
unblinding.

```json
{
  "amendment_hash": "1d1302fcc01fec3d0be00875026854e8b9e47eee38dd74fa654e824fdab44830",
  "amendment_id": "C5A_C4B_USDJPY_RELATIVE_RESILIENCE_HANDOFF_AMENDMENT_V1",
  "amendment_integrity_hashes": {
    "amended_decision_matrix_hash": "86f8bcbcd510ba457ef36cd1fff36efe7299d77f662a2e16ffa0bc30fe51eb87",
    "amendment_id": "C5A_C4B_USDJPY_RELATIVE_RESILIENCE_HANDOFF_AMENDMENT_V1",
    "handoff_amendment_hash": "1d1302fcc01fec3d0be00875026854e8b9e47eee38dd74fa654e824fdab44830",
    "inference_protocol_hash": "2b0f1651dabdf00028238ef3708655cf2034c0f916a5ec42dc908e2aaa9db5c4",
    "matching_protocol_hash": "6a58ebb23b02729b6ee08119c0d0de5449ec3e441b8376dbf0ed97e840f86114",
    "placebo_protocol_hash": "2d116dd997ee112c44af8bdf6cc1eb3beaebf2d5c83047b0fecc60548559a81c",
    "status": "PASS",
    "validation_or_holdout_accessed": false
  },
  "analysis_code_hashes": {
    "acceptance_config": "f668b91ab7f275b438b4079d160d81e755e514e7c7d0e4571626a19ff6c9c875",
    "acceptance_detector": "831aada49cc661a2a30a2dce030b6e9d4f2fbc01af0b0813d00aae47c4b3efb0",
    "c4_event_alpha_module": "5f183c7b43e7ddae073b97860d39ad952cbd7af2d672520deb632b252d8d1644",
    "c5a_amendment_module": "074044a67c78c2708626679b72cf195b50e43e4916afed4c2988612bcaa94b55",
    "runner": "73c6f3caa2b515765ed135b9c2e6b192db6b6d0bf6f210a47948bfed1f5cd52e"
  },
  "bootstrap_seed": 4242,
  "configuration_file_hash": "f668b91ab7f275b438b4079d160d81e755e514e7c7d0e4571626a19ff6c9c875",
  "created_at_utc": "2026-07-23T20:08:10.100803+00:00",
  "detector_hash": "831aada49cc661a2a30a2dce030b6e9d4f2fbc01af0b0813d00aae47c4b3efb0",
  "development_replay_hash": "04e7babfa8a5f29643ea1e6e91c2ad0f0510edab919c6f5fb8f39b42b52c0c9c",
  "development_replay_status": "PASS",
  "event_configuration_hash": "736428ec62cfb04efa5b5de6dc759f50c97b71bfa585f57c6b03a451c169b8f1",
  "event_family": "Acceptance Continuation",
  "event_schema": [
    "event_id",
    "pair",
    "family",
    "direction",
    "confirmation_timestamp",
    "earliest_entry_timestamp",
    "session",
    "source_level",
    "pre-event covariates",
    "year",
    "month",
    "configuration_hash",
    "hypothesis_hash"
  ],
  "execution_protocol_hash": "25455b31140d47b559c9fb5bd2d5d6c195742ad536dd7132dfb325026562be30",
  "gate": "C.5-A",
  "hypothesis_hash": "e8b726734a3b5118709edc7642caa1d4e10bad2509aa9fd0949a0cca2b05290d",
  "hypothesis_id": "C4B_USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_V1",
  "inference_protocol": {
    "bootstrap_cluster": "UTC trading day",
    "confidence_level": 0.95,
    "day_cluster_bootstrap_iterations": 1000,
    "holm_adjusted_p_value": "raw primary p-value",
    "holm_family_size": 1,
    "mandatory_requirements": {
      "ci95_lower_bound_gt_0": true,
      "event_minus_control_point_estimate_gt_0": true,
      "paired_permutation_p_value_lte_0_05": true
    },
    "paired_permutation_iterations": 2000,
    "primary_alpha": 0.05
  },
  "mandatory_criteria": [
    {
      "comparison_operator": "equals",
      "criterion": "artifact_integrity",
      "criterion_number": 1,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    },
    {
      "comparison_operator": "equals",
      "criterion": "validation_data_quality",
      "criterion_number": 2,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    },
    {
      "comparison_operator": ">=",
      "criterion": "successfully_matched_primary_non_overlap_events",
      "criterion_number": 3,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 40
    },
    {
      "comparison_operator": "equals",
      "criterion": "exact_key_relaxations",
      "criterion_number": 4,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "every_post_match_abs_smd",
      "criterion_number": 5,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0.1
    },
    {
      "comparison_operator": ">",
      "criterion": "mean_event_minus_control_executable_markout",
      "criterion_number": 6,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "paired_permutation_p_value",
      "criterion_number": 7,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0.05
    },
    {
      "comparison_operator": ">",
      "criterion": "ci95_lower_bound",
      "criterion_number": 8,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "mean_absolute_event_executable_markout",
      "criterion_number": 9,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "equals",
      "criterion": "plus_1_day_placebo_reproduces_relative_resilience",
      "criterion_number": 10,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": false
    },
    {
      "comparison_operator": "equals",
      "criterion": "holdout_integrity",
      "criterion_number": 11,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    }
  ],
  "matching_implementation_hash": "074044a67c78c2708626679b72cf195b50e43e4916afed4c2988612bcaa94b55",
  "matching_protocol": {
    "covariates": [
      "spread",
      "atr",
      "pre_event_volatility",
      "pre_event_trend",
      "range_position"
    ],
    "embargo_minutes": 120,
    "exact_key_relaxations_required": 0,
    "exact_keys": [
      "year",
      "month",
      "session",
      "direction"
    ],
    "fallback_allowed": false,
    "matching_coverage_threshold": "diagnostic_only",
    "matching_type": "1:1 nearest-neighbour matching",
    "minimum_event_count_applies_after": [
      "primary non-overlap filtering",
      "complete 120-minute outcome coverage",
      "successful exact-key matching"
    ],
    "minimum_successfully_matched_events": 40,
    "random_seed": 4242,
    "replacement": true,
    "unmatched_event_policy": "retained in event manifest, reported explicitly, excluded from paired primary estimand"
  },
  "no_adaptation_policy": true,
  "outcome_implementation_hash": "5f183c7b43e7ddae073b97860d39ad952cbd7af2d672520deb632b252d8d1644",
  "pair": "USDJPY",
  "permutation_seed": 4242,
  "placebo_implementation_hash": "074044a67c78c2708626679b72cf195b50e43e4916afed4c2988612bcaa94b55",
  "placebo_protocol": {
    "apply_same_primary_non_overlap_policy": true,
    "construct_controls_with_same_exact_matcher": true,
    "exclude_if_real_acceptance_event_inside_embargo_minutes": 120,
    "mandatory_criterion": "placebo_reproduces_relative_resilience = false",
    "primary_placebo": "+1-day shifted pseudo-event relative-resilience placebo",
    "reproduces_if_all": {
      "placebo_ci95_lower_bound_gt_0": true,
      "placebo_differential_gt_0": true,
      "placebo_paired_permutation_p_lte_0_05": true
    },
    "require_complete_next_bar_entry_and_120m_outcome": true,
    "require_shift_inside_interval": true,
    "retain_direction": true,
    "shift": "+24 hours UTC"
  },
  "post_unblinding_failure_policy": "If a scientific-code defect appears after validation unblinding, stop with BLOCKED_BY_POST_UNBLINDING_EXECUTION_FAILURE; do not patch and continue.",
  "primary_horizon_minutes": 120,
  "primary_sample": "primary non-overlap sample",
  "validation_period": "2020-01-01 through 2022-12-31"
}
```
