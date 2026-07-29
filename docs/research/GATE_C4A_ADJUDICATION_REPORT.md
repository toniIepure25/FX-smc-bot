# Gate C.4-A Adjudication Report

Acceptance exact answers:

```json
{
  "effect_survived_removal_of_strongest_year": "diagnostic_only_no_registered_threshold",
  "every_preregistered_placebo_criterion_passed": true,
  "exact_boolean_producing_mixed": "confirmation conjunction failed because mean_event_markout_points > 0 was false; mixed fallback passed because mean_event_minus_control_points > 0 was true",
  "full_sample_effect": 11.189338697510573,
  "holm_correction_passed": true,
  "matched_control_effect_passed": true,
  "mde80_points": 14.061585121967383,
  "mde_preregistered_as_confirmation_threshold": false,
  "mde_used_as_decision_threshold": false,
  "mean_event_markout_points": -3.66885245901655,
  "mean_event_minus_control_points": 13.754508196721174,
  "non_overlap_sample_retained_direction": true,
  "other_family_result_assigned_to_acceptance": false,
  "primary_confidence_interval_passed": "diagnostic_only_not_mandatory",
  "primary_effect_passed": false,
  "primary_non_overlap_effect": 13.754508196721174,
  "replication_confidence_interval_preregistered": false,
  "replication_effect_passed": true,
  "secondary_sensitivity_accidentally_mandatory": false,
  "year_concentration_passed": "diagnostic_only_no_registered_threshold"
}
```

Decision trace:

