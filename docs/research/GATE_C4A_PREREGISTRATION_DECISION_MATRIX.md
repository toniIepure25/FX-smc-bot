# Gate C.4-A Preregistration Decision Matrix

Preregistration hash: `508ad3540b0f8f82b710775a50781f3f936695c2978284edc13942658624a349`

Mandatory confirmation criteria:

```json
[
  "minimum_total_events",
  "minimum_replication_events",
  "positive_event_primary_effect",
  "positive_matched_control_difference",
  "holm_adjusted_p_value",
  "positive_replication_effect",
  "placebo_not_reproduced"
]
```

Diagnostic or secondary items:

```json
[
  "confidence_interval",
  "positive_forward_return_probability",
  "power_mde80",
  "overlap_robustness",
  "year_concentration",
  "balance"
]
```

Family matrix:

```json
{
  "liquidity_acceptance_fvg_continuation": {
    "balance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "Matched-control balance is audited; no numeric SMD pass threshold was registered."
    },
    "confidence_interval_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "day-cluster bootstrap confidence intervals were registered for inference, not as a confirmation threshold"
    },
    "effect_direction_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive event and matched-control primary effect"
    },
    "effect_size_criterion": {
      "type": "not_preregistered_as_threshold",
      "verbatim": "No numeric effect-size threshold beyond positivity was registered."
    },
    "final_boolean_decision_rule": {
      "type": "required_confirmation_criterion",
      "verbatim": "adequate event count, positive event and matched-control primary effect, Holm p<=0.05, positive replication effect, and placebo checks not reproducing the primary effect"
    },
    "matched_control_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive ... matched-control primary effect"
    },
    "minimum_event_count": {
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "minimum_independent_episode_count": {
      "source": "implemented as n_events on non-overlap primary sample",
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "missing_artifact_policy": {
      "type": "required_infrastructure",
      "verbatim": "Missing artifacts block reproducibility rather than fail an alpha criterion."
    },
    "multiplicity_adjusted_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "Holm p<=0.05"
    },
    "overlap_robustness_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "Primary sample is non-overlap; robustness reports full/non-overlap comparisons."
    },
    "placebo_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "placebo checks not reproducing the primary effect"
    },
    "positive_probability_criterion": {
      "type": "descriptive_result",
      "verbatim": "No positive-probability threshold was registered."
    },
    "primary_estimand": "mean executable markout points and event-minus-matched-control points",
    "primary_horizon_minutes": 120,
    "primary_hypothesis": "direction-normalized executable primary forward markout is positive and exceeds matched controls",
    "primary_sample": "non-overlapping primary events",
    "raw_significance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "paired permutation p-values are computed before multiplicity correction"
    },
    "temporal_replication_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive replication effect"
    },
    "year_concentration_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "No year-concentration threshold was registered."
    }
  },
  "liquidity_sweep_mss_fvg_reversal": {
    "balance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "Matched-control balance is audited; no numeric SMD pass threshold was registered."
    },
    "confidence_interval_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "day-cluster bootstrap confidence intervals were registered for inference, not as a confirmation threshold"
    },
    "effect_direction_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive event and matched-control primary effect"
    },
    "effect_size_criterion": {
      "type": "not_preregistered_as_threshold",
      "verbatim": "No numeric effect-size threshold beyond positivity was registered."
    },
    "final_boolean_decision_rule": {
      "type": "required_confirmation_criterion",
      "verbatim": "adequate event count, positive event and matched-control primary effect, Holm p<=0.05, positive replication effect, and placebo checks not reproducing the primary effect"
    },
    "matched_control_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive ... matched-control primary effect"
    },
    "minimum_event_count": {
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "minimum_independent_episode_count": {
      "source": "implemented as n_events on non-overlap primary sample",
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "missing_artifact_policy": {
      "type": "required_infrastructure",
      "verbatim": "Missing artifacts block reproducibility rather than fail an alpha criterion."
    },
    "multiplicity_adjusted_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "Holm p<=0.05"
    },
    "overlap_robustness_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "Primary sample is non-overlap; robustness reports full/non-overlap comparisons."
    },
    "placebo_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "placebo checks not reproducing the primary effect"
    },
    "positive_probability_criterion": {
      "type": "descriptive_result",
      "verbatim": "No positive-probability threshold was registered."
    },
    "primary_estimand": "mean executable markout points and event-minus-matched-control points",
    "primary_horizon_minutes": 60,
    "primary_hypothesis": "direction-normalized executable primary forward markout is positive and exceeds matched controls",
    "primary_sample": "non-overlapping primary events",
    "raw_significance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "paired permutation p-values are computed before multiplicity correction"
    },
    "temporal_replication_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive replication effect"
    },
    "year_concentration_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "No year-concentration threshold was registered."
    }
  },
  "opening_range_london": {
    "balance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "Matched-control balance is audited; no numeric SMD pass threshold was registered."
    },
    "confidence_interval_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "day-cluster bootstrap confidence intervals were registered for inference, not as a confirmation threshold"
    },
    "effect_direction_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive event and matched-control primary effect"
    },
    "effect_size_criterion": {
      "type": "not_preregistered_as_threshold",
      "verbatim": "No numeric effect-size threshold beyond positivity was registered."
    },
    "final_boolean_decision_rule": {
      "type": "required_confirmation_criterion",
      "verbatim": "adequate event count, positive event and matched-control primary effect, Holm p<=0.05, positive replication effect, and placebo checks not reproducing the primary effect"
    },
    "matched_control_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive ... matched-control primary effect"
    },
    "minimum_event_count": {
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "minimum_independent_episode_count": {
      "source": "implemented as n_events on non-overlap primary sample",
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "missing_artifact_policy": {
      "type": "required_infrastructure",
      "verbatim": "Missing artifacts block reproducibility rather than fail an alpha criterion."
    },
    "multiplicity_adjusted_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "Holm p<=0.05"
    },
    "overlap_robustness_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "Primary sample is non-overlap; robustness reports full/non-overlap comparisons."
    },
    "placebo_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "placebo checks not reproducing the primary effect"
    },
    "positive_probability_criterion": {
      "type": "descriptive_result",
      "verbatim": "No positive-probability threshold was registered."
    },
    "primary_estimand": "mean executable markout points and event-minus-matched-control points",
    "primary_horizon_minutes": 60,
    "primary_hypothesis": "direction-normalized executable primary forward markout is positive and exceeds matched controls",
    "primary_sample": "non-overlapping primary events",
    "raw_significance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "paired permutation p-values are computed before multiplicity correction"
    },
    "temporal_replication_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive replication effect"
    },
    "year_concentration_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "No year-concentration threshold was registered."
    }
  },
  "opening_range_new_york": {
    "balance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "Matched-control balance is audited; no numeric SMD pass threshold was registered."
    },
    "confidence_interval_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "day-cluster bootstrap confidence intervals were registered for inference, not as a confirmation threshold"
    },
    "effect_direction_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive event and matched-control primary effect"
    },
    "effect_size_criterion": {
      "type": "not_preregistered_as_threshold",
      "verbatim": "No numeric effect-size threshold beyond positivity was registered."
    },
    "final_boolean_decision_rule": {
      "type": "required_confirmation_criterion",
      "verbatim": "adequate event count, positive event and matched-control primary effect, Holm p<=0.05, positive replication effect, and placebo checks not reproducing the primary effect"
    },
    "matched_control_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive ... matched-control primary effect"
    },
    "minimum_event_count": {
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "minimum_independent_episode_count": {
      "source": "implemented as n_events on non-overlap primary sample",
      "threshold": 40,
      "type": "required_confirmation_criterion"
    },
    "missing_artifact_policy": {
      "type": "required_infrastructure",
      "verbatim": "Missing artifacts block reproducibility rather than fail an alpha criterion."
    },
    "multiplicity_adjusted_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "Holm p<=0.05"
    },
    "overlap_robustness_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "Primary sample is non-overlap; robustness reports full/non-overlap comparisons."
    },
    "placebo_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "placebo checks not reproducing the primary effect"
    },
    "positive_probability_criterion": {
      "type": "descriptive_result",
      "verbatim": "No positive-probability threshold was registered."
    },
    "primary_estimand": "mean executable markout points and event-minus-matched-control points",
    "primary_horizon_minutes": 60,
    "primary_hypothesis": "direction-normalized executable primary forward markout is positive and exceeds matched controls",
    "primary_sample": "non-overlapping primary events",
    "raw_significance_criterion": {
      "type": "supporting_diagnostic",
      "verbatim": "paired permutation p-values are computed before multiplicity correction"
    },
    "temporal_replication_criterion": {
      "type": "required_confirmation_criterion",
      "verbatim": "positive replication effect"
    },
    "year_concentration_criterion": {
      "type": "secondary_sensitivity",
      "verbatim": "No year-concentration threshold was registered."
    }
  }
}
```
