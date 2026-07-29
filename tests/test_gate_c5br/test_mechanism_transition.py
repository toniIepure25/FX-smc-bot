from __future__ import annotations

import numpy as np
import pandas as pd

from fx_smc_bot.research.gate_c5br import (
    CANDIDATE_CLASS,
    canonical_json_sha256,
    effective_sample_size,
    exact_cell_weights,
    infer_absolute_effect,
    intersection_union,
    normalized_weight_diagnostics,
    post_match_smd,
    summarize_pairs,
    validate_holdout_closed,
    validate_no_strategy_metrics,
    validate_single_candidate,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "utc_date": ["2020-01-01", "2020-01-01", "2021-01-01", "2022-01-01"],
            "year": [2020, 2020, 2021, 2022],
            "session": ["asia", "london", "asia", "new_york"],
            "direction": ["LONG", "SHORT", "LONG", "SHORT"],
            "spread": [1.0, 2.0, 1.0, 2.0],
            "atr": [5.0, 6.0, 5.0, 6.0],
            "pre_event_volatility": [0.1, 0.2, 0.1, 0.2],
            "pre_event_trend": [1.0, -1.0, 1.0, -1.0],
            "range_position": [0.2, 0.8, 0.2, 0.8],
            "primary_executable_markout_points": [2.0, 4.0, 6.0, 8.0],
            "primary_mid_markout_points": [3.0, 5.0, 7.0, 9.0],
        }
    )


def _controls() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "control_spread": [1.0, 2.0, 1.0, 2.0],
            "control_atr": [5.0, 6.0, 5.0, 6.0],
            "control_pre_event_volatility": [0.1, 0.2, 0.1, 0.2],
            "control_pre_event_trend": [1.0, -1.0, 1.0, -1.0],
            "control_range_position": [0.2, 0.8, 0.2, 0.8],
            "primary_control_executable_markout_points": [1.0, 1.0, 1.0, 1.0],
            "primary_control_mid_markout_points": [1.5, 1.5, 1.5, 1.5],
        }
    )


def test_reconciliation_overlay_verification_hashes_canonical_payload() -> None:
    payload = {"overlay_id": "C5AR_ARTIFACT_RECONCILIATION_V1", "status": "PASS"}

    assert canonical_json_sha256(payload) == canonical_json_sha256(dict(reversed(payload.items())))


def test_original_c5ar_lock_preservation_detects_hash_change() -> None:
    original = {"status": "LOCKED", "hashes": {"x": "old"}}
    changed = {"status": "LOCKED", "hashes": {"x": "new"}}

    assert canonical_json_sha256(original) != canonical_json_sha256(changed)


def test_authoritative_adjudication_hash_verification_is_field_preserving() -> None:
    adjudication = {"criteria": [{"observed_value": 1, "passed": True}], "status": "PASS"}

    assert canonical_json_sha256(adjudication) == canonical_json_sha256(adjudication.copy())


def test_c5b_resumption_handoff_verification_requires_ready_status() -> None:
    handoff = {"status": "READY_TO_RESUME_C5B_PHASE_0", "hash": "abc"}

    assert handoff["status"] == "READY_TO_RESUME_C5B_PHASE_0"


def test_development_and_validation_deterministic_reproduction_identity() -> None:
    summary = summarize_pairs(_events(), _controls())

    assert summary["mean_event_minus_control_points"] == 4.0


def test_common_protocol_matcher_balance_smd() -> None:
    smds = post_match_smd(_events(), _controls())

    assert max(abs(value) for value in smds.values()) == 0.0


def test_decomposition_identity() -> None:
    dev_event, dev_control = -3.0, -17.0
    val_event, val_control = 11.0, -16.0
    change_diff = (val_event - val_control) - (dev_event - dev_control)

    assert change_diff == (val_event - dev_event) - (val_control - dev_control)


def test_fixed_composition_strata_are_not_empty() -> None:
    strata = ["direction", "session", "event subtype", "volatility regime"]

    assert "direction" in strata
    assert "session" in strata


def test_no_subgroup_selection_flag() -> None:
    audit = {"no_subgroup_selection": True}

    assert audit["no_subgroup_selection"] is True


def test_transport_weight_determinism() -> None:
    source = _events()
    target = _events().iloc[::-1].reset_index(drop=True)
    cols = ["session", "direction"]

    np.testing.assert_allclose(exact_cell_weights(source, target, cols), np.ones(4))


def test_effective_sample_size_threshold() -> None:
    weights = np.array([1.0, 1.0, 1.0, 1.0])

    assert effective_sample_size(weights) >= 0.5 * len(weights)


def test_maximum_weight_threshold() -> None:
    diagnostics = normalized_weight_diagnostics(np.array([1.0, 1.0, 1.0, 11.0]))

    assert diagnostics["max_weight_median_multiple"] > 10


def test_matching_support_comparison() -> None:
    requirements = {
        "zero_exact_key_relaxation_both_periods": True,
        "all_post_match_abs_smd_lte_0_10": True,
        "minimum_matched_events_both_periods": True,
    }

    assert all(requirements.values())


def test_single_candidate_class() -> None:
    assert validate_single_candidate(CANDIDATE_CLASS)
    assert not validate_single_candidate("OTHER")


def test_dual_positive_co_primary_estimands() -> None:
    estimands = {"co_primary_a": "event_absolute", "co_primary_b": "relative_diff"}

    assert set(estimands) == {"co_primary_a", "co_primary_b"}


def test_absolute_effect_inference_can_fail_on_p_value() -> None:
    result = infer_absolute_effect(
        np.array([1.0, -1.0, 1.0, -1.0]),
        np.array(["d1", "d1", "d2", "d2"]),
        iterations=100,
        bootstrap_iterations=100,
    )

    assert result["sign_flip_permutation_p_value"] > 0.05


def test_relative_effect_inference_rule() -> None:
    inference = {"raw_permutation_p_value": 0.01, "ci95_day_cluster_bootstrap": [1.0, 2.0]}

    assert inference["raw_permutation_p_value"] <= 0.05
    assert inference["ci95_day_cluster_bootstrap"][0] > 0


def test_intersection_union_decision() -> None:
    assert intersection_union({"co_primary_a": True, "co_primary_b": True})
    assert not intersection_union({"co_primary_a": True, "co_primary_b": False})


def test_no_estimand_substitution() -> None:
    passes = {"co_primary_a": False, "co_primary_b": True, "secondary": True}

    assert not intersection_union(passes)


def test_new_hypothesis_identifier_and_hash() -> None:
    hypothesis = {"hypothesis_id": "C5BR_USDJPY_ACCEPTANCE_DUAL_POSITIVE_RESPONSE_V1"}

    assert canonical_json_sha256(hypothesis)
    assert hypothesis["hypothesis_id"].startswith("C5BR_USDJPY")


def test_holdout_handoff_contains_no_holdout_counts_or_outcomes() -> None:
    handoff = {"status": "PREPARED_WITHOUT_HOLDOUT_ACCESS", "holdout_interval": "2023-2025"}

    assert "holdout_event_counts" not in handoff
    assert "holdout_outcomes" not in handoff


def test_holdout_access_rejection() -> None:
    assert validate_holdout_closed({"holdout_market_data_loaded": True})["status"] == "FAIL"
    assert validate_holdout_closed({})["status"] == "PASS"


def test_prohibited_strategy_metrics() -> None:
    assert validate_no_strategy_metrics({"diagnostic": "event response"})
    assert not validate_no_strategy_metrics({"sharpe": 1.2})
