from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.gate_c5arir import canonical_json_sha256, write_json  # noqa: E402


EXPECTED_BRANCH = "research/rigorous-intraday-smc-validation"
EXPECTED_START_SHA = "1b71ea4e17a24c51c6b7bc2f8271ac67fd0ae295"
EXPECTED_C5ARIR_DECISION = "C5AR_ARTIFACT_INTEGRITY_RECONCILED_READY_FOR_C5B"
EXPECTED_OVERLAY_ID = "C5AR_ARTIFACT_RECONCILIATION_V1"
EXPECTED_OVERLAY_HASH = (
    "64c00bb924b5f6db96a876ab476e53741da6377060150546df2a1b16ed10be06"
)
EXPECTED_HANDOFF_STATUS = "READY_TO_RESUME_C5B_PHASE_0"
EXPECTED_HANDOFF_HASH = (
    "05b11d2ce5b59ed66b556fc3596f733f93ffac0ca61a2d7f828f774ae6bad2ad"
)
EXPECTED_ADJUDICATION_RAW = (
    "af085060058dbfc3b25c6df6d84ab99898ef9002f19c733b5a5188f7496055b9"
)
EXPECTED_ADJUDICATION_CANONICAL = (
    "82533389578b20e026b9e7cf5bf26019275536329009eede5d83212fae167e7a"
)
EXPECTED_ORIGINAL_LOCK_RAW = (
    "114bb5f490be1bfcd8256ca4cb4e2882775f42536c48fb0248d8cd3a6b520db7"
)

RESULT_DIR = REPO / "results" / "gate_c5br"
DOC_DIR = REPO / "docs" / "research"

PHASE0_READ_PATHS = [
    "docs/research/GATE_C5ARIR_ARTIFACT_HISTORY.md",
    "docs/research/GATE_C5ARIR_SEMANTIC_DIFF.md",
    "docs/research/GATE_C5ARIR_LOCK_GENERATION_AUDIT.md",
    "docs/research/GATE_C5ARIR_RECONCILIATION_REPORT.md",
    "docs/research/GATE_C5ARIR_C5B_RESUMPTION_HANDOFF.md",
    "docs/research/GATE_C5ARIR_FINAL_DECISION_MEMO.md",
    "results/gate_c5arir/artifact_history.json",
    "results/gate_c5arir/expected_hash_provenance.json",
    "results/gate_c5arir/semantic_diff.json",
    "results/gate_c5arir/lock_generation_audit.json",
    "results/gate_c5arir/cross_artifact_identity_audit.json",
    "results/gate_c5arir/adjudication_reproduction.json",
    "results/gate_c5arir/authoritative_artifact_determination.json",
    "results/gate_c5arir/artifact_reconciliation_overlay.json",
    "results/gate_c5arir/c5b_resumption_handoff.json",
    "results/gate_c5arir/holdout_integrity.json",
    "results/gate_c5ar/post_validation_lock.json",
    "results/gate_c5ar/validation_criterion_adjudication.json",
    "results/gate_c5ar/validation_primary_estimand.json",
    "results/gate_c5ar/validation_inference.json",
    "results/gate_c5ar/validation_placebo.json",
    "results/gate_c5ar/validation_stability.json",
]

SOURCE_ARTIFACTS = [
    "results/gate_c5ar/post_validation_lock.json",
    "results/gate_c5ar/validation_criterion_adjudication.json",
    "results/gate_c5ar/validation_primary_estimand.json",
    "results/gate_c5ar/validation_inference.json",
    "results/gate_c5ar/validation_placebo.json",
    "results/gate_c5ar/validation_stability.json",
    "results/gate_c5ar/control_matching_audit.json",
    "results/gate_c5ar/holdout_integrity.json",
    "results/gate_c5ar/scientific_code_integrity.json",
    "results/gate_c5arir/artifact_reconciliation_overlay.json",
    "results/gate_c5arir/c5b_resumption_handoff.json",
]


