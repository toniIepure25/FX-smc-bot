from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2er"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_infrastructure_freeze_hashes_exact_components() -> None:
    freeze = _load("empirical_infrastructure_freeze.json")
    hashes = freeze["component_sha256"]
    assert isinstance(hashes, dict)
    for relative_path, expected in hashes.items():
        assert manifest_file_sha256(
            ROOT / relative_path,
            SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
        ) == expected, relative_path
    assert freeze["freeze_id"] == "F0RPE2ER_EMPIRICAL_INFRASTRUCTURE_V1"
    assert freeze["full_observation_acquisition_authorized"] is False
    assert freeze["official_numerical_requests_before_freeze"] == 0


def test_local_certifications_have_no_official_observations() -> None:
    firewall = _load("response_firewall_certification.json")
    store = _load("vintage_store_certification.json")
    alignment = _load("rate_alignment_certification.json")

    assert firewall["violation_records_contain_numerical_values"] is False
    assert firewall["official_network_requests"] == 0
    assert store["store_schema_id"] == "F0RPE2ER_RATE_VINTAGE_STORE_V3"
    assert store["official_observation_identities"] == 0
    assert store["official_rate_versions"] == 0
    assert store["official_revisions"] == 0
    assert alignment["strategy_timestamp"] == "17:05 America/New_York"
    assert alignment["official_panel_rows"] == 0


def test_boundary_commit_precedes_every_infrastructure_commit() -> None:
    boundary = _load("integrity_boundary_commit.json")
    freeze = _load("empirical_infrastructure_freeze.json")

    assert boundary["integrity_boundary_pre_network_sha"] == (
        "313349aecc6694c1e852f1d0b2b2f6170ed81514"
    )
    assert freeze["integrity_boundary_pre_network_sha"] == boundary[
        "integrity_boundary_pre_network_sha"
    ]

