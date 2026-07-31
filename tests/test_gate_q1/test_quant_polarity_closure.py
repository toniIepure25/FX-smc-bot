from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fx_smc_bot.research.quant_polarity_closure import (
    CANDIDATE_IDS,
    CLOSURE_ID,
    EXPECTED_CLAIM_STATUSES,
    EXPECTED_RESULTS,
    QUARANTINE_ID,
    QUARANTINE_STATUS,
    REQUIRED_FUTURE_CONDITIONS,
    REQUIRED_SEAL_PROHIBITIONS,
    SEAL_ID,
    SEAL_STATUS,
    build_claim_matrix,
    detect_prohibited_changed_paths,
    payload_hash_without,
    validate_claim_matrix,
    validate_closed_lineage_action,
    validate_lineage_seal,
    validate_no_future_or_live_handoff,
    validate_posthoc_quarantine,
)

REPO = Path(__file__).resolve().parents[2]
Q1 = REPO / "results" / "gate_q1"
DOCS = REPO / "docs" / "research" / "quant_polarity_v2"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_aggregate_reproduction_matches_every_frozen_conclusion() -> None:
    reproduction = load_json(Q1 / "final_result_reproduction.json")

    assert reproduction["status"] == "PASS"
    assert reproduction["aggregate_check_count"] == 111
    assert reproduction["mismatch_count"] == 0
    assert reproduction["maximum_numeric_difference"] == 0.0
    assert reproduction["hash_agreement"] is True
    assert reproduction["market_data_loaded"] is False
    assert reproduction["row_level_trades_loaded"] is False

    for candidate_id in CANDIDATE_IDS:
        observed = reproduction["candidate_results"][candidate_id]
        for field, expected in EXPECTED_RESULTS[candidate_id].items():
            assert observed[field] == expected


def test_q0_failure_blob_is_preserved_despite_recorded_hash_typo() -> None:
    preservation = load_json(Q1 / "q0_failure_preservation.json")

    assert preservation["status"] == "Q0_FAILURE_PRESERVED_UNCHANGED"
    assert all(preservation["historical_blob_unchanged"].values())
    assert all(preservation["hash_matches_immutable_q0_blobs"].values())
    assert len(preservation["q0r_inheritance_record_mismatches"]) == 1
    mismatch = preservation["q0r_inheritance_record_mismatches"][0]
    assert mismatch["artifact"] == "holdout_integrity"
    assert mismatch["historical_blob_unchanged"] is True


def test_claim_matrix_identities_and_statuses_are_exact() -> None:
    claims = build_claim_matrix()
    validation = validate_claim_matrix(claims)

    assert validation["status"] == "PASS"
    assert validation["observed_statuses"] == EXPECTED_CLAIM_STATUSES
    assert load_json(Q1 / "final_claim_matrix.json")["claims"] == claims


def test_replication_failure_claim_is_explicitly_rejected() -> None:
    claims = {
        item["claim_id"]: item for item in load_json(Q1 / "final_claim_matrix.json")["claims"]
    }

    assert claims["D"]["status"] == "NOT_SUPPORTED"
    assert claims["E"]["status"] == "NOT_TESTED_BECAUSE_NO_CANDIDATE_WAS_ELIGIBLE"
    assert claims["I"]["status"] == "FALSE"
    assert claims["J"]["status"] == "NOT_AUTHORIZED"


def test_posthoc_quarantine_is_complete_and_tamper_evident() -> None:
    quarantine = load_json(Q1 / "posthoc_hypothesis_quarantine.json")
    tampered = {**quarantine, "hypotheses": quarantine["hypotheses"][:-1]}

    assert quarantine["quarantine_id"] == QUARANTINE_ID
    assert len(quarantine["hypotheses"]) == 18
    assert {item["status"] for item in quarantine["hypotheses"]} == {
        QUARANTINE_STATUS
    }
    assert validate_posthoc_quarantine(quarantine)["status"] == "PASS"
    assert validate_posthoc_quarantine(tampered)["status"] == "FAIL"


def test_failure_mechanisms_separate_research_from_operations() -> None:
    audit = load_json(Q1 / "failure_mechanism_audit.json")

    assert audit["controls"]["data_certification"] == "PASS"
    assert audit["controls"]["execution_integrity"] == "PASS"
    assert audit["controls"]["economic_performance"] == "FAIL"
    assert audit["controls"]["benchmark_relative_alpha"] == "FAIL"
    assert audit["controls"]["replication"] == "NOT_ACCESSED"
    assert audit["controls"]["prospective_candidate"] == "NOT_CREATED"