def git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=REPO, check=check, capture_output=True)


def git_text(args: list[str], *, check: bool = True) -> str:
    return git(args, check=check).stdout.decode("utf-8", errors="replace").strip()


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_payload(path: str) -> dict[str, Any]:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def file_record(path: str) -> dict[str, Any]:
    full = REPO / path
    data = full.read_bytes()
    record: dict[str, Any] = {
        "path": path,
        "exists": full.exists(),
        "raw_file_sha256": hashlib.sha256(data).hexdigest(),
        "file_size_bytes": len(data),
    }
    if path.endswith(".json"):
        payload = json.loads(data.decode("utf-8"))
        record["canonical_json_sha256"] = canonical_json_sha256(payload)
    return record


def command_record(name: str, args: list[str]) -> dict[str, Any]:
    result = git(args, check=False)
    return {
        "name": name,
        "command": "git " + " ".join(args),
        "returncode": result.returncode,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
    }


def build_repository_state() -> dict[str, Any]:
    return {
        "gate": "C5-B-R",
        "expected_branch": EXPECTED_BRANCH,
        "actual_branch": git_text(["branch", "--show-current"]),
        "expected_starting_sha": EXPECTED_START_SHA,
        "actual_head": git_text(["rev-parse", "HEAD"]),
        "git_status": command_record("status", ["status"]),
        "git_log_oneline_decorate_35": git_text(
            ["log", "--oneline", "--decorate", "-35"]
        ).splitlines(),
        "git_diff": command_record("diff", ["diff"]),
        "git_diff_check": command_record("diff_check", ["diff", "--check"]),
        "phase0_paths_read": {path: file_record(path) for path in PHASE0_READ_PATHS},
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def build_reconciliation_integrity() -> dict[str, Any]:
    quality = json_payload("results/gate_c5arir/quality_gate_final.json")
    overlay = json_payload("results/gate_c5arir/artifact_reconciliation_overlay.json")
    handoff = json_payload("results/gate_c5arir/c5b_resumption_handoff.json")
    holdout = json_payload("results/gate_c5arir/holdout_integrity.json")
    checks = {
        "c5arir_final_decision": quality["final_decision"]
        == EXPECTED_C5ARIR_DECISION,
        "overlay_id": overlay["overlay_id"] == EXPECTED_OVERLAY_ID,
        "overlay_hash": overlay["reconciliation_overlay_hash"]
        == EXPECTED_OVERLAY_HASH,
        "handoff_status": handoff["status"] == EXPECTED_HANDOFF_STATUS,
        "handoff_hash": handoff["handoff_hash"] == EXPECTED_HANDOFF_HASH,
        "authoritative_current_artifact": overlay[
            "authoritative_artifact_designation"
        ]
        == "AUTHORITATIVE_CURRENT_ARTIFACT",
        "scientific_semantic_equality": overlay["scientific_semantic_equality"]
        is True,
        "holdout_access_false": holdout["status"] == "PASS"
        and not holdout["violations"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "overlay_hash": overlay["reconciliation_overlay_hash"],
        "handoff_hash": handoff["handoff_hash"],
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def build_c5ar_artifact_integrity() -> dict[str, Any]:
    lock = json_payload("results/gate_c5ar/post_validation_lock.json")
    adjudication = json_payload("results/gate_c5ar/validation_criterion_adjudication.json")
    overlay = json_payload("results/gate_c5arir/artifact_reconciliation_overlay.json")
    source_records = {path: file_record(path) for path in SOURCE_ARTIFACTS}
    checks = {
        "original_lock_preserved_raw_hash": source_records[
            "results/gate_c5ar/post_validation_lock.json"
        ]["raw_file_sha256"]
        == EXPECTED_ORIGINAL_LOCK_RAW,
        "authoritative_adjudication_raw_hash": source_records[
            "results/gate_c5ar/validation_criterion_adjudication.json"
        ]["raw_file_sha256"]
        == EXPECTED_ADJUDICATION_RAW,
        "authoritative_adjudication_canonical_hash": source_records[
            "results/gate_c5ar/validation_criterion_adjudication.json"
        ]["canonical_json_sha256"]
        == EXPECTED_ADJUDICATION_CANONICAL,
        "original_lock_final_decision_preserved": lock["final_decision"]
        == "USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_NOT_VALIDATED",
        "adjudication_final_decision_preserved": adjudication["final_decision"]
        == "USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_NOT_VALIDATED",
        "overlay_supersedes_only_adjudication_hash": overlay[
            "erroneous_lock_reference_superseded_only_for"
        ]
        == "results/gate_c5ar/validation_criterion_adjudication.json",
        "scientific_code_hash_present": "scientific_code" in lock["hashes"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "source_artifact_hashes": source_records,
        "scientific_code_hash": lock["hashes"]["scientific_code"],
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def build_preregistration(
    reconciliation_integrity: dict[str, Any],
    c5ar_artifact_integrity: dict[str, Any],
) -> dict[str, Any]:
    source_hashes = c5ar_artifact_integrity["source_artifact_hashes"]
    preregistration = {
        "gate": "C5-B-R",
        "hypothesis_class_under_audit": "DUAL_POSITIVE_ACCEPTANCE_RESPONSE",
        "candidate_status": "validation-informed exploratory; not confirmed",
        "source_artifact_paths_and_hashes": source_hashes,
        "development_sample": {
            "pair": "USDJPY",
            "period": "2015-01-01 through 2019-12-31",
            "source": "frozen development row-level event/control artifacts only",
        },
        "validation_sample": {
            "pair": "USDJPY",
            "period": "2020-01-01 through 2022-12-31",
            "source": "frozen C5-A-R row-level artifacts only",
        },
        "diagnostic_questions": [
            "Does validation show positive absolute executable event markout?",
            "Does validation preserve positive exact-matched-control differential?",
            "Is the transition transportable under fixed common protocol?",
            "Is the positive absolute validation response stable and not cost-only?",
        ],
        "fixed_composition_strata": [
            "direction",
            "session",
            "event subtype",
            "volatility regime",
            "spread regime",
            "pre-event trend regime",
            "range-position regime",
            "overlap status",
        ],
        "transport_standardization_method": {
            "method": "stabilized propensity-density weighting",
            "covariates": [
                "spread",
                "ATR",
                "pre-event volatility",
                "pre-event trend",
                "range position",
                "session",
                "direction",
            ],
        },
        "weight_stability_rules": {
            "effective_sample_size_min_fraction": 0.5,
            "max_normalized_weight_max_median_multiple": 10,
            "every_standardized_abs_smd_max": 0.10,
        },
        "temporal_stability_rules": [
            "relative differential positive across most development years",
            "relative differential positive in 2020, 2021 and 2022",
            "validation absolute event markout positive in at least two of three years",
            "leave-one-validation-year-out absolute markout remains positive",
            "leave-one-validation-year-out differential remains positive",
            "no validation year contributes more than 60% of total weighted absolute effect",
        ],
        "matching_geometry_rules": {
            "controls_per_event": 1,
            "replacement": True,
            "seed": 4242,
            "exact_keys": ["year", "month", "session", "direction"],
            "key_relaxation": "forbidden",
            "post_match_abs_smd_max": 0.10,
            "minimum_matched_events": 40,
        },
        "candidate_eligibility_criteria": [
            "C5-A-R artifact and reconciliation integrity pass",
            "development and validation reproduction pass",
            "cross-period semantic comparability passes",
            "validation absolute event executable markout > 0",
            "validation event-minus-control executable differential > 0",
            "validation absolute-effect inference passes",
            "validation relative-differential inference passes",
            "validation placebo does not reproduce either co-primary effect",
            "relative differential positive in 2020, 2021 and 2022",
            "validation absolute positivity in at least two of three years",
            "leave-one-validation-year-out absolute markout remains positive",
            "leave-one-validation-year-out differential remains positive",
            "positive absolute effect is not explained solely by transaction costs",
            "valid transport standardization preserves both co-primary signs",
            "no subgroup selection is required",
            "matching support and balance pass in both periods",
            "holdout remains completely unopened",
        ],
        "one_candidate_only_rule": "Exactly DUAL_POSITIVE_ACCEPTANCE_RESPONSE is allowed.",
        "research_stop_conditions": [
            "Any required candidate criterion fails",
            "Reconciliation integrity fails",
            "Mechanism reproduction fails",
            "Cross-period comparability has material risk",
            "Holdout integrity fails",
        ],
        "holdout_prohibition": {
            "holdout_period": "2023-01-01 through 2025-12-31",
            "access_allowed": False,
            "prohibited": [
                "market data loading",
                "structural inspection",
                "event counting",
                "control construction",
                "outcome computation",
                "result reporting",
            ],
        },
        "final_decision_options": [
            "ACCEPTANCE_DUAL_POSITIVE_HYPOTHESIS_FROZEN_FOR_HOLDOUT",
            "VALIDATION_SIGNAL_NONTRANSPORTABLE_RESEARCH_STOP",
            "BLOCKED_BY_C5AR_RECONCILIATION_INTEGRITY",
            "BLOCKED_BY_C5AR_ARTIFACT_INTEGRITY",
            "BLOCKED_BY_MECHANISM_PREREGISTRATION",
            "BLOCKED_BY_MECHANISM_REPRODUCIBILITY",
            "BLOCKED_BY_CROSS_PERIOD_COMPARABILITY",
            "BLOCKED_BY_TRANSPORTABILITY",
            "BLOCKED_BY_HYPOTHESIS_FREEZE_INTEGRITY",
            "BLOCKED_BY_HOLDOUT_INTEGRITY",
        ],
        "required_statements": [
            "C5-B diagnostics are validation-informed and exploratory.",
            "They cannot confirm the new mechanism.",
            "The untouched holdout is reserved as the sole confirmatory sample.",
        ],
        "inputs_passed_before_preregistration": {
            "reconciliation_integrity": reconciliation_integrity["status"],
            "c5ar_artifact_integrity": c5ar_artifact_integrity["status"],
        },
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    preregistration["preregistration_hash"] = canonical_json_sha256(preregistration)
    return preregistration


def write_prereg_doc(preregistration: dict[str, Any]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    (DOC_DIR / "GATE_C5BR_MECHANISM_TRANSITION_PREREGISTRATION.md").write_text(
        "# Gate C5-B-R Mechanism Transition Preregistration\n\n"
        f"Preregistration hash: `{preregistration['preregistration_hash']}`\n\n"
        "C5-B diagnostics are validation-informed and exploratory.\n\n"
        "They cannot confirm the new mechanism.\n\n"
        "The untouched holdout is reserved as the sole confirmatory sample.\n\n"
        "Exactly one candidate class is frozen for audit: "
        "`DUAL_POSITIVE_ACCEPTANCE_RESPONSE`.\n",
        encoding="utf-8",
    )


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    repository_state = build_repository_state()
    reconciliation_integrity = build_reconciliation_integrity()
    c5ar_artifact_integrity = build_c5ar_artifact_integrity()
    preregistration = build_preregistration(
        reconciliation_integrity,
        c5ar_artifact_integrity,
    )
    write_json(RESULT_DIR / "repository_state.json", repository_state)
    write_json(RESULT_DIR / "reconciliation_integrity.json", reconciliation_integrity)
    write_json(RESULT_DIR / "c5ar_artifact_integrity.json", c5ar_artifact_integrity)
    write_json(
        RESULT_DIR / "mechanism_transition_preregistration.json",
        preregistration,
    )
    write_prereg_doc(preregistration)
    return 0 if (
        reconciliation_integrity["status"] == "PASS"
        and c5ar_artifact_integrity["status"] == "PASS"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
