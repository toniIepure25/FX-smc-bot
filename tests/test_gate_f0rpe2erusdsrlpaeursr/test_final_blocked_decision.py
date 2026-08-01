from __future__ import annotations

import json
from pathlib import Path

RESULTS = (
    Path(__file__).resolve().parents[2] / "results" / "gate_f0rpe2erusdsrlpaeursr"
)


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text())


def test_final_decision_is_allowed_official_adapter_blocker() -> None:
    decision = _load("final_decision.json")
    live = _load("live_adapter_certification.json")

    assert decision["decision"] == "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
    assert live["blocking_decision"] == "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
    failure = live["failure"]
    assert isinstance(failure, dict)
    assert failure["adapter_id"] == "BOE_SONIA_V2"
    assert failure["failure_code"] == "OFFICIAL_ENDPOINT_HTTP_STATUS_403"


def test_final_safety_audits_block_empirical_access() -> None:
    prohibited = _load("prohibited_data_audit.json")
    integrity = _load("integrity_audit.json")
    live = _load("live_adapter_certification.json")

    assert prohibited["status"] == "PASS"
    assert integrity["status"] == "PASS"
    assert live["market_provider_requests_sent"] == 0
    assert live["numerical_rows_exposed_to_parser"] == 0
    assert live["source_snapshots_persisted"] == 0
    checks = prohibited["checks"]
    assert isinstance(checks, dict)
    assert checks["years_2023_2025_unused_and_unpersisted"] == "PASS"
    assert checks["nzd_and_nzdusd_inaccessible"] == "PASS"


def test_reproducibility_manifest_records_eur_v3_and_live_blocker_hashes() -> None:
    manifest = _load("reproducibility_manifest.json")
    artifacts = manifest["artifact_sha256"]
    commits = manifest["commits"]

    assert isinstance(artifacts, dict)
    assert isinstance(commits, dict)
    assert commits["eur_v3_certification_sha"] == (
        "eaccdb7729ee379153eaa532f28918515bf5a2e9"
    )
    assert "results/gate_f0rpe2erusdsrlpaeursr/live_adapter_certification.json" in artifacts
    assert manifest["final_decision"] == "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