```json
{
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "criteria": [
        {
          "comparison_operator": ">=",
          "criterion": "minimum_total_events",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 2440,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 40
        },
        {
          "comparison_operator": ">=",
          "criterion": "minimum_replication_events",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 996,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 10
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_event_primary_effect",
          "failure_reason": "positive_event_primary_effect failed",
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": -3.66885245901655,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1018",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_matched_control_difference",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 13.754508196721174,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1017",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "<=",
          "criterion": "holm_adjusted_p_value",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 0.021989005497251374,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1019",
          "source_hash": "",
          "threshold": 0.05
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_replication_effect",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 7.2751004016060214,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1021",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "==",
          "criterion": "placebo_not_reproduced",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": false,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/placebo_results.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1022",
          "source_hash": "",
          "threshold": false
        },
        {
          "comparison_operator": "not_used",
          "criterion": "mde80_effect_threshold",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 13.754508196721174,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/power_and_sensitivity.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: power diagnostic only",
          "source_hash": "",
          "threshold": 14.061585121967383
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "overlap_robustness",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": 13.754508196721174,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: not a confirmation threshold",
          "source_hash": "",
          "threshold": null
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "year_concentration",
          "failure_reason": null,
          "family": "liquidity_acceptance_fvg_continuation",
          "observed_value": {
            "2015": 33.86175710594296,
            "2016": 10.652230971128764,
            "2017": 1.4125615763544412,
            "2018": 11.959044368600555,
            "2019": -1.980000000000151
          },
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: no threshold registered",
          "source_hash": "",
          "threshold": null
        }
      ],
      "failed_mandatory_criteria": [
        "positive_event_primary_effect"
      ],
      "label": "Acceptance Continuation",
      "mandatory_pass": false,
      "recomputed_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision_matches_recomputed": true
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "criteria": [
        {
          "comparison_operator": ">=",
          "criterion": "minimum_total_events",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": 1389,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 40
        },
        {
          "comparison_operator": ">=",
          "criterion": "minimum_replication_events",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": 414,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 10
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_event_primary_effect",
          "failure_reason": "positive_event_primary_effect failed",
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": -8.406047516198633,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1018",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_matched_control_difference",
          "failure_reason": "positive_matched_control_difference failed",
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": -13.451403887688675,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1017",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "<=",
          "criterion": "holm_adjusted_p_value",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": 0.03798100949525238,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1019",
          "source_hash": "",
          "threshold": 0.05
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_replication_effect",
          "failure_reason": "positive_replication_effect failed",
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": -6.345410628019312,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1021",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "==",
          "criterion": "placebo_not_reproduced",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": false,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/placebo_results.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1022",
          "source_hash": "",
          "threshold": false
        },
        {
          "comparison_operator": "not_used",
          "criterion": "mde80_effect_threshold",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": -13.451403887688675,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/power_and_sensitivity.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: power diagnostic only",
          "source_hash": "",
          "threshold": 16.264893632834536
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "overlap_robustness",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": -13.451403887688675,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: not a confirmation threshold",
          "source_hash": "",
          "threshold": null
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "year_concentration",
          "failure_reason": null,
          "family": "liquidity_sweep_mss_fvg_reversal",
          "observed_value": {
            "2015": -27.493074792243444,
            "2016": -0.8486707566459359,
            "2017": 2.4738095238102407,
            "2018": 2.0159744408943427,
            "2019": -22.586387434554787
          },
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: no threshold registered",
          "source_hash": "",
          "threshold": null
        }
      ],
      "failed_mandatory_criteria": [
        "positive_event_primary_effect",
        "positive_matched_control_difference",
        "positive_replication_effect"
      ],
      "label": "Sweep Reversal",
      "mandatory_pass": false,
      "recomputed_decision": "NULL_SUPPORTED",
      "stored_c4_decision": "NULL_SUPPORTED",
      "stored_c4_decision_matches_recomputed": true
    },
    "opening_range_london": {
      "criteria": [
        {
          "comparison_operator": ">=",
          "criterion": "minimum_total_events",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 694,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 40
        },
        {
          "comparison_operator": ">=",
          "criterion": "minimum_replication_events",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 279,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 10
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_event_primary_effect",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 0.21181556195970366,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1018",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_matched_control_difference",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 15.15994236311225,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1017",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "<=",
          "criterion": "holm_adjusted_p_value",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 0.03748125937031484,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1019",
          "source_hash": "",
          "threshold": 0.05
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_replication_effect",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 4.727598566307897,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1021",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "==",
          "criterion": "placebo_not_reproduced",
          "failure_reason": "placebo_not_reproduced failed",
          "family": "opening_range_london",
          "observed_value": true,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/placebo_results.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1022",
          "source_hash": "",
          "threshold": false
        },
        {
          "comparison_operator": "not_used",
          "criterion": "mde80_effect_threshold",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 15.15994236311225,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/power_and_sensitivity.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: power diagnostic only",
          "source_hash": "",
          "threshold": 16.604405422991615
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "overlap_robustness",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": 15.15994236311225,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: not a confirmation threshold",
          "source_hash": "",
          "threshold": null
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "year_concentration",
          "failure_reason": null,
          "family": "opening_range_london",
          "observed_value": {
            "2015": 3.856060606061685,
            "2016": 15.583941605838314,
            "2017": 44.917808219178134,
            "2018": 4.687943262410954,
            "2019": 4.768115942028686
          },
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: no threshold registered",
          "source_hash": "",
          "threshold": null
        }
      ],
      "failed_mandatory_criteria": [
        "placebo_not_reproduced"
      ],
      "label": "London Opening Range",
      "mandatory_pass": false,
      "recomputed_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision_matches_recomputed": true
    },
    "opening_range_new_york": {
      "criteria": [
        {
          "comparison_operator": ">=",
          "criterion": "minimum_total_events",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": 800,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 40
        },
        {
          "comparison_operator": ">=",
          "criterion": "minimum_replication_events",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": 318,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
          "source_hash": "",
          "threshold": 10
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_event_primary_effect",
          "failure_reason": "positive_event_primary_effect failed",
          "family": "opening_range_new_york",
          "observed_value": -9.677499999999919,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1018",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_matched_control_difference",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": 0.0950000000001873,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1017",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "<=",
          "criterion": "holm_adjusted_p_value",
          "failure_reason": "holm_adjusted_p_value failed",
          "family": "opening_range_new_york",
          "observed_value": 0.9885057471264368,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/primary_estimands.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1019",
          "source_hash": "",
          "threshold": 0.05
        },
        {
          "comparison_operator": ">",
          "criterion": "positive_replication_effect",
          "failure_reason": "positive_replication_effect failed",
          "family": "opening_range_new_york",
          "observed_value": -9.327044025157035,
          "passed": false,
          "required": true,
          "source_artifact": "results/gate_c4/temporal_replication.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1021",
          "source_hash": "",
          "threshold": 0.0
        },
        {
          "comparison_operator": "==",
          "criterion": "placebo_not_reproduced",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": false,
          "passed": true,
          "required": true,
          "source_artifact": "results/gate_c4/placebo_results.json",
          "source_code_location": "src/fx_smc_bot/research/gate_c4_event_alpha.py:1022",
          "source_hash": "",
          "threshold": false
        },
        {
          "comparison_operator": "not_used",
          "criterion": "mde80_effect_threshold",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": 0.0950000000001873,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/power_and_sensitivity.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: power diagnostic only",
          "source_hash": "",
          "threshold": 19.60973061961117
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "overlap_robustness",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": 0.0950000000001873,
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: not a confirmation threshold",
          "source_hash": "",
          "threshold": null
        },
        {
          "comparison_operator": "diagnostic",
          "criterion": "year_concentration",
          "failure_reason": null,
          "family": "opening_range_new_york",
          "observed_value": {
            "2015": 11.618750000001299,
            "2016": 8.43749999999952,
            "2017": -1.0308641975311392,
            "2018": 0.32544378698254184,
            "2019": -20.275167785234807
          },
          "passed": true,
          "required": false,
          "source_artifact": "results/gate_c4/robustness_results.json",
          "source_code_location": "docs/research/GATE_C4_PREREGISTRATION.md: no threshold registered",
          "source_hash": "",
          "threshold": null
        }
      ],
      "failed_mandatory_criteria": [
        "positive_event_primary_effect",
        "holm_adjusted_p_value",
        "positive_replication_effect"
      ],
      "label": "New York Opening Range",
      "mandatory_pass": false,
      "recomputed_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision": "MIXED_EXPLORATORY_SIGNAL",
      "stored_c4_decision_matches_recomputed": true
    }
  }
}
```

