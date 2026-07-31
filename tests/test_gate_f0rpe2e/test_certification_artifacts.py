from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

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


def test_reproducibility_manifest_hashes_match() -> None:
    manifest = _load("reproducibility_manifest.json")
    declared: dict[str, str] = {}
    for section in ("artifact_sha256", "documentation_sha256"):
        declared.update(cast(dict[str, str], manifest[section]))

    for relative_path, expected in declared.items():
        actual = manifest_file_sha256(
            ROOT / relative_path,
            SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
        )
        assert actual == expected, relative_path

    revision = cast(str, manifest["implementation_sha_before_final_artifacts"])
    sources = cast(dict[str, str], manifest["source_sha256"])
    for relative_path, expected in sources.items():
        blob = subprocess.run(
            ["git", "show", f"{revision}:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        normalized = blob.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert hashlib.sha256(normalized).hexdigest() == expected, relative_path
