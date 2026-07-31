from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsr"


def _load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_publication_assessment_stops_before_timestamp_fabrication() -> None:
    assessment = _load("usd_publication_revision_availability.json")

    assert assessment["legacy_regime"]["exact_rate_version_timestamp_constructible"] is False
    assert assessment["modern_regime"]["eligible_at_17_05_on_publication_day"] is True
    assert assessment["fabricated_clock_instant_used"] is False
    assert assessment["rate_versions_emitted"] == 0
    assert assessment["blocking_decision"] == "BLOCKED_BY_USD_PUBLICATION_AVAILABILITY"


def test_final_decision_is_fail_closed_at_phase_six() -> None:
    decision = _load("final_decision.json")

    assert decision["highest_phase_reached"] == (
        "PHASE_6_PUBLICATION_AND_REVISION_AVAILABILITY"
    )
    assert decision["decision"] == "BLOCKED_BY_USD_PUBLICATION_AVAILABILITY"
    assert decision["ny_fed_effr_v3_implemented"] is False
    assert decision["fabricated_timestamp_used"] is False
    assert decision["usd_official_requests"] == 2
    assert decision["usd_local_snapshots"] == 2
    assert decision["usd_observation_identities"] == 0
    assert decision["usd_rate_versions"] == 0
    assert decision["market_requests"] == 0


def test_integrity_and_prohibited_data_audits_pass() -> None:
    integrity = _load("integrity_audit.json")
    prohibited = _load("prohibited_data_audit.json")

    assert integrity["predecessor_failure_preserved"] is True
    assert integrity["historical_2023_2025_used"] is False
    assert integrity["historical_2023_2025_persisted"] is False
    assert integrity["historical_2023_2025_untouched_claim"] is False
    assert integrity["nzd_accessed"] is False
    assert integrity["nzdusd_accessed"] is False
    assert integrity["status"] == "PASS"
    assert prohibited["official_raw_responses_tracked_by_gate"] == 0
    assert prohibited["absolute_clean_room_paths_tracked_by_gate"] == 0
    assert prohibited["status"] == "PASS"
