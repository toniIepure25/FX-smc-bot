from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.gate_c6 import (
    FINAL_DECISION,
    SEAL_ID,
    find_prohibited_strategy_metrics,
    validate_claim_matrix,
    validate_gate_ledger,
    validate_holdout_unauthorized,
    validate_lineage_seal,
    validate_manifest_completeness,
    validate_no_acceptance_holdout_handoff,
)

REPO = Path(__file__).resolve().parents[2]
RESULT_DIR = REPO / "results" / "gate_c6"
DOC_DIR = REPO / "docs" / "research"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_complete_gate_ledger_ordering() -> None:
    ledger = load_json(RESULT_DIR / "acceptance_research_gate_ledger.json")["gates"]
    validation = validate_gate_ledger(ledger)

    assert validation["complete"] is True
    assert validation["ordered"] is True
    assert validation["status"] == "PASS"


def test_preregistration_before_outcome_ordering() -> None:
    ledger = load_json(RESULT_DIR / "acceptance_research_gate_ledger.json")["gates"]
    validation = validate_gate_ledger(ledger)

    assert validation["preregistration_before_outcome"] is True


def test_final_number_reproduction() -> None:
    reproduction = load_json(RESULT_DIR / "final_result_reproduction.json")

    assert reproduction["status"] == "PASS"
    assert reproduction["development"]["differential"] == 13.668032786885094
    assert reproduction["validation"]["differential"] == 27.453020134228165
    assert reproduction["validation"]["absolute_sign_flip_p"] == 0.12843578210894552
    assert reproduction["transport"]["maximum_weight_median_multiple"] == 10.399999999999999


def test_claim_matrix_consistency() -> None:
    matrix = load_json(RESULT_DIR / "final_claim_matrix.json")["claims"]
    validation = validate_claim_matrix(matrix)

    assert validation["status"] == "PASS"
    assert validation["observed_statuses"]["C"] == "DESCRIPTIVELY_SUPPORTED_BUT_NOT_CONFIRMED"
    assert validation["observed_statuses"]["D"] == "NOT_SUPPORTED"
    assert validation["observed_statuses"]["E"] == "NOT_TESTED_AND_NOT_CLAIMABLE"


def test_prohibited_claim_detection() -> None:
    assert find_prohibited_strategy_metrics("Sharpe and drawdown were calculated")
    assert find_prohibited_strategy_metrics("relative event-minus-control effect") == []


def test_reconciliation_overlay_inclusion() -> None:
    lineage = load_json(RESULT_DIR / "lineage_integrity.json")

    assert lineage["status"] == "PASS"
    assert lineage["reconciliation_overlay"]["overlay_id"] == "C5AR_ARTIFACT_RECONCILIATION_V1"
    assert (
        lineage["reconciliation_overlay"]["overlay_hash"]
        == "64c00bb924b5f6db96a876ab476e53741da6377060150546df2a1b16ed10be06"
    )


def test_reproducibility_manifest_completeness() -> None:
    manifest = load_json(RESULT_DIR / "reproducibility_manifest.json")
    validation = validate_manifest_completeness(manifest)

    assert validation["status"] == "PASS"
    assert manifest["raw_or_row_level_data_included"] is False
    assert manifest["holdout_data_included"] is False


def test_lineage_seal_immutability() -> None:
    seal = load_json(RESULT_DIR / "acceptance_lineage_seal.json")
    tampered = dict(seal)
    tampered["status"] = "REOPENED"

    assert seal["seal_id"] == SEAL_ID
    assert validate_lineage_seal(seal)["status"] == "PASS"
    assert validate_lineage_seal(tampered)["status"] == "FAIL"


def test_holdout_remains_unauthorized() -> None:
    holdout = load_json(RESULT_DIR / "holdout_integrity.json")

    assert validate_holdout_unauthorized(holdout)["status"] == "PASS"
    assert holdout["status"] == "PASS"


def test_no_acceptance_holdout_handoff_exists() -> None:
    c6_paths = [
        "results/gate_c6/repository_state.json",
        "results/gate_c6/holdout_integrity.json",
        "docs/research/GATE_C6_FINAL_DECISION_MEMO.md",
    ]

    assert validate_no_acceptance_holdout_handoff(c6_paths)["status"] == "PASS"
    assert not (RESULT_DIR / "acceptance_holdout_handoff.json").exists()
    assert not (DOC_DIR / "ACCEPTANCE_HOLDOUT_HANDOFF.md").exists()


def test_no_prohibited_strategy_metrics_in_publication_documents() -> None:
    docs = [
        "ACCEPTANCE_RESEARCH_METHODS.md",
        "ACCEPTANCE_RESEARCH_RESULTS.md",
        "ACCEPTANCE_RESEARCH_ABSTRACT.md",
        "ACCEPTANCE_LIMITATIONS.md",
        "ACCEPTANCE_REPRODUCIBILITY.md",
        "ACCEPTANCE_LINEAGE_SEAL.md",
        "ACCEPTANCE_RESEARCH_LESSONS.md",
        "GATE_C6_FINAL_DECISION_MEMO.md",
    ]
    text = "\n".join((DOC_DIR / name).read_text(encoding="utf-8") for name in docs)

    assert find_prohibited_strategy_metrics(text) == []


def test_quality_gate_final_decision() -> None:
    quality = load_json(RESULT_DIR / "quality_gate_final.json")

    assert quality["status"] == "PASS"
    assert quality["final_decision"] == FINAL_DECISION
