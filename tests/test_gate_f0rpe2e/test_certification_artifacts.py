from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2e"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_synthetic_adapter_certification_cannot_claim_official_pass() -> None:
    matrix = _load("official_rate_adapter_matrix.json")
    certification = _load("official_rate_adapter_certification.json")
    adapters = matrix["adapters"]

    assert isinstance(adapters, dict)
    assert set(adapters) == {"USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"}
    assert all(item["synthetic_status"] == "PASS" for item in adapters.values())
    assert all(item["official_endpoint_status"] == "NOT_RUN" for item in adapters.values())
    assert matrix["official_endpoint_certification_promoted"] is False
    assert certification["promotes_rate_adapters_certified_stage"] is False
    assert certification["official_rate_provider_requests_sent"] == 0
    assert certification["source_snapshots_persisted"] == 0


def test_unreached_empirical_metrics_are_null_or_not_run() -> None:
    storage = _load("storage_budget.json")
    for key, value in storage.items():
        if key.endswith("_estimate") or key in {"free_bytes", "required_reserve"}:
            assert value is None
    assert storage["safe_development_peak"] == "NOT_RUN"
    assert storage["status"] == "NOT_RUN"


def test_prospective_incident_fails_closed_before_provider_access() -> None:
    integrity = _load("prospective_integrity.json")

    assert integrity["status"] == "FAIL"
    assert integrity["blocking_decision"] == "BLOCKED_BY_PROSPECTIVE_INTEGRITY"
    assert integrity["official_rate_provider_requests_sent"] == 0
    assert integrity["market_provider_requests_sent"] == 0
    assert integrity["source_snapshots_persisted"] == 0
    assert integrity["row_level_observations_persisted"] == 0
