"""Gate C.6 Acceptance research-program closure helpers.

These helpers validate the final publication package without opening or
enumerating holdout data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FINAL_DECISION = "ACCEPTANCE_RESEARCH_PROGRAM_CLOSED_WITH_MIXED_NONTRANSPORTABLE_RESULT"
SEAL_ID = "USDJPY_ACCEPTANCE_RESEARCH_LINEAGE_V1"
SEAL_STATUS = "CLOSED_MIXED_NONTRANSPORTABLE_RESULT"

REQUIRED_GATE_IDS = [
    "C3FV",
    "C3F-TPR",
    "C3F-CRSF",
    "C4",
    "C4-A",
    "C4-B",
    "C5",
    "C5-A",
    "C5-A-DQB",
    "C5-A-DQR",
    "C5-A-R",
    "C5-A-R-IR",
    "C5-B-R",
    "C6",
]

EXPECTED_CLAIM_STATUSES = {
    "A": "SUPPORTED_IN_DEVELOPMENT",
    "B": "SUPPORTED_IN_VALIDATION",
    "C": "DESCRIPTIVELY_SUPPORTED_BUT_NOT_CONFIRMED",
    "D": "NOT_SUPPORTED",
    "E": "NOT_TESTED_AND_NOT_CLAIMABLE",
}

HOLDOUT_FLAGS = [
    "holdout_market_data_loaded",
    "holdout_structural_data_inspected",
    "holdout_files_enumerated_for_content",
    "holdout_events_detected",
    "holdout_event_counts_computed",
    "holdout_controls_constructed",
    "holdout_outcomes_computed",
    "holdout_results_reported",
]

PROHIBITED_STRATEGY_METRICS = [
    "pnl",
    "equity curve",
    "sharpe",
    "sortino",
    "drawdown",
    "profit factor",
    "profit_factor",
]

REQUIRED_MANIFEST_GROUPS = [
    "preregistrations",
    "development_freeze",
    "validation_freeze",
    "event_detector",
    "event_configuration",
    "row_level_artifact_manifests",
    "matching_implementations",
    "inference_implementations",
    "placebo_implementations",
    "reconciliation_overlays",
    "compact_result_artifacts",
    "research_stop_record",
    "final_claim_matrix",
    "methods_and_results_reports",
]


def canonical_json_sha256(payload: Any) -> str:
    data = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def validate_gate_ledger(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(item["gate_id"]) for item in ledger]
    expected_positions = [
        ids.index(gate_id) if gate_id in ids else -1 for gate_id in REQUIRED_GATE_IDS
    ]
    complete = all(position >= 0 for position in expected_positions)
    ordered = expected_positions == sorted(expected_positions) and complete
    prereg_checks = []
    for item in ledger:
        prereg_sha = item.get("preregistration_sha")
        outcome_sha = item.get("ending_sha")
        if prereg_sha in (None, "N/A") or outcome_sha in (None, "N/A"):
            continue
        prereg_index = item.get("preregistration_commit_index")
        outcome_index = item.get("ending_commit_index")
        if isinstance(prereg_index, int) and isinstance(outcome_index, int):
            passed = prereg_index <= outcome_index
        else:
            passed = False
        prereg_checks.append(
            {
                "gate_id": item["gate_id"],
                "preregistration_sha": prereg_sha,
                "outcome_sha": outcome_sha,
                "passed": passed,
            }
        )
    return {
        "complete": complete,
        "ordered": ordered,
        "required_gate_ids": REQUIRED_GATE_IDS,
        "observed_gate_ids": ids,
        "preregistration_before_outcome": all(check["passed"] for check in prereg_checks),
        "preregistration_checks": prereg_checks,
        "status": "PASS"
        if complete and ordered and all(check["passed"] for check in prereg_checks)
        else "FAIL",
    }


def assert_close(
    name: str,
    observed: float,
    expected: float,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    difference = abs(float(observed) - float(expected))
    return {
        "name": name,
        "observed": observed,
        "expected": expected,
        "absolute_difference": difference,
        "tolerance": tolerance,
        "match": difference <= tolerance,
    }


def validate_claim_matrix(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {str(item["claim_id"]): str(item["status"]) for item in matrix}
    status_checks = {
        claim_id: statuses.get(claim_id) == expected
        for claim_id, expected in EXPECTED_CLAIM_STATUSES.items()
    }
    allowed_wording = " ".join(str(item.get("allowed_wording", "")) for item in matrix)
    prohibited_terms = find_prohibited_strategy_metrics(allowed_wording)
    return {
        "expected_statuses": EXPECTED_CLAIM_STATUSES,
        "observed_statuses": statuses,
        "status_checks": status_checks,
        "allowed_wording_prohibited_terms": prohibited_terms,
        "status": "PASS" if all(status_checks.values()) and not prohibited_terms else "FAIL",
    }


def find_prohibited_strategy_metrics(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in PROHIBITED_STRATEGY_METRICS if term in lowered]


def validate_manifest_completeness(manifest: dict[str, Any]) -> dict[str, Any]:
    groups = manifest.get("artifact_groups", {})
    missing_groups = [group for group in REQUIRED_MANIFEST_GROUPS if not groups.get(group)]
    entries_without_hash = []
    for group, entries in groups.items():
        if not isinstance(entries, list):
            entries_without_hash.append(f"{group}:not-a-list")
            continue
        for entry in entries:
            if not entry.get("sha256"):
                entries_without_hash.append(f"{group}:{entry.get('path', 'unknown')}")
    return {
        "required_groups": REQUIRED_MANIFEST_GROUPS,
        "missing_groups": missing_groups,
        "entries_without_hash": entries_without_hash,
        "status": "PASS" if not missing_groups and not entries_without_hash else "FAIL",
    }


def seal_payload_for_hash(seal: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in seal.items() if key != "lineage_seal_hash"}


def lineage_seal_hash(seal: dict[str, Any]) -> str:
    return canonical_json_sha256(seal_payload_for_hash(seal))


def validate_lineage_seal(seal: dict[str, Any]) -> dict[str, Any]:
    computed = lineage_seal_hash(seal)
    expected = seal.get("lineage_seal_hash")
    required_statements = [
        "No further outcome-informed Acceptance hypotheses may be tested against the preserved "
        "2023-2025 holdout.",
        "The holdout remains unopened and is not authorized for this closed hypothesis family.",
        "Any future Acceptance research must use a genuinely new external dataset, new prospective "
        "data collection, or an independently specified hypothesis before data access.",
    ]
    statements = seal.get("closure_statements", [])
    statement_checks = {statement: statement in statements for statement in required_statements}
    return {
        "seal_id": seal.get("seal_id"),
        "status_value": seal.get("status"),
        "computed_hash": computed,
        "recorded_hash": expected,
        "hash_matches": computed == expected,
        "statement_checks": statement_checks,
        "status": "PASS"
        if seal.get("seal_id") == SEAL_ID
        and seal.get("status") == SEAL_STATUS
        and computed == expected
        and all(statement_checks.values())
        else "FAIL",
    }


def validate_holdout_unauthorized(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {flag: bool(payload.get(flag, False)) for flag in HOLDOUT_FLAGS}
    violations = [flag for flag, value in checks.items() if value]
    return {
        "checks": checks,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def validate_no_acceptance_holdout_handoff(paths: list[str]) -> dict[str, Any]:
    blocked = [
        path
        for path in paths
        if "gate_c6" in path.lower()
        and "holdout" in path.lower()
        and "handoff" in path.lower()
    ]
    return {
        "blocked_paths": blocked,
        "status": "PASS" if not blocked else "FAIL",
    }
