from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fx_smc_bot.research.gate_c4_event_alpha import assert_development_request
from fx_smc_bot.research.gate_c4b_mechanism import (
    EXPECTED_MECHANISM_PREREG_HASH,
    GateC4BPaths,
    absolute_relative_decomposition,
    artifact_integrity,
    candidate_selection_trace,
    confirmation_latency,
    contrarian_diagnostic,
    load_acceptance,
    relative_resilience,
    split_integrity,
    transaction_cost_decomposition,
)

ROOT = Path(__file__).resolve().parents[2]


def _paths() -> GateC4BPaths:
    return GateC4BPaths(root=ROOT)


def _merged() -> pd.DataFrame:
    return load_acceptance(_paths())[2]


def test_c4a_research_stop_enforced_and_original_artifacts_unchanged() -> None:
    integrity = artifact_integrity(_paths())
    assert integrity["status"] == "PASS"
    assert integrity["checks"]["c4a_research_stop_status_stop"] is True
    assert integrity["mechanism_preregistration_hash"] == EXPECTED_MECHANISM_PREREG_HASH


def test_absolute_relative_identity() -> None:
    result = absolute_relative_decomposition(_merged())
    assert result["identity_check"]["passed"] is True
    assert result["interpretation"] == "B_EVENT_NEGATIVE_CONTROL_SUBSTANTIALLY_MORE_NEGATIVE"


def test_executable_versus_mid_return_decomposition() -> None:
    result = transaction_cost_decomposition(_merged())
    primary = result["primary_non_overlap"]
    assert primary["mean_total_spread_drag_points"] == pytest.approx(
        primary["mean_mid_return_points"] - primary["mean_executable_markout_points"]
    )
    assert result["cost_limited_requirements"]["no_spread_threshold_required"] is True


def test_trajectory_horizons_are_immutable() -> None:
    from fx_smc_bot.research.gate_c4b_mechanism import forward_trajectory

    trajectory = forward_trajectory(_merged())
    assert list(trajectory["horizons"].keys()) == ["15", "30", "60", "120", "240"]


def test_confirmation_latency_is_causal_and_reports_missing_preconfirmation_prices() -> None:
    result = confirmation_latency(_merged())
    assert result["mean_time_from_break_to_confirmation_minutes"] == 5.0
    assert result["mean_time_from_confirmation_to_entry_minutes"] == 5.0
    assert result["timing_decay_requirements"]["lifecycle_price_data_sufficient"] is False


def test_single_predefined_direction_flip() -> None:
    result = contrarian_diagnostic(_merged())
    assert "flipped_direction_absolute_markout" in result
    assert set(result["requirements"]) == {
        "flipped_executable_positive",
        "flipped_discovery_positive",
        "flipped_replication_positive",
        "non_overlap_positive",
        "not_dominated_by_one_year",
        "latency_supports_reversal",
    }


def test_no_session_or_subgroup_selection() -> None:
    from fx_smc_bot.research.gate_c4b_mechanism import mechanism_stability

    stability = mechanism_stability(_merged())
    assert stability["no_subgroup_selected"] is True
    assert "session" in stability["stability_dimensions"]


def test_deterministic_candidate_selection_tree_prefers_precedence_not_magnitude() -> None:
    cost = {"cost_limited_requirements": {"a": False}}
    relative = {"requirements": {"a": True}}
    contrarian = {"requirements": {"a": True}}
    latency = {
        "timing_decay_requirements": {
            "pre_entry_move_fraction_material": True,
            "post_entry_continuation_non_positive": True,
            "discovery_replication_same_qualitative_decay": True,
            "no_retroactive_entry_rule": True,
            "lifecycle_price_data_sufficient": True,
        }
    }
    selected = candidate_selection_trace(cost, relative, contrarian, latency)
    assert selected["selected_mechanism"] == "RELATIVE_RESILIENCE"
    assert selected["selection_not_based_on_effect_magnitude"] is True


def test_ambiguous_multi_candidate_uses_frozen_precedence() -> None:
    cost = {"cost_limited_requirements": {"a": True}}
    relative = {"requirements": {"a": True}}
    contrarian = {"requirements": {"a": True}}
    latency = {
        "timing_decay_requirements": {
            "pre_entry_move_fraction_material": False,
            "post_entry_continuation_non_positive": True,
            "discovery_replication_same_qualitative_decay": True,
            "no_retroactive_entry_rule": True,
            "lifecycle_price_data_sufficient": True,
        }
    }
    selected = candidate_selection_trace(cost, relative, contrarian, latency)
    assert selected["selected_mechanism"] == "COST_LIMITED_CONTINUATION"


def test_exactly_one_hypothesis_may_be_frozen_from_real_trace() -> None:
    merged = _merged()
    cost = transaction_cost_decomposition(merged)
    relative = relative_resilience(merged, placebo_not_reproduced=True)
    contrarian = contrarian_diagnostic(merged)
    latency = confirmation_latency(merged)
    selected = candidate_selection_trace(cost, relative, contrarian, latency)
    assert selected["passed_classes"] == ["RELATIVE_RESILIENCE"]


def test_validation_handoff_contains_no_validation_outcomes() -> None:
    split = split_integrity()
    assert split["validation_event_counts_computed"] is False
    assert split["validation_outcomes_computed"] is False


def test_validation_and_holdout_access_rejection() -> None:
    with pytest.raises(ValueError):
        assert_development_request("USDJPY", (2020,))
    with pytest.raises(ValueError):
        assert_development_request("USDJPY", (2023,))
