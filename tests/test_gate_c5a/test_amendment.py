from __future__ import annotations

import numpy as np
import pandas as pd

from fx_smc_bot.research.gate_c5a_amendment import (
    AMENDMENT_ID,
    BALANCE_SMD_THRESHOLD,
    COVARIATES,
    EXACT_KEYS,
    amended_decision_matrix,
    criterion_trace,
    handoff_amendment_payload,
    inference_protocol,
    matching_balance_audit,
    matching_protocol,
    placebo_protocol,
    smd,
)


def test_handoff_amendment_preserves_original_hypothesis() -> None:
    payload = handoff_amendment_payload()
    assert payload["amendment_id"] == AMENDMENT_ID
    assert payload["original_hypothesis_id"] == "C4B_USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_V1"
    assert payload["original_handoff_remains_immutable"] is True
    assert payload["validation_or_holdout_information_available_during_resolution"] is False
    assert payload["amendment_hash"]


def test_amended_decision_matrix_has_exact_eleven_mandatory_criteria() -> None:
    amendment = handoff_amendment_payload()
    matrix = amended_decision_matrix(amendment["amendment_hash"])
    assert matrix["decision_matrix_complete"] is True
    assert len(matrix["mandatory_criteria"]) == 11
    names = {row["criterion"] for row in matrix["mandatory_criteria"]}
    assert "plus_1_day_placebo_reproduces_relative_resilience" in names
    assert "mean_absolute_event_executable_markout" in names


def test_matching_protocol_freezes_exact_keys_and_no_fallback() -> None:
    protocol = matching_protocol()
    assert tuple(protocol["exact_keys"]) == EXACT_KEYS
    assert protocol["fallback_allowed"] is False
    assert protocol["exact_key_relaxations_required"] == 0
    assert protocol["replacement"] is True
    assert protocol["minimum_successfully_matched_events"] == 40


def test_smd_and_balance_threshold_are_covariate_wise() -> None:
    events = pd.DataFrame({covar: [1.0, 2.0, 3.0] for covar in COVARIATES})
    events["event_id"] = ["a", "b", "c"]
    matches = pd.DataFrame(
        {
            "event_id": ["a", "b", "c"],
            **{f"control_{covar}": [1.0, 2.0, 3.0] for covar in COVARIATES},
        }
    )
    audit = matching_balance_audit(events, matches)
    assert audit["balance_pass"] is True
    assert audit["max_abs_post_match_smd"] <= BALANCE_SMD_THRESHOLD
    assert smd(np.array([1.0, 1.0]), np.array([2.0, 2.0])) < 0


def test_inference_and_placebo_protocols_freeze_primary_rules() -> None:
    inference = inference_protocol()
    placebo = placebo_protocol()
    assert inference["primary_alpha"] == 0.05
    assert inference["holm_family_size"] == 1
    assert inference["mandatory_requirements"]["ci95_lower_bound_gt_0"] is True
    assert placebo["shift"] == "+24 hours UTC"
    assert placebo["reproduces_if_all"]["placebo_ci95_lower_bound_gt_0"] is True


def test_criterion_trace_requires_non_positive_absolute_event_markout() -> None:
    primary = {
        "mean_event_minus_control_points": 1.0,
        "mean_event_executable_markout_points": 0.1,
        "paired_permutation_p_value": 0.01,
        "cluster_bootstrap_ci95_mean_diff_points": [0.1, 2.0],
    }
    matching = {
        "successfully_matched_events": 40,
        "exact_key_relaxations": 0,
        "balance_pass": True,
    }
    placebo = {"placebo_reproduces_relative_resilience": False}
    trace = criterion_trace(primary, matching, placebo)
    assert trace["criteria"]["mean_absolute_event_executable_markout"] is False
    assert trace["all_pass"] is False
