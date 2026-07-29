from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.gate_c6r import (
    EXPECTED_C6_DECISION,
    EXPECTED_MANIFEST_HASH,
    EXPECTED_SEAL_HASH,
    EXPECTED_SEAL_ID,
    find_misleading_phrases,
    find_prohibited_paths,
    validate_c6_seal,
    validate_claim_statuses,
    validate_holdout_closed,
    validate_manifest_hash,
    validate_temp_ignore,
)

REPO = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pytest_tmp_directories_are_ignored() -> None:
    assert validate_temp_ignore((REPO / ".gitignore").read_text(encoding="utf-8"))


def test_holdout_remains_closed() -> None:
    payload = load_json(REPO / "results/gate_c6/holdout_integrity.json")

    assert validate_holdout_closed(payload)["status"] == "PASS"


def test_manifest_hash_is_sealed_value() -> None:
    manifest = load_json(REPO / "results/gate_c6/reproducibility_manifest.json")

    assert validate_manifest_hash(manifest)["status"] == "PASS"
    assert manifest["manifest_hash"] == EXPECTED_MANIFEST_HASH


def test_lineage_seal_identity_and_hash_are_fixed() -> None:
    seal = load_json(REPO / "results/gate_c6/acceptance_lineage_seal.json")

    assert validate_c6_seal(seal)["status"] == "PASS"
    assert seal["seal_id"] == EXPECTED_SEAL_ID
    assert seal["lineage_seal_hash"] == EXPECTED_SEAL_HASH


def test_final_claim_statuses_are_unchanged() -> None:
    claim_matrix = load_json(REPO / "results/gate_c6/final_claim_matrix.json")

    assert validate_claim_statuses(claim_matrix["claims"])["status"] == "PASS"


def test_new_hypothesis_and_handoff_absent_from_c6() -> None:
    quality = load_json(REPO / "results/gate_c6/quality_gate_final.json")

    assert quality["checks"]["no_new_acceptance_hypothesis_created"] is True
    assert quality["checks"]["no_acceptance_holdout_handoff_created"] is True


def test_c6_final_decision_is_unchanged() -> None:
    quality = load_json(REPO / "results/gate_c6/quality_gate_final.json")

    assert quality["final_decision"] == EXPECTED_C6_DECISION


def test_prohibited_paths_detector_flags_data_and_caches() -> None:
    paths = [
        "data/raw/gate_c5ar/events.parquet",
        "tools/dukascopy-node/node_modules/pkg/index.js",
        "docs/research/ACCEPTANCE_RESEARCH_RESULTS.md",
    ]

    findings = find_prohibited_paths(paths)
    assert "data/raw/gate_c5ar/events.parquet" in findings
    assert "tools/dukascopy-node/node_modules/pkg/index.js" in findings


def test_document_quality_phrase_scanner_allows_negated_context() -> None:
    assert find_misleading_phrases("This is not standalone alpha.") == []
    assert find_misleading_phrases("This is standalone alpha.") == ["standalone alpha"]
