# Gate C.5-A Amended Development Replay

Replay status: `PASS`

This replay uses only the frozen 2015-2019 development row-level artifacts and
development canonical data. It is a lineage-consistency check, not a
rule-selection step.

```json
{
  "all_eleven_criteria": {
    "all_pass": true,
    "criteria": {
      "artifact_integrity": true,
      "ci95_lower_bound": true,
      "every_post_match_abs_smd": true,
      "exact_key_relaxations": true,
      "holdout_integrity": true,
      "mean_absolute_event_executable_markout": true,
      "mean_event_minus_control_executable_markout": true,
      "paired_permutation_p_value": true,
      "plus_1_day_placebo_does_not_reproduce": true,
      "successfully_matched_primary_non_overlap_events": true,
      "validation_data_quality": true
    }
  },
  "development_only": true,
  "eligible_primary_events": 2440,
  "exact_key_relaxations": 0,
  "final_decision_if_failed": "BLOCKED_BY_AMENDED_DEVELOPMENT_REPLAY",
  "matching": {
    "balance_pass": true,
    "candidate_count_max": 1808,
    "candidate_count_median": 945.0,
    "candidate_count_min": 394,
    "exact_key_relaxations": 0,
    "exact_keys": [
      "year",
      "month",
      "session",
      "direction"
    ],
    "matching_seed": 4242,
    "max_abs_post_match_smd": 0.09501540210119847,
    "post_match_smd": {
      "atr": 0.05435215708934559,
      "pre_event_trend": -0.002653131219811562,
      "pre_event_volatility": 0.09501540210119847,
      "range_position": -0.001199291556264466,
      "spread": 0.04721272971392561
    },
    "pre_match_smd": {
      "atr": 0.05435215708934559,
      "pre_event_trend": -0.002653131219811562,
      "pre_event_volatility": 0.09501540210119847,
      "range_position": -0.001199291556264466,
      "spread": 0.04721272971392561
    },
    "primary_eligible_events": 2440,
    "replacement": true,
    "successfully_matched_events": 2440,
    "unmatched_event_records": [],
    "unmatched_events": 0
  },
  "placebo": {
    "eligible_shifted_placebo_events": 1436,
    "estimand": {
      "cluster_bootstrap_ci95_mean_diff_points": [
        0.0,
        0.4205714285714229
      ],
      "event_outperforms_control_probability": 0.001392757660167131,
      "holm_adjusted_p_value": 0.5162418790604698,
      "mean_control_executable_markout_points": -0.5041782729804634,
      "mean_event_executable_markout_points": -0.24791086350971447,
      "mean_event_minus_control_points": 0.2562674094707486,
      "median_event_minus_control_points": 0.0,
      "n": 1436,
      "paired_permutation_p_value": 0.5162418790604698,
      "positive_control_probability": 0.4986072423398329,
      "positive_event_probability": 0.49930362116991645,
      "standardized_paired_effect": 0.03602451177417548,
      "trimmed_mean_event_minus_control_points": 0.0
    },
    "matching": {
      "balance_pass": true,
      "candidate_count_max": 1808,
      "candidate_count_median": 985.5,
      "candidate_count_min": 394,
      "exact_key_relaxations": 0,
      "exact_keys": [
        "year",
        "month",
        "session",
        "direction"
      ],
      "matching_seed": 4242,
      "max_abs_post_match_smd": 0.00016573201511214857,
      "post_match_smd": {
        "atr": -0.0001353321937767702,
        "pre_event_trend": -4.3773552993655413e-05,
        "pre_event_volatility": 7.010440390702717e-05,
        "range_position": 0.00012617634763846308,
        "spread": 0.00016573201511214857
      },
      "pre_match_smd": {
        "atr": -0.0001353321937767702,
        "pre_event_trend": -4.3773552993655413e-05,
        "pre_event_volatility": 7.010440390702717e-05,
        "range_position": 0.00012617634763846308,
        "spread": 0.00016573201511214857
      },
      "primary_eligible_events": 1436,
      "replacement": true,
      "successfully_matched_events": 1436,
      "unmatched_event_records": [],
      "unmatched_events": 0
    },
    "placebo_reproduces_relative_resilience": false,
    "placebo_type": "+1-day shifted pseudo-event relative-resilience placebo",
    "successfully_matched_placebo_events": 1436
  },
  "primary_estimand": {
    "cluster_bootstrap_ci95_mean_diff_points": [
      6.277491118674749,
      21.844720075312043
    ],
    "event_outperforms_control_probability": 0.5245901639344263,
    "holm_adjusted_p_value": 0.006496751624187906,
    "mean_control_executable_markout_points": -17.33688524590164,
    "mean_event_executable_markout_points": -3.66885245901655,
    "mean_event_minus_control_points": 13.668032786885094,
    "median_event_minus_control_points": 9.99999999999801,
    "n": 2440,
    "paired_permutation_p_value": 0.006496751624187906,
    "positive_control_probability": 0.43278688524590164,
    "positive_event_probability": 0.46352459016393444,
    "standardized_paired_effect": 0.05341486685670989,
    "trimmed_mean_event_minus_control_points": 12.717725409836014
  },
  "status": "PASS",
  "successfully_matched_events": 2440,
  "unmatched_events": 0,
  "validation_or_holdout_accessed": false
}
```
