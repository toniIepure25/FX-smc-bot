from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsrlpa"
STARTING_SHA = "c35c17aacb20afc682c14a096de1432120bec35c"


def _load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_repository_state_matches_fetched_remote_start() -> None:
    state = _load("repository_state.json")

    assert state["branch"] == "research/classical-fx-risk-premia-v2-future-baseline"
    assert state["required_starting_sha"] == STARTING_SHA
    assert state["local_starting_sha"] == STARTING_SHA
    assert state["remote_tracking_sha"] == STARTING_SHA
    assert state["remote_verification_mode"] == "FETCH_ALL_PRUNE"
    assert state["worktree_clean_before_gate_artifacts"] is True
    assert state["status"] == "PASS"


def test_predecessor_block_is_preserved_without_timestamp_fabrication() -> None:
    inherited = _load("predecessor_inheritance.json")

    assert inherited["status"] == "PREDECESSOR_BLOCK_PRESERVED_NOT_REVERSED"
    assert inherited["predecessor_decision"] == "BLOCKED_BY_USD_PUBLICATION_AVAILABILITY"
    assert inherited["legacy_actual_clock_time_known"] is False
    assert inherited["fabricated_timestamp_used"] is False
    assert inherited["ny_fed_effr_v3_implemented"] is False
    assert inherited["usd_rate_versions"] == 0
    assert inherited["economic_outcomes"] == 0


def test_predecessor_artifact_hashes_are_unchanged() -> None:
    hashes = _load("predecessor_inheritance.json")["predecessor_artifact_sha256"]

    assert len(hashes) == 10
    for relative_path, expected in hashes.items():
        actual = manifest_file_sha256(
            ROOT / relative_path,
            SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
        )
        assert actual == expected, relative_path


def test_protocol_lock_preserves_scientific_freezes() -> None:
    lock = _load("protocol_inheritance_lock.json")

    assert lock["lock_id"] == "F0RPE2ERUSDSRLPA_PROTOCOL_INHERITANCE_V1"
    assert lock["starting_sha"] == STARTING_SHA
    assert lock["scientific_protocol_changed"] is False
    assert len(lock["locked_artifact_sha256"]) == 11
    for relative_path, expected in lock["locked_artifact_sha256"].items():
        actual = manifest_file_sha256(
            ROOT / relative_path,
            SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
        )
        assert actual == expected, relative_path


def test_pre_amendment_integrity_has_no_outcomes_or_prohibited_access() -> None:
    integrity = _load("pre_amendment_integrity.json")

    assert integrity["legacy_actual_publication_clock_known"] is False
    assert integrity["fabricated_timestamp_used"] is False
    assert integrity["usd_rate_versions"] == 0
    assert integrity["economic_outcomes"] == 0
    assert integrity["historical_2023_2025_used"] is False
    assert integrity["historical_2023_2025_persisted"] is False
    assert integrity["historical_2023_2025_untouched_claim"] is False
    assert integrity["nzd_accessed"] is False
    assert integrity["nzdusd_accessed"] is False
