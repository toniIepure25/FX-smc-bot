from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2e"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_provenance_inheritance_is_outcome_blind_and_preserved() -> None:
    inherited = _load("provenance_inheritance.json")
    integrity = _load("pre_execution_integrity.json")

    assert inherited["status"] == "PASS"
    assert inherited["original_f0_decision"] == "BLOCKED_BY_RATE_DATA_PROVENANCE"
    assert inherited["nzd_amendment_route"] == "OUTCOME_BLIND_NZD_EXCLUSION"
    assert inherited["pre_amendment_observation_access"] is False
    assert inherited["historical_artifact_mutation"] is False
    assert integrity["market_provider_requests_sent"] == 0
    assert integrity["rate_provider_requests_sent"] == 0
    assert integrity["nzd_rate_accessed"] is False
    assert integrity["nzdusd_market_accessed"] is False


def test_inherited_artifact_hashes_match() -> None:
    for artifact_name in ("provenance_inheritance.json", "protocol_inheritance_lock.json"):
        artifact = _load(artifact_name)
        hashes = artifact.get("artifact_sha256", artifact.get("locked_artifact_sha256"))
        assert isinstance(hashes, dict)
        for relative_path, expected in hashes.items():
            actual = manifest_file_sha256(
                ROOT / relative_path,
                SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            )
            assert actual == expected, relative_path


def test_scientific_lock_forbids_scientific_changes() -> None:
    lock = _load("protocol_inheritance_lock.json")

    assert lock["lock_id"] == "F0RPE2E_SCIENTIFIC_PROTOCOL_INHERITANCE_V1"
    assert lock["status"] == "PASS"
    assert lock["scientific_changes_permitted"] is False
    changed_flags = [key for key in lock if key.endswith("_changed")]
    assert changed_flags
    assert all(lock[key] is False for key in changed_flags)
