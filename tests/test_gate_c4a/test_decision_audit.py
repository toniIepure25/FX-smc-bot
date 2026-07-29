from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.research.gate_c4_event_alpha import assert_development_request
from fx_smc_bot.research.gate_c4a_decision_audit import (
    DIAGNOSTIC_CRITERIA,
    EXPECTED_OUTCOME_COMMIT,
    EXPECTED_PREREG_COMMIT,
    GateC4APaths,
    acceptance_answers,
    adjudicated_decisions,
    artifact_integrity,
    criterion_trace,
    placebo_mapping_audit,
    power_decision_audit,
    preregistration_decision_matrix,
    repository_state,
    reproduction_comparison,
    split_integrity,
)

ROOT = Path(__file__).resolve().parents[2]


def _paths() -> GateC4APaths:
    return GateC4APaths(root=ROOT)


def test_preregistration_hash_enforcement_and_artifact_integrity() -> None:
    integrity = artifact_integrity(_paths())
    assert integrity["status"] == "PASS"
    assert integrity["checks"]["preregistration_hash"] is True
    assert integrity["checks"]["event_table_manifest_hash"] is True


def test_preregistration_commit_precedes_outcomes() -> None:
    state = repository_state(_paths())
    assert state["preregistration_commit"] == EXPECTED_PREREG_COMMIT
    assert state["outcome_commit"] == EXPECTED_OUTCOME_COMMIT
    assert state["preregistration_precedes_outcome"] is True


def test_complete_criterion_trace_and_mandatory_diagnostic_separation() -> None:
    matrix = preregistration_decision_matrix(_paths())
    trace, rows = criterion_trace(_paths())
    assert matrix["mandatory_confirmation_criteria"]
    assert "power_mde80" in DIAGNOSTIC_CRITERIA
    assert all(row["criterion"] for row in rows["rows"])
    acceptance = trace["families"]["liquidity_acceptance_fvg_continuation"]
    assert "positive_event_primary_effect" in acceptance["failed_mandatory_criteria"]
    assert "mde80_effect_threshold" not in acceptance["failed_mandatory_criteria"]


def test_mde_cannot_affect_decision_unless_preregistered() -> None:
    trace, _ = criterion_trace(_paths())
    audit = power_decision_audit(_paths(), trace)
    acceptance = audit["families"]["liquidity_acceptance_fvg_continuation"]
    assert acceptance["observed_effect_below_mde80"] is True
    assert acceptance["mde_preregistered_as_confirmation_threshold"] is False
    assert acceptance["mde_used_by_decision_engine"] is False


def test_holm_mapping_and_boolean_aggregation_for_acceptance() -> None:
    trace, _ = criterion_trace(_paths())
    acceptance = {
        row["criterion"]: row
        for row in trace["families"]["liquidity_acceptance_fvg_continuation"]["criteria"]
    }
    assert acceptance["holm_adjusted_p_value"]["passed"] is True
    assert acceptance["positive_matched_control_difference"]["passed"] is True
    assert acceptance["positive_event_primary_effect"]["passed"] is False
    decisions = adjudicated_decisions(trace)
    assert (
        decisions["families"]["liquidity_acceptance_fvg_continuation"]["decision"]
        == "MIXED_EXPLORATORY_SIGNAL"
    )


def test_placebo_family_mapping_does_not_assign_london_to_acceptance() -> None:
    audit = placebo_mapping_audit(_paths())
    assert audit["status"] == "PASS"
    assert audit["london_or_not_assigned_to_acceptance"] is True
    assert audit["families"]["liquidity_acceptance_fvg_continuation"]["aggregated_passed"] is True
    assert audit["families"]["opening_range_london"]["aggregated_passed"] is False


def test_replication_split_and_overlap_primary_selection() -> None:
    matrix = preregistration_decision_matrix(_paths())
    acceptance = matrix["families"]["liquidity_acceptance_fvg_continuation"]
    assert acceptance["primary_horizon_minutes"] == 120
    assert acceptance["primary_sample"] == "non-overlapping primary events"
    trace, _ = criterion_trace(_paths())
    answers = acceptance_answers(trace, _paths())
    assert answers["replication_effect_passed"] is True
    assert answers["non_overlap_sample_retained_direction"] is True


def test_year_concentration_is_diagnostic_not_mandatory() -> None:
    trace, _ = criterion_trace(_paths())
    acceptance = trace["families"]["liquidity_acceptance_fvg_continuation"]
    assert "year_concentration" not in acceptance["failed_mandatory_criteria"]


def test_missing_artifact_behavior(tmp_path: Path) -> None:
    paths = GateC4APaths(root=tmp_path)
    with pytest.raises(FileNotFoundError):
        artifact_integrity(paths)


def test_no_rounding_dependent_decisions() -> None:
    trace, _ = criterion_trace(_paths())
    acceptance = trace["families"]["liquidity_acceptance_fvg_continuation"]
    event_effect = next(
        row for row in acceptance["criteria"] if row["criterion"] == "positive_event_primary_effect"
    )
    assert event_effect["observed_value"] < 0
    assert round(event_effect["observed_value"], 2) < 0


def test_deterministic_c4_reproduction() -> None:
    comparison = reproduction_comparison(_paths())
    assert comparison["status"] == "PASS"


def test_validation_and_holdout_access_rejection() -> None:
    with pytest.raises(ValueError):
        assert_development_request("USDJPY", (2020,))
    with pytest.raises(ValueError):
        assert_development_request("USDJPY", (2023,))
    assert split_integrity()["status"] == "PASS"


def test_validation_handoff_immutability_when_no_handoff() -> None:
    trace, _ = criterion_trace(_paths())
    decisions = adjudicated_decisions(trace)
    assert decisions["overall_gate_c4a_decision"] == "C4_MIXED_RESULT_UPHELD_DO_NOT_OPEN_VALIDATION"