Placebo mapping:

```json
{
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "aggregated_failure_rule": "fails confirmation if placebo_reproduces_primary_direction is true",
      "aggregated_passed": true,
      "applies_to_family": true,
      "family_label": "Acceptance Continuation",
      "placebo_reproduces_primary_direction": false,
      "placebo_types": {
        "direction_flip_mid_mean_points": {
          "confidence_interval": null,
          "observed_effect": -0.2961065573769135,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "random_matched_time_mean_points": {
          "confidence_interval": null,
          "observed_effect": -17.423360655737724,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "timestamp_shift_plus_one_day_mean_points": {
          "confidence_interval": null,
          "observed_effect": -0.4507111329082536,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        }
      },
      "primary_or_diagnostic": "required aggregated placebo criterion for placebo_reproduces_primary_direction; individual placebo effects are diagnostics"
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "aggregated_failure_rule": "fails confirmation if placebo_reproduces_primary_direction is true",
      "aggregated_passed": true,
      "applies_to_family": true,
      "family_label": "Sweep Reversal",
      "placebo_reproduces_primary_direction": false,
      "placebo_types": {
        "direction_flip_mid_mean_points": {
          "confidence_interval": null,
          "observed_effect": 4.507559395248264,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "random_matched_time_mean_points": {
          "confidence_interval": null,
          "observed_effect": 5.045356371490041,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "timestamp_shift_plus_one_day_mean_points": {
          "confidence_interval": null,
          "observed_effect": -5.969217238346368,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        }
      },
      "primary_or_diagnostic": "required aggregated placebo criterion for placebo_reproduces_primary_direction; individual placebo effects are diagnostics"
    },
    "opening_range_london": {
      "aggregated_failure_rule": "fails confirmation if placebo_reproduces_primary_direction is true",
      "aggregated_passed": false,
      "applies_to_family": true,
      "family_label": "London Opening Range",
      "placebo_reproduces_primary_direction": true,
      "placebo_types": {
        "direction_flip_mid_mean_points": {
          "confidence_interval": null,
          "observed_effect": -3.2896253602306307,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "random_matched_time_mean_points": {
          "confidence_interval": null,
          "observed_effect": -14.948126801152547,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "timestamp_shift_plus_one_day_mean_points": {
          "confidence_interval": null,
          "observed_effect": 0.52919708029206,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        }
      },
      "primary_or_diagnostic": "required aggregated placebo criterion for placebo_reproduces_primary_direction; individual placebo effects are diagnostics"
    },
    "opening_range_new_york": {
      "aggregated_failure_rule": "fails confirmation if placebo_reproduces_primary_direction is true",
      "aggregated_passed": true,
      "applies_to_family": true,
      "family_label": "New York Opening Range",
      "placebo_reproduces_primary_direction": false,
      "placebo_types": {
        "direction_flip_mid_mean_points": {
          "confidence_interval": null,
          "observed_effect": 6.585000000000196,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "random_matched_time_mean_points": {
          "confidence_interval": null,
          "observed_effect": -9.772500000000104,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        },
        "timestamp_shift_plus_one_day_mean_points": {
          "confidence_interval": null,
          "observed_effect": 6.984326018808448,
          "p_value": null,
          "pass_fail": "diagnostic_only"
        }
      },
      "primary_or_diagnostic": "required aggregated placebo criterion for placebo_reproduces_primary_direction; individual placebo effects are diagnostics"
    }
  },
  "london_or_not_assigned_to_acceptance": true,
  "status": "PASS"
}
```

