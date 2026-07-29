from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.gate_c6r import (
    EXPECTED_C6_DECISION,
    EXPECTED_MANIFEST_HASH,
    EXPECTED_SEAL_HASH,
    EXPECTED_SEAL_ID,
)
from fx_smc_bot.research.gate_c6rci import (
    APPROVED_FOR_MERGE,
    EXPECTED_MYPY_HEAD_COUNT,
    EXPECTED_MYPY_TARGET_COUNT,
    EXPECTED_RUFF_NEW_POST_COUNT,
    EXPECTED_RUFF_NEW_PRE_COUNT,
    EXPECTED_RUFF_POST_COUNT,
    EXPECTED_RUFF_PRE_COUNT,
    EXPECTED_RUFF_TARGET_COUNT,
    REVIEW_ID_V1,
    REVIEW_ID_V2,
    TOUCHED_SOURCE_FILES,
    find_ruff_suppressions,
    ruff_delta,
    ruff_finding_identity,
    semantic_equivalence,
    semantic_fingerprint,
    validate_holdout_closed,
    validate_review_supersession,
)

REPO = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_exact_ruff_target_head_delta_calculation() -> None:
    delta = load_json(REPO / "results/gate_c6rci/ruff_finding_delta.json")

    assert delta["target_count"] == EXPECTED_RUFF_TARGET_COUNT
    assert delta["head_count"] == EXPECTED_RUFF_PRE_COUNT
    assert delta["new_on_branch_count"] == EXPECTED_RUFF_NEW_PRE_COUNT
    assert delta["ambiguous_count"] == 0


def test_line_movement_resistant_finding_identity() -> None:
    finding = {
        "filename": "D:/ComputaCenter/FX-smc-bot/src/fx_smc_bot/research/placebos.py",
        "code": "B905",
        "message": "`zip()` without an explicit `strict=` parameter",
        "source_line": "for bar_idx, orig_dir in zip(signal_bars, signal_directions):",
        "location": {"row": 129, "column": 30},
    }
    moved = {**finding, "location": {"row": 150, "column": 5}}

    assert ruff_finding_identity(finding) == ruff_finding_identity(moved)


def test_ambiguous_finding_rejection() -> None:
    duplicate = {
        "filename": "src/fx_smc_bot/research/example.py",
        "code": "E501",
        "message": "Line too long",
        "source_line": "x = 'long'",
    }

    assert ruff_delta([duplicate, duplicate], [duplicate])["status"] == "AMBIGUOUS_FINDING_IDENTITY"


def test_no_broad_ruff_suppression_added_to_touched_sources() -> None:
    findings = {
        path: find_ruff_suppressions(REPO / path)
        for path in TOUCHED_SOURCE_FILES
    }

    assert findings == {path: [] for path in TOUCHED_SOURCE_FILES}


def test_semantic_fingerprint_generation_for_touched_sources() -> None:
    fingerprints = [semantic_fingerprint(REPO / path) for path in TOUCHED_SOURCE_FILES]

    assert {item["path"].replace("\\", "/").split("FX-smc-bot/")[-1] for item in fingerprints}
    assert all(item["public_symbol_inventory"] for item in fingerprints)


def test_public_signature_and_constant_preservation() -> None:
    pre = load_json(REPO / "results/gate_c6rci/pre_change_semantic_fingerprints.json")["files"]
    post = [semantic_fingerprint(REPO / path) for path in TOUCHED_SOURCE_FILES]
    audit = semantic_equivalence(pre, post)

    assert audit["status"] == "PASS"
    assert all(row["checks"]["public_signatures_preserved"] for row in audit["files"])
    assert all(row["checks"]["module_constants_preserved"] for row in audit["files"])


def test_exception_behavior_parity() -> None:
    pre = load_json(REPO / "results/gate_c6rci/pre_change_semantic_fingerprints.json")["files"]
    post = [semantic_fingerprint(REPO / path) for path in TOUCHED_SOURCE_FILES]
    audit = semantic_equivalence(pre, post)

    assert all(row["checks"]["exception_behavior_preserved"] for row in audit["files"])


def test_scientific_artifact_hashes_remain_sealed() -> None:
    manifest = load_json(REPO / "results/gate_c6/reproducibility_manifest.json")
    seal = load_json(REPO / "results/gate_c6/acceptance_lineage_seal.json")
    quality = load_json(REPO / "results/gate_c6/quality_gate_final.json")

    assert manifest["manifest_hash"] == EXPECTED_MANIFEST_HASH
    assert seal["seal_id"] == EXPECTED_SEAL_ID
    assert seal["lineage_seal_hash"] == EXPECTED_SEAL_HASH
    assert quality["final_decision"] == EXPECTED_C6_DECISION


def test_compatibility_overlay_not_required_for_unsealed_sources() -> None:
    pre = load_json(REPO / "results/gate_c6rci/pre_change_semantic_fingerprints.json")["files"]

    assert {item["path"] for item in pre} == set(TOUCHED_SOURCE_FILES)
    assert all(item["sealed_manifest_references_hash"] is False for item in pre)


def test_zero_new_ruff_and_mypy_delta_after_remediation() -> None:
    final_static = load_json(REPO / "results/gate_c6rci/static_analysis_delta_final.json")

    assert final_static["ruff"]["target_count"] == EXPECTED_RUFF_TARGET_COUNT
    assert final_static["ruff"]["head_count"] == EXPECTED_RUFF_POST_COUNT
    assert final_static["ruff"]["new_on_branch_count"] == EXPECTED_RUFF_NEW_POST_COUNT
    assert final_static["mypy"]["target_count"] == EXPECTED_MYPY_TARGET_COUNT
    assert final_static["mypy"]["head_count"] == EXPECTED_MYPY_HEAD_COUNT
    assert final_static["mypy"]["new_on_branch_count"] == 0


def test_v1_review_lock_and_v2_supersession_integrity() -> None:
    payload = load_json(REPO / "results/gate_c6rci/review_supersession.json")

    assert payload["v1_review_id"] == REVIEW_ID_V1
    assert payload["v2_review_id"] == REVIEW_ID_V2
    assert validate_review_supersession(payload)["status"] == "PASS"


def test_holdout_rejection_and_no_new_handoff() -> None:
    holdout = load_json(REPO / "results/gate_c6rci/holdout_integrity.json")
    quality = load_json(REPO / "results/gate_c6rci/quality_gate_final.json")

    assert validate_holdout_closed(holdout)["status"] == "PASS"
    assert quality["checks"]["no_acceptance_holdout_handoff_created"] is True
    assert quality["checks"]["no_new_acceptance_hypothesis_created"] is True
    assert quality["final_decision"] == APPROVED_FOR_MERGE
