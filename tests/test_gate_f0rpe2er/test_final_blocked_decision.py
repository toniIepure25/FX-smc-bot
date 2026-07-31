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


def test_live_schema_failure_stops_before_persistence_and_market_access() -> None:
    certification = _load("live_adapter_certification.json")
    decision = _load("final_decision.json")

    assert certification["failure_code"] == "SOURCE_RESPONSE_SCHEMA_VIOLATION"
    assert certification["failure_disposition"] == (
        "RESPONSE_REJECTED_ATOMICALLY_BEFORE_PERSISTENCE"
    )
    assert certification["official_rate_provider_requests_sent"] == 1
    assert certification["source_snapshots_persisted"] == 0
    assert certification["numerical_rows_exposed_to_parser"] == 0
    assert certification["market_provider_requests_sent"] == 0
    assert decision["decision"] == "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"


def test_final_integrity_audits_preserve_future_only_claims() -> None:
    audit = _load("integrity_audit.json")
    prohibited = _load("prohibited_data_audit.json")

    assert audit["failed_f0rpe2e_audit_preserved"] is True
    assert audit["historical_2023_2025_untouched_claim"] is False
    assert audit["historical_2023_2025_persisted"] is False
    assert audit["nzd_accessed"] is False
    assert audit["nzdusd_accessed"] is False
    assert audit["future_prospective_observations_accessed"] is False
    assert audit["future_prospective_storage_enumerated"] is False
    assert prohibited["status"] == "PASS"


def test_unreached_empirical_stages_do_not_contain_placeholder_results() -> None:
    decision = _load("final_decision.json")
    matrix = _load("live_adapter_matrix.json")

    assert decision["development_executed"] is False
    assert decision["validation_executed"] is False
    assert decision["replication_executed"] is False
    assert decision["future_portfolio_frozen"] is False
    assert matrix["all_required_adapters_certified"] is False


def test_reproducibility_manifest_hashes_every_reached_artifact() -> None:
    manifest = _load("reproducibility_manifest.json")
    for section in ("artifact_sha256", "documentation_sha256", "source_sha256"):
        hashes = manifest[section]
        assert isinstance(hashes, dict)
        for relative_path, expected in hashes.items():
            assert manifest_file_sha256(
                ROOT / relative_path,
                SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            ) == expected, relative_path
