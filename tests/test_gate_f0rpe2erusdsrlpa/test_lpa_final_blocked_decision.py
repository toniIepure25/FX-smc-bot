from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import verify_manifest_sections

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsrlpa"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_final_decision_stops_at_rate_source_access_without_empirical_access() -> None:
    decision = _load("final_decision.json")
    live = _load("live_adapter_certification.json")
    integrity = _load("integrity_audit.json")
    prohibited = _load("prohibited_data_audit.json")

    assert decision["decision"] == "BLOCKED_BY_RATE_SOURCE_ACCESS"
    assert decision["blocked_phase"] == 13
    assert decision["blocking_adapter"] == "ECB_EONIA_ESTR_V2"
    assert decision["blocking_code"] == "OFFICIAL_ENDPOINT_HTTP_STATUS_404"
    assert decision["actual_legacy_publication_timestamp_invented"] is False

    assert live["official_rate_provider_requests_sent"] == 1
    assert live["source_snapshots_persisted"] == 0
    assert live["numerical_rows_exposed_to_parser"] == 0
    assert live["market_provider_requests_sent"] == 0
    assert live["blocking_decision"] == "BLOCKED_BY_RATE_SOURCE_ACCESS"

    assert integrity["development_executed"] is False
    assert integrity["validation_executed"] is False
    assert integrity["replication_executed"] is False
    assert prohibited["status"] == "PASS"
    assert prohibited["official_payloads_committed_to_git"] is False
    assert prohibited["row_level_official_rate_data_committed_to_git"] is False
    assert prohibited["excluded_2023_2025_used_in_calculation"] is False
    assert prohibited["nzd_accessed"] is False
    assert prohibited["nzdusd_accessed"] is False


def test_final_manifest_hashes_reached_artifacts_and_contains_no_rate_rows() -> None:
    manifest = _load("reproducibility_manifest.json")
    verify_manifest_sections(
        manifest,
        repository_root=ROOT,
        sections=("artifact_sha256", "documentation_sha256", "source_sha256"),
        manifest_relative_path="results/gate_f0rpe2erusdsrlpa/reproducibility_manifest.json",
    )

    serialized = json.dumps(
        [
            _load("final_decision.json"),
            _load("integrity_audit.json"),
            _load("prohibited_data_audit.json"),
            _load("live_adapter_certification.json"),
            _load("live_adapter_matrix.json"),
        ],
        sort_keys=True,
    )
    for forbidden in ('"value"', "percentRate", "effectiveDate", "refRates"):
        assert forbidden not in serialized