Temporal replication:

```json
{
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "discovery_confidence_interval": null,
      "discovery_effect": 18.22368421052636,
      "discovery_event_count": 1444,
      "discovery_interval": [
        2015,
        2016,
        2017
      ],
      "event_definitions_identical": true,
      "matching_rules_identical": true,
      "no_discovery_events_leak_into_replication": true,
      "preregistered_replication_pass_status": true,
      "primary_effect_ci": [
        6.3252850111418315,
        21.790929169814817
      ],
      "primary_horizon_minutes": 120,
      "replication_confidence_interval": null,
      "replication_confidence_interval_preregistered": false,
      "replication_effect": 7.2751004016060214,
      "replication_event_count": 996,
      "replication_interval": [
        2018,
        2019
      ],
      "replication_uses_frozen_primary_sample": true,
      "same_direction_status": true
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "discovery_confidence_interval": null,
      "discovery_effect": -16.46871794871751,
      "discovery_event_count": 975,
      "discovery_interval": [
        2015,
        2016,
        2017
      ],
      "event_definitions_identical": true,
      "matching_rules_identical": true,
      "no_discovery_events_leak_into_replication": true,
      "preregistered_replication_pass_status": false,
      "primary_effect_ci": [
        -21.65365587176299,
        -4.74573832156042
      ],
      "primary_horizon_minutes": 60,
      "replication_confidence_interval": null,
      "replication_confidence_interval_preregistered": false,
      "replication_effect": -6.345410628019312,
      "replication_event_count": 414,
      "replication_interval": [
        2018,
        2019
      ],
      "replication_uses_frozen_primary_sample": true,
      "same_direction_status": false
    },
    "opening_range_london": {
      "discovery_confidence_interval": null,
      "discovery_effect": 22.173493975903614,
      "discovery_event_count": 415,
      "discovery_interval": [
        2015,
        2016,
        2017
      ],
      "event_definitions_identical": true,
      "matching_rules_identical": true,
      "no_discovery_events_leak_into_replication": true,
      "preregistered_replication_pass_status": true,
      "primary_effect_ci": [
        6.015287649989427,
        23.54029143475591
      ],
      "primary_horizon_minutes": 60,
      "replication_confidence_interval": null,
      "replication_confidence_interval_preregistered": false,
      "replication_effect": 4.727598566307897,
      "replication_event_count": 279,
      "replication_interval": [
        2018,
        2019
      ],
      "replication_uses_frozen_primary_sample": true,
      "same_direction_status": true
    },
    "opening_range_new_york": {
      "discovery_confidence_interval": null,
      "discovery_effect": 6.311203319502256,
      "discovery_event_count": 482,
      "discovery_interval": [
        2015,
        2016,
        2017
      ],
      "event_definitions_identical": true,
      "matching_rules_identical": true,
      "no_discovery_events_leak_into_replication": true,
      "preregistered_replication_pass_status": false,
      "primary_effect_ci": [
        -9.925967601652154,
        11.230362524851277
      ],
      "primary_horizon_minutes": 60,
      "replication_confidence_interval": null,
      "replication_confidence_interval_preregistered": false,
      "replication_effect": -9.327044025157035,
      "replication_event_count": 318,
      "replication_interval": [
        2018,
        2019
      ],
      "replication_uses_frozen_primary_sample": true,
      "same_direction_status": false
    }
  },
  "status": "PASS"
}
```

