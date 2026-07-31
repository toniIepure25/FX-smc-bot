from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsr"
STARTING_SHA = "f460fe6a2f5c83fee8e06dd0168d983f9bfa70f3"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_repository_state_matches_authorized_start_without_network() -> None:
    state = _load("repository_state.json")

    assert state["branch"] == "research/classical-fx-risk-premia-v2-future-baseline"
    assert state["required_starting_sha"] == STARTING_SHA
    assert state["local_starting_sha"] == STARTING_SHA
    assert state["remote_tracking_sha"] == STARTING_SHA
    assert state["remote_verification_mode"] == "EXISTING_LOCAL_TRACKING_REF_NO_NETWORK"
    assert state["network_access_performed"] is False
    assert state["worktree_clean_before_gate_artifacts"] is True
    assert state["git_diff_check_before_gate_artifacts"] == "PASS"
    assert state["status"] == "PASS"


def test_pre_reconciliation_integrity_has_no_outcomes_or_prohibited_access() -> None:
    integrity = _load("pre_reconciliation_integrity.json")

    assert integrity["captured_at_sha"] == STARTING_SHA
    assert integrity["predecessor_failure_mutated"] is False
    assert integrity["predecessor_live_adapter_fail_reclassified"] is False
    assert integrity["predecessor_artifacts_overwritten"] is False
    assert integrity["network_access_performed"] is False
    assert integrity["old_clean_room_roots_inspected"] is False
    assert integrity["historical_2023_2025_used"] is False
    assert integrity["historical_2023_2025_persisted"] is False
    assert integrity["historical_2023_2025_untouched_claim"] is False
    assert integrity["nzd_accessed"] is False
    assert integrity["nzdusd_accessed"] is False
    assert integrity["economic_outcomes_generated"] == 0


def test_predecessor_failure_is_preserved_exactly() -> None:
    inherited = _load("predecessor_failure_inheritance.json")

    assert inherited["status"] == "PREDECESSOR_FAILURE_PRESERVED_NOT_REVERSED"
    assert inherited["predecessor_tip_sha"] == STARTING_SHA
    assert inherited["predecessor_decision"] == "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
    assert inherited["blocking_adapter"] == "NY_FED_EFFR_V2"
    assert inherited["blocking_failure"] == "SOURCE_RESPONSE_SCHEMA_VIOLATION"
    assert inherited["failure_stage"] == "RESPONSE_FIREWALL"
    assert inherited["source_snapshots_persisted"] == 0
    assert inherited["numerical_rows_exposed_to_parser"] == 0
    assert inherited["market_requests"] == 0
    assert inherited["economic_outcomes"] == 0


def test_predecessor_artifacts_are_unchanged() -> None:
    inherited = _load("predecessor_failure_inheritance.json")
    hashes = inherited["predecessor_artifact_sha256"]

    assert isinstance(hashes, dict)
    assert len(hashes) == 7
    for relative_path, expected in hashes.items():
        assert (
            manifest_file_sha256(
                ROOT / relative_path,
                SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            )
            == expected
        ), relative_path


def test_scientific_protocol_lock_matches_all_frozen_inputs() -> None:
    lock = _load("protocol_inheritance_lock.json")
    hashes = lock["locked_artifact_sha256"]

    assert lock["lock_id"] == "F0RPE2ERUSDSR_PROTOCOL_INHERITANCE_V1"
    assert lock["starting_sha"] == STARTING_SHA
    assert lock["scientific_protocol_changed"] is False
    assert lock["preserved_contract_ids"] == [
        "F0_RATE_PROVENANCE_AMENDMENT_V1",
        "F0RPE2ER_SCIENTIFIC_PROTOCOL_INHERITANCE_V1",
        "F0RPE2ER_FUTURE_ONLY_CONFIRMATORY_BASELINE_V1",
    ]
    assert lock["permitted_implementation_changes"] == [
        "PARSER",
        "SCHEMA_NORMALIZATION",
        "ADAPTER",
        "RESPONSE_FIREWALL",
        "PERSISTENCE",
        "ORCHESTRATION",
    ]
    assert isinstance(hashes, dict)
    assert len(hashes) == 9
    for relative_path, expected in hashes.items():
        assert (
            manifest_file_sha256(
                ROOT / relative_path,
                SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            )
            == expected
        ), relative_path


def test_usdsr_clean_room_is_external_new_and_path_sanitized() -> None:
    clean_room = _load("clean_room_root.json")

    assert clean_room["configured_path_template"] == (
        "<repository-parent>/FX-smc-bot-local-data/f0rpe2erusdsr_v1"
    )
    assert clean_room["absolute_path_committed"] is False
    assert clean_room["outside_repository"] is True
    assert clean_room["existed_before_gate"] is False
    assert clean_room["initially_empty"] is True
    assert clean_room["symlink_or_junction_escape"] is False
    assert clean_room["old_roots_inspected"] is False