def test_lineage_seal_identity_hash_and_guards_are_immutable() -> None:
    seal = load_json(Q1 / "quant_polarity_lineage_seal.json")
    tampered = {**seal, "status": "REOPENED"}

    assert seal["seal_id"] == SEAL_ID
    assert seal["status"] == SEAL_STATUS
    assert all(item in seal["prohibitions"] for item in REQUIRED_SEAL_PROHIBITIONS)
    assert all(
        item in seal["permitted_future_work_requires"]
        for item in REQUIRED_FUTURE_CONDITIONS
    )
    assert validate_lineage_seal(seal)["status"] == "PASS"
    assert validate_lineage_seal(tampered)["status"] == "FAIL"


def test_closed_lineage_rejects_research_and_handoff_actions() -> None:
    for action in (
        "tune_current_sample",
        "lower_eligibility",
        "access_replication",
        "create_future_candidate",
        "create_live_handoff",
    ):
        result = validate_closed_lineage_action(action)
        assert result["permitted"] is False
        assert result["status"] == "BLOCKED_BY_LINEAGE_SEAL"

    assert validate_closed_lineage_action("publish_negative_result")["permitted"]
    assert validate_closed_lineage_action("create_review_pr")["permitted"]


def test_prohibited_git_content_classifier_blocks_payload_paths() -> None:
    prohibited = [
        "data/raw/q1/provider.bin",
        "data/canonical/q1/AUDUSD.parquet",
        "results/gate_q1/row_level_trades.json",
        "tmp/provider_payload.json",
        "config/client_secret.json",
    ]
    permitted = [
        "results/gate_q1/final_claim_matrix.json",
        "docs/research/quant_polarity_v2/QUANT_POLARITY_RESULTS.md",
        "src/fx_smc_bot/research/quant_polarity_closure.py",
    ]

    assert detect_prohibited_changed_paths(prohibited) == prohibited
    assert detect_prohibited_changed_paths(permitted) == []


def test_future_and_live_handoffs_are_blocked() -> None:
    assert validate_no_future_or_live_handoff(
        [
            "results/gate_q1/future_candidate_freeze.json",
            "results/gate_q1/live_capital_handoff.json",
        ]
    )["status"] == "FAIL"
    assert validate_no_future_or_live_handoff(
        [
            "results/gate_q1/final_claim_matrix.json",
            "docs/research/quant_polarity_v2/QUANT_POLARITY_LINEAGE_SEAL.md",
        ]
    )["status"] == "PASS"


def test_closure_lock_binds_seal_quarantine_and_shortlist() -> None:
    closure = load_json(Q1 / "closure_lock.json")
    seal = load_json(Q1 / "quant_polarity_lineage_seal.json")
    quarantine = load_json(Q1 / "posthoc_hypothesis_quarantine.json")

    assert closure["closure_id"] == CLOSURE_ID
    assert closure["seal_hash"] == seal["lineage_seal_hash"]
    assert closure["quarantine_hash"] == quarantine["quarantine_hash"]
    assert closure["replication_accessed"] is False
    assert closure["future_candidate_created"] is False
    assert closure["closure_hash"] == payload_hash_without(closure, "closure_hash")


def test_publication_package_preserves_negative_claim_boundaries() -> None:
    required = {
        "QUANT_POLARITY_ABSTRACT.md",
        "QUANT_POLARITY_METHODS.md",
        "QUANT_POLARITY_RESULTS.md",
        "QUANT_POLARITY_STATISTICAL_APPENDIX.md",
        "QUANT_POLARITY_LIMITATIONS.md",
        "QUANT_POLARITY_REPRODUCIBILITY.md",
        "QUANT_POLARITY_RESEARCH_LEDGER.md",
        "QUANT_POLARITY_RESEARCH_LESSONS.md",
        "QUANT_POLARITY_PACKAGE_INDEX.md",
    }
    text = " ".join(
        "\n".join(
            (DOCS / name).read_text(encoding="utf-8") for name in required
        ).split()
    )

    assert "No candidate entered the frozen replication shortlist" in text
    assert "Replication therefore has no outcome" in text
    assert "neither paper trading nor live-capital deployment" in text


def test_reproducibility_manifest_hashes_every_declared_artifact() -> None:
    manifest = load_json(Q1 / "reproducibility_manifest.json")
    records = [
        record
        for values in manifest["artifact_groups"].values()
        for record in values
    ]

    assert manifest["status"] == "PASS"
    assert manifest["all_declared_artifacts_present"] is True
    assert manifest["raw_canonical_or_row_level_data_included"] is False
    assert manifest["clean_room_market_data_loaded"] is False
    assert manifest["replication_data_accessed"] is False
    assert manifest["manifest_hash"] == payload_hash_without(
        manifest, "manifest_hash"
    )
    for record in records:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["raw_sha256"]