Overlap and concentration:

```json
{
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "actual_criterion_result": "diagnostic_only",
      "embargo_minutes": 120,
      "full_sample_effect": 11.189338697510573,
      "full_sample_is_secondary": true,
      "leave_one_year_out_effect_directions": {
        "2015": "positive",
        "2016": "positive",
        "2017": "positive",
        "2018": "positive",
        "2019": "positive"
      },
      "maximum_year_contribution_points": 33.86175710594296,
      "primary_non_overlap_effect": 13.754508196721174,
      "primary_sample_is_non_overlapping": true,
      "required_stability_criterion": "none preregistered",
      "strongest_year": 2015,
      "strongest_year_removed_mean_year_effect": 5.510959229020902
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "actual_criterion_result": "diagnostic_only",
      "embargo_minutes": 120,
      "full_sample_effect": -7.319052987598358,
      "full_sample_is_secondary": true,
      "leave_one_year_out_effect_directions": {
        "2015": "non_positive",
        "2016": "non_positive",
        "2017": "non_positive",
        "2018": "non_positive",
        "2019": "non_positive"
      },
      "maximum_year_contribution_points": 2.4738095238102407,
      "primary_non_overlap_effect": -13.451403887688675,
      "primary_sample_is_non_overlapping": true,
      "required_stability_criterion": "none preregistered",
      "strongest_year": 2017,
      "strongest_year_removed_mean_year_effect": -12.228039635637456
    },
    "opening_range_london": {
      "actual_criterion_result": "diagnostic_only",
      "embargo_minutes": 120,
      "full_sample_effect": 15.15994236311225,
      "full_sample_is_secondary": true,
      "leave_one_year_out_effect_directions": {
        "2015": "positive",
        "2016": "positive",
        "2017": "positive",
        "2018": "positive",
        "2019": "positive"
      },
      "maximum_year_contribution_points": 44.917808219178134,
      "primary_non_overlap_effect": 15.15994236311225,
      "primary_sample_is_non_overlapping": true,
      "required_stability_criterion": "none preregistered",
      "strongest_year": 2017,
      "strongest_year_removed_mean_year_effect": 7.2240153540849095
    },
    "opening_range_new_york": {
      "actual_criterion_result": "diagnostic_only",
      "embargo_minutes": 120,
      "full_sample_effect": 0.0950000000001873,
      "full_sample_is_secondary": true,
      "leave_one_year_out_effect_directions": {
        "2015": "non_positive",
        "2016": "non_positive",
        "2017": "positive",
        "2018": "non_positive",
        "2019": "positive"
      },
      "maximum_year_contribution_points": 11.618750000001299,
      "primary_non_overlap_effect": 0.0950000000001873,
      "primary_sample_is_non_overlapping": true,
      "required_stability_criterion": "none preregistered",
      "strongest_year": 2015,
      "strongest_year_removed_mean_year_effect": -3.135772048945971
    }
  },
  "overlap": {
    "by_family_non_overlap": {
      "liquidity_acceptance_fvg_continuation": 2440,
      "liquidity_sweep_mss_fvg_reversal": 1389,
      "opening_range_london": 694,
      "opening_range_new_york": 800
    },
    "non_overlap_primary_events": 5323,
    "overlapped_primary_events": 1922,
    "total_events": 7245
  },
  "status": "PASS"
}
```
