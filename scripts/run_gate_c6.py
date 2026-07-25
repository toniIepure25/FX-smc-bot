from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.gate_c5br import (  # noqa: E402
    add_transport_bins,
    exact_cell_weights,
    normalized_weight_diagnostics,
    primary_development,
    primary_validation,
)
from fx_smc_bot.research.gate_c6 import (  # noqa: E402
    FINAL_DECISION,
    HOLDOUT_FLAGS,
    SEAL_ID,
    SEAL_STATUS,
    assert_close,
    canonical_json_sha256,
    find_prohibited_strategy_metrics,
    lineage_seal_hash,
    load_json,
    raw_sha256,
    validate_claim_matrix,
    validate_gate_ledger,
    validate_holdout_unauthorized,
    validate_lineage_seal,
    validate_manifest_completeness,
    validate_no_acceptance_holdout_handoff,
    write_json,
)

RESULT_DIR = REPO / "results" / "gate_c6"
DOC_DIR = REPO / "docs" / "research"
EXPECTED_HEAD = "c3a872db6bbdd44f53291824c3c5da9fe5cb4592"
EXPECTED_BRANCH = "research/rigorous-intraday-smc-validation"


def run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def artifact(path: str) -> dict[str, Any]:
    absolute = REPO / path
    payload: dict[str, Any] = {
        "path": path,
        "exists": absolute.exists(),
        "sha256": raw_sha256(absolute) if absolute.exists() else None,
        "size_bytes": absolute.stat().st_size if absolute.exists() else None,
    }
    if absolute.suffix == ".json" and absolute.exists():
        payload["canonical_json_sha256"] = canonical_json_sha256(load_json(absolute))
    return payload


def build_repository_state() -> dict[str, Any]:
    status = run_git(["status", "--short", "--branch"])
    full_status = run_git(["status"])
    branch = run_git(["branch", "--show-current"]).strip()
    head = run_git(["rev-parse", "HEAD"]).strip()
    log = run_git(["log", "--oneline", "--decorate", "-60"])
    diff = run_git(["diff"])
    diff_check = run_git(["diff", "--check"])
    return {
        "gate": "C6",
        "expected_branch": EXPECTED_BRANCH,
        "actual_branch": branch,
        "expected_starting_sha": EXPECTED_HEAD,
        "actual_starting_sha": head,
        "branch_matches": branch == EXPECTED_BRANCH,
        "starting_sha_matches": head == EXPECTED_HEAD,
        "status_short": status,
        "status_full": full_status,
        "working_tree_clean": "nothing to commit, working tree clean" in full_status,
        "dirty_paths": dirty_paths_from_status(status),
        "git_log_oneline_decorate_60": log.splitlines(),
        "git_diff": diff,
        "git_diff_check": diff_check,
        "diff_check_pass": diff_check.strip() == "",
        "created_at_utc": now_utc(),
    }


def dirty_paths_from_status(status_short: str) -> list[str]:
    paths = []
    for line in status_short.splitlines():
        if not line or line.startswith("## "):
            continue
        paths.append(line[3:].replace("\\", "/"))
    return paths


def is_gate_c6_path(path: str) -> bool:
    return (
        path == "scripts/run_gate_c6.py"
        or path == "src/fx_smc_bot/research/gate_c6.py"
        or path.startswith("tests/test_gate_c6/")
        or path.startswith("docs/research/ACCEPTANCE_")
        or path.startswith("docs/research/GATE_C6_")
        or path.startswith("results/gate_c6/")
    )


def commit_index_by_prefix(log_lines: list[str]) -> dict[str, int]:
    return {line.split()[0]: index for index, line in enumerate(reversed(log_lines))}


def build_ledger(log_lines: list[str]) -> list[dict[str, Any]]:
    index = commit_index_by_prefix(log_lines)

    def idx(prefix: str) -> int:
        return index.get(prefix, -1)

    return [
        {
            "gate_id": "C3FV",
            "purpose": "Recovered tick-audit data certification plan and blocked first freeze.",
            "starting_sha": "9490bab",
            "ending_sha": "1eae93f",
            "preregistration_sha": "1eae93f",
            "preregistration_commit_index": idx("1eae93f"),
            "ending_commit_index": idx("1eae93f"),
            "data_interval": "development recovery lineage",
            "data_status": "blocked certification preserved",
            "hypothesis_status": "no Acceptance hypothesis tested",
            "primary_estimand": "data certification only",
            "result": "frozen recovered tick audit plan",
            "decision": "blocked gate preserved as lineage evidence",
            "blocking_reason": "earlier artifact/data ambiguity",
            "artifact_directory": "results/gate_c3fv",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation and holdout unopened",
        },
        {
            "gate_id": "C3F-TPR",
            "purpose": "Prospective tick-to-M1 protocol and deterministic audit.",
            "starting_sha": "6aa275e",
            "ending_sha": "10ccb2b",
            "preregistration_sha": "6aa275e",
            "preregistration_commit_index": idx("6aa275e"),
            "ending_commit_index": idx("10ccb2b"),
            "data_interval": "2015-2019 development",
            "data_status": "certified deterministic tick-to-M1 audit",
            "hypothesis_status": "no Acceptance hypothesis tested",
            "primary_estimand": "data certification only",
            "result": "development dataset certified",
            "decision": "ready for pair-scoped freeze",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c3ftpr",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation and holdout unopened",
        },
        {
            "gate_id": "C3F-CRSF",
            "purpose": "Pair-scoped USDJPY development freeze.",
            "starting_sha": "f988510",
            "ending_sha": "8fb676d",
            "preregistration_sha": "f988510",
            "preregistration_commit_index": idx("f988510"),
            "ending_commit_index": idx("8fb676d"),
            "data_interval": "USDJPY 2015-2019 development",
            "data_status": "pair-scoped freeze certified",
            "hypothesis_status": "development data frozen before C4 study",
            "primary_estimand": "data freeze only",
            "result": "USDJPY-only CRSF development freeze",
            "decision": "ready for C4 preregistration",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c3fcrsf",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation and holdout unopened",
        },
        {
            "gate_id": "C4",
            "purpose": "Preregister and execute USDJPY development event-alpha study.",
            "starting_sha": "2089ff1",
            "ending_sha": "df5d446",
            "preregistration_sha": "2089ff1",
            "preregistration_commit_index": idx("2089ff1"),
            "ending_commit_index": idx("df5d446"),
            "data_interval": "USDJPY 2015-2019 development",
            "data_status": "frozen development only",
            "hypothesis_status": "development event family assessed",
            "primary_estimand": "event-minus-control executable markout",
            "result": "development differential positive",
            "decision": "advanced to C4-A audit",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c4",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation and holdout unopened",
        },
        {
            "gate_id": "C4-A",
            "purpose": "Audit C4 preregistration compliance and adjudicate signal.",
            "starting_sha": "467e44f",
            "ending_sha": "d9a9e51",
            "preregistration_sha": "2089ff1",
            "preregistration_commit_index": idx("2089ff1"),
            "ending_commit_index": idx("d9a9e51"),
            "data_interval": "USDJPY 2015-2019 development",
            "data_status": "development only",
            "hypothesis_status": "C4 signal adjudicated",
            "primary_estimand": "family decision logic",
            "result": "USDJPY Acceptance signal selected for mechanism audit",
            "decision": "ready for C4-B mechanism decomposition",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c4a",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation and holdout unopened",
        },
        {
            "gate_id": "C4-B",
            "purpose": "Mechanism redesign and Acceptance relative-resilience hypothesis freeze.",
            "starting_sha": "d420c3a",
            "ending_sha": "e39faa5",
            "preregistration_sha": "d420c3a",
            "preregistration_commit_index": idx("d420c3a"),
            "ending_commit_index": idx("e39faa5"),
            "data_interval": "USDJPY 2015-2019 development",
            "data_status": "development only",
            "hypothesis_status": "new Acceptance relative-resilience hypothesis frozen",
            "primary_estimand": "absolute and relative executable markout decomposition",
            "result": "relative positive, absolute event markout negative",
            "decision": "validation handoff prepared without holdout access",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c4b",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation untouched; holdout unopened",
        },
        {
            "gate_id": "C5",
            "purpose": "Initial validation handoff ambiguity block.",
            "starting_sha": "771ac92",
            "ending_sha": "771ac92",
            "preregistration_sha": "N/A",
            "preregistration_commit_index": None,
            "ending_commit_index": idx("771ac92"),
            "data_interval": "no validation outcome access",
            "data_status": "blocked before validation execution",
            "hypothesis_status": "Acceptance validation blocked",
            "primary_estimand": "validation authorization only",
            "result": "handoff ambiguity detected",
            "decision": "blocked gate preserved",
            "blocking_reason": "handoff ambiguity",
            "artifact_directory": "results/gate_c5",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation not executed; holdout unopened",
        },
        {
            "gate_id": "C5-A",
            "purpose": "Prospective handoff amendment and pre-unblinding freeze.",
            "starting_sha": "bd6d4d6",
            "ending_sha": "78177a7",
            "preregistration_sha": "bd6d4d6",
            "preregistration_commit_index": idx("bd6d4d6"),
            "ending_commit_index": idx("78177a7"),
            "data_interval": "validation 2020-2022 authorized, not yet adjudicated",
            "data_status": "protocol frozen pre-unblinding",
            "hypothesis_status": "C4-B Acceptance hypothesis remains frozen",
            "primary_estimand": "amended validation execution protocol",
            "result": "ready for validation acquisition",
            "decision": "proceed to validation data certification",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c5a",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation authorized; holdout unopened",
        },
        {
            "gate_id": "C5-A-DQB",
            "purpose": "Validation data-quality block after initial acquisition.",
            "starting_sha": "59084c4",
            "ending_sha": "edd2de7",
            "preregistration_sha": "78177a7",
            "preregistration_commit_index": idx("78177a7"),
            "ending_commit_index": idx("edd2de7"),
            "data_interval": "USDJPY 2020-2022 validation",
            "data_status": "blocked by zero-row certification bug",
            "hypothesis_status": "validation outcome not accepted under bad data quality",
            "primary_estimand": "data-quality remediation",
            "result": "zero-row certification vulnerability fixed",
            "decision": "blocked pending provider fallback",
            "blocking_reason": "provider/data-quality failure",
            "artifact_directory": "results/gate_c5a",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation data quality blocked; holdout unopened",
        },
        {
            "gate_id": "C5-A-DQR",
            "purpose": "Provider fallback and validation freeze remediation.",
            "starting_sha": "9845c75",
            "ending_sha": "a8b8d4b",
            "preregistration_sha": "9845c75",
            "preregistration_commit_index": idx("9845c75"),
            "ending_commit_index": idx("a8b8d4b"),
            "data_interval": "USDJPY 2020-2022 validation",
            "data_status": "Dukascopy validation dataset recertified",
            "hypothesis_status": "C4-B Acceptance hypothesis remains frozen",
            "primary_estimand": "data certification only",
            "result": "validation dataset certified",
            "decision": "ready for frozen validation execution",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c5adqr",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation authorized; holdout unopened",
        },
        {
            "gate_id": "C5-A-R",
            "purpose": "Frozen validation execution and adjudication.",
            "starting_sha": "4cd388b",
            "ending_sha": "92e992d",
            "preregistration_sha": "0d054c2",
            "preregistration_commit_index": idx("0d054c2"),
            "ending_commit_index": idx("92e992d"),
            "data_interval": "USDJPY 2020-2022 validation",
            "data_status": "validation executed; holdout preserved",
            "hypothesis_status": "C4-B relative-resilience hypothesis not validated",
            "primary_estimand": "validation event-minus-control executable markout",
            "result": "relative effect positive but original C4-B rule not validated",
            "decision": "USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_NOT_VALIDATED",
            "blocking_reason": "confirmatory criterion failed under adjudication",
            "artifact_directory": "results/gate_c5ar",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation used; holdout unopened",
        },
        {
            "gate_id": "C5-A-R-IR",
            "purpose": "Artifact integrity reconciliation after lock mismatch.",
            "starting_sha": "abd879c",
            "ending_sha": "1b71ea4",
            "preregistration_sha": "abd879c",
            "preregistration_commit_index": idx("abd879c"),
            "ending_commit_index": idx("1b71ea4"),
            "data_interval": "compact validation artifacts only",
            "data_status": "integrity reconciled",
            "hypothesis_status": "no scientific result changed",
            "primary_estimand": "artifact provenance and semantic equality",
            "result": "overlay and C5-B resumption handoff created",
            "decision": "C5AR_ARTIFACT_INTEGRITY_RECONCILED_READY_FOR_C5B",
            "blocking_reason": None,
            "artifact_directory": "results/gate_c5arir",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation artifacts used; holdout unopened",
        },
        {
            "gate_id": "C5-B-R",
            "purpose": "Reconciled development-validation mechanism and transport audit.",
            "starting_sha": "61aa358",
            "ending_sha": "c3a872d",
            "preregistration_sha": "61aa358",
            "preregistration_commit_index": idx("61aa358"),
            "ending_commit_index": idx("c3a872d"),
            "data_interval": "development 2015-2019 and validation 2020-2022",
            "data_status": "compact artifacts plus frozen development/validation rows",
            "hypothesis_status": "dual-positive candidate rejected before holdout",
            "primary_estimand": "absolute event markout and relative event-minus-control",
            "result": "15/17 criteria passed; absolute inference and transport failed",
            "decision": "VALIDATION_SIGNAL_NONTRANSPORTABLE_RESEARCH_STOP",
            "blocking_reason": "nontransportable dual-positive response",
            "artifact_directory": "results/gate_c5br",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation used; holdout unopened",
        },
        {
            "gate_id": "C6",
            "purpose": "Acceptance research-program closure and publication package.",
            "starting_sha": EXPECTED_HEAD,
            "ending_sha": "generated-by-this-gate",
            "preregistration_sha": "N/A",
            "preregistration_commit_index": None,
            "ending_commit_index": None,
            "data_interval": "compact committed artifacts only",
            "data_status": "no new outcomes generated",
            "hypothesis_status": "Acceptance hypothesis family closed",
            "primary_estimand": "lineage, reproducibility, inference, transport, claims",
            "result": FINAL_DECISION,
            "decision": FINAL_DECISION,
            "blocking_reason": None,
            "artifact_directory": "results/gate_c6",
            "document_directory": "docs/research",
            "validation_holdout_access_status": "validation summarized; holdout unopened",
        },
    ]


def build_lineage_integrity(
    repository_state: dict[str, Any],
    ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    log_text = "\n".join(repository_state["git_log_oneline_decorate_60"])
    expected_commits = [
        "1eae93f",
        "6aa275e",
        "9a66239",
        "6c8312b",
        "10ccb2b",
        "f988510",
        "8fb676d",
        "2089ff1",
        "df5d446",
        "467e44f",
        "deee74a",
        "5bfba55",
        "d9a9e51",
        "d420c3a",
        "865ba3b",
        "8e89f82",
        "624561f",
        "e39faa5",
        "771ac92",
        "bd6d4d6",
        "0d054c2",
        "78177a7",
        "59084c4",
        "c11bd40",
        "92e992d",
        "edd2de7",
        "9845c75",
        "a8b8d4b",
        "4cd388b",
        "abd879c",
        "1f59fb2",
        "ee4f433",
        "d0cb3d6",
        "fc7a704",
        "1b71ea4",
        "61aa358",
        "0f585dd",
        "a5cc01c",
        "08fcff2",
        "c3a872d",
    ]
    missing = [commit for commit in expected_commits if commit not in log_text]
    reconciliation = load_json(REPO / "results/gate_c5br/reconciliation_integrity.json")
    c5ar_integrity = load_json(REPO / "results/gate_c5br/c5ar_artifact_integrity.json")
    c5br_stop = load_json(REPO / "results/gate_c5br/research_stop_record.json")
    holdout = load_json(REPO / "results/gate_c5br/holdout_integrity.json")
    ledger_validation = validate_gate_ledger(ledger)
    checks = {
        "working_tree_clean_at_gate_start": repository_state["starting_sha_matches"]
        and all(is_gate_c6_path(path) for path in repository_state["dirty_paths"]),
        "no_non_c6_worktree_changes": all(
            is_gate_c6_path(path) for path in repository_state["dirty_paths"]
        ),
        "expected_commits_present": not missing,
        "preregistration_before_outcome": ledger_validation["preregistration_before_outcome"],
        "all_research_stop_decisions_preserved": c5br_stop["status"] == "RESEARCH_STOP",
        "all_reconciliation_overlays_valid": reconciliation["status"] == "PASS"
        and c5ar_integrity["status"] == "PASS",
        "holdout_unopened": holdout["status"] == "PASS",
        "ledger_complete": ledger_validation["status"] == "PASS",
    }
    return {
        "checks": checks,
        "missing_expected_commits": missing,
        "ledger_validation": ledger_validation,
        "reconciliation_overlay": {
            "overlay_id": "C5AR_ARTIFACT_RECONCILIATION_V1",
            "overlay_hash": reconciliation["overlay_hash"],
            "handoff_hash": reconciliation["handoff_hash"],
        },
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_final_reproduction() -> dict[str, Any]:
    dev = load_json(REPO / "results/gate_c5br/common_protocol_development_analysis.json")
    repro = load_json(REPO / "results/gate_c5br/development_validation_reproduction.json")
    transport = load_json(REPO / "results/gate_c5br/transport_standardization.json")
    trace = load_json(REPO / "results/gate_c5br/candidate_eligibility_trace.json")
    val_summary = repro["validation_reproduction"]["computed_from_frozen_rows"]
    val_abs = trace["criteria"][5]["observed"]
    comparisons = [
        assert_close("development_event_markout", dev["event_markout"], -3.66885245901655),
        assert_close("development_control_markout", dev["control_markout"], -17.33688524590164),
        assert_close("development_differential", dev["differential"], 13.668032786885094),
        assert_close("development_permutation_p", dev["permutation_p"], 0.006496751624187906),
        assert_close("development_ci_lower", dev["bootstrap_ci"][0], 6.277491118674749),
        assert_close("development_ci_upper", dev["bootstrap_ci"][1], 21.844720075312043),
        assert_close(
            "validation_event_markout",
            val_summary["mean_event_executable_markout_points"],
            11.33724832214778,
        ),
        assert_close(
            "validation_control_markout",
            val_summary["mean_control_executable_markout_points"],
            -16.11577181208039,
        ),
        assert_close(
            "validation_differential",
            val_summary["mean_event_minus_control_points"],
            27.453020134228165,
        ),
        assert_close(
            "validation_relative_permutation_p",
            repro["validation_reproduction"]["comparisons"][4]["reproduced_value"],
            0.004497751124437781,
        ),
        assert_close(
            "validation_relative_ci_lower",
            repro["validation_reproduction"]["comparisons"][5]["reproduced_value"],
            14.784214406740844,
        ),
        assert_close(
            "validation_relative_ci_upper",
            repro["validation_reproduction"]["comparisons"][6]["reproduced_value"],
            40.27386831699497,
        ),
        assert_close(
            "validation_absolute_sign_flip_p",
            val_abs["sign_flip_permutation_p_value"],
            0.12843578210894552,
        ),
        assert_close(
            "validation_absolute_ci_lower",
            val_abs["ci95_day_cluster_bootstrap"][0],
            0.7861459649301382,
        ),
        assert_close(
            "transport_standardized_validation_event",
            transport["results"]["validation_standardized_to_development"]["standardized"]["event"],
            12.26554243296961,
        ),
        assert_close(
            "transport_standardized_validation_differential",
            transport["results"]["validation_standardized_to_development"]["standardized"]["differential"],
            35.53894763198631,
        ),
        assert_close(
            "transport_max_weight_median_multiple",
            transport["results"]["validation_standardized_to_development"]["weight_diagnostics"][
                "max_weight_median_multiple"
            ],
            10.4,
        ),
    ]
    return {
        "status": "PASS" if all(item["match"] for item in comparisons) else "FAIL",
        "comparisons": comparisons,
        "development": {
            "event_markout": dev["event_markout"],
            "control_markout": dev["control_markout"],
            "differential": dev["differential"],
            "permutation_p": dev["permutation_p"],
            "ci95": dev["bootstrap_ci"],
        },
        "validation": {
            "matched_events": val_summary["n"],
            "event_markout": val_summary["mean_event_executable_markout_points"],
            "control_markout": val_summary["mean_control_executable_markout_points"],
            "differential": val_summary["mean_event_minus_control_points"],
            "relative_permutation_p": repro["validation_reproduction"]["comparisons"][4][
                "reproduced_value"
            ],
            "relative_ci95": [
                repro["validation_reproduction"]["comparisons"][5]["reproduced_value"],
                repro["validation_reproduction"]["comparisons"][6]["reproduced_value"],
            ],
            "absolute_sign_flip_p": val_abs["sign_flip_permutation_p_value"],
            "absolute_ci95": val_abs["ci95_day_cluster_bootstrap"],
        },
        "transport": {
            "standardized_validation_event": transport["results"][
                "validation_standardized_to_development"
            ]["standardized"]["event"],
            "standardized_validation_differential": transport["results"][
                "validation_standardized_to_development"
            ]["standardized"]["differential"],
            "maximum_weight_median_multiple": transport["results"][
                "validation_standardized_to_development"
            ]["weight_diagnostics"]["max_weight_median_multiple"],
        },
        "created_at_utc": now_utc(),
    }


def validation_day_distribution() -> dict[str, Any]:
    events = pd.read_parquet(REPO / "data/raw/gate_c5ar/validation_acceptance_events.parquet")
    primary = primary_validation(events)
    by_day = primary.groupby("utc_date", observed=False).size().to_numpy()
    values = primary["primary_executable_markout_points"].to_numpy(float)
    return {
        "matched_event_count": int(len(primary)),
        "independent_day_count": int(primary["utc_date"].nunique()),
        "events_per_day": {
            "min": int(np.min(by_day)),
            "median": float(np.median(by_day)),
            "mean": float(np.mean(by_day)),
            "p95": float(np.quantile(by_day, 0.95)),
            "max": int(np.max(by_day)),
        },
        "absolute_markout_distribution": {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "p05": float(np.quantile(values, 0.05)),
            "p95": float(np.quantile(values, 0.95)),
            "minimum": float(np.min(values)),
            "maximum": float(np.max(values)),
            "positive_fraction": float(np.mean(values > 0)),
        },
    }


def build_inference_audit(reproduction: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "not_software_contradiction": True,
        "potential_inferential_method_sensitivity": True,
        "preregistered_decision_rule_remains_authoritative": True,
        "validation_absolute_effect": {
            "mean": reproduction["validation"]["event_markout"],
            "bootstrap_ci_lower": reproduction["validation"]["absolute_ci95"][0],
            "bootstrap_ci_upper": reproduction["validation"]["absolute_ci95"][1],
            "sign_flip_permutation_p": reproduction["validation"]["absolute_sign_flip_p"],
            "formal_pass": False,
        },
        "procedure_comparison": {
            "day_cluster_bootstrap": {
                "null_or_target": "uncertainty interval for the mean under day-resampled clusters",
                "resampling_unit": "utc day",
                "day_weighting": (
                    "days are sampled as clusters; event counts per sampled day carry through"
                ),
                "sensitivity": (
                    "can give a positive interval when day-level means are mostly positive"
                ),
            },
            "sign_flip_permutation": {
                "null_or_target": "symmetry or exchangeability of signs around zero",
                "resampling_unit": "event signs with fixed magnitudes in the frozen implementation",
                "monte_carlo_iterations": 2000,
                "seed": 4242,
                "sensitivity": "skew, heavy tails, and within-day dependence can raise p-values",
            },
        },
        "permitted_diagnostics": validation_day_distribution(),
        "adjudication": (
            "The positive mean and bootstrap lower bound are descriptive evidence. "
            "The preregistered intersection rule also required sign-flip p <= 0.05, "
            "so the absolute-effect criterion remains failed."
        ),
        "created_at_utc": now_utc(),
    }


def build_transport_audit() -> dict[str, Any]:
    dev_events_all = pd.read_parquet(REPO / "data/raw/gate_c4/usdjpy_event_table.parquet")
    dev_controls_all = pd.read_parquet(REPO / "data/raw/gate_c4/usdjpy_control_matches.parquet")
    val_events_all = pd.read_parquet(
        REPO / "data/raw/gate_c5ar/validation_acceptance_events.parquet"
    )
    val_controls = pd.read_parquet(REPO / "data/raw/gate_c5ar/validation_control_matches.parquet")
    dev_events = primary_development(dev_events_all)
    dev_controls = dev_controls_all[dev_controls_all["event_id"].isin(dev_events["event_id"])]
    val_events = primary_validation(val_events_all)
    merged = {
        "development": add_transport_bins(dev_events).merge(
            dev_controls,
            on="event_id",
            suffixes=("", "_control"),
        ),
        "validation": add_transport_bins(val_events).merge(
            val_controls,
            on="event_id",
            suffixes=("", "_control"),
        ),
    }
    cols = [
        "spread_bin",
        "atr_bin",
        "volatility_bin",
        "trend_bin",
        "range_position_bin",
        "session",
        "direction",
    ]
    weights = exact_cell_weights(merged["validation"], merged["development"], cols)
    max_index = int(np.argmax(weights))
    max_row = merged["validation"].iloc[max_index]
    source_keys = merged["validation"][cols].astype(str).agg("|".join, axis=1)
    target_keys = merged["development"][cols].astype(str).agg("|".join, axis=1)
    max_key = str(source_keys.iloc[max_index])
    source_count = int((source_keys == max_key).sum())
    target_count = int((target_keys == max_key).sum())
    balance = load_json(REPO / "results/gate_c5br/matching_geometry_drift.json")
    c5_transport = load_json(REPO / "results/gate_c5br/transport_standardization.json")
    diagnostics = normalized_weight_diagnostics(weights)
    return {
        "status": "PASS",
        "formal_result": "FAIL",
        "threshold": 10.0,
        "maximum_weight_median_multiple": diagnostics["max_weight_median_multiple"],
        "close_to_threshold": diagnostics["max_weight_median_multiple"] - 10.0 < 0.5,
        "maximum_weight_observation": {
            "event_id": str(max_row["event_id"]),
            "source_period": "validation 2020-2022",
            "confirmation_timestamp": str(max_row["confirmation_timestamp"]),
            "earliest_entry_timestamp": str(max_row["earliest_entry_timestamp"]),
            "year": int(max_row["year"]),
            "month": int(max_row["month"]),
            "session": str(max_row["session"]),
            "direction": str(max_row["direction"]),
            "pre_event_covariates": {
                "spread": float(max_row["spread"]),
                "atr": float(max_row["atr"]),
                "pre_event_volatility": float(max_row["pre_event_volatility"]),
                "pre_event_trend": float(max_row["pre_event_trend"]),
                "range_position": float(max_row["range_position"]),
            },
            "transport_cell": {column: str(max_row[column]) for column in cols},
            "cell_key": max_key,
            "source_cell_count": source_count,
            "target_cell_count": target_count,
            "source_cell_proportion": source_count / len(source_keys),
            "target_cell_proportion": target_count / len(target_keys),
            "weight": float(weights[max_index]),
        },
        "weight_diagnostics": {
            "effective_sample_size": diagnostics["effective_sample_size"],
            "maximum_weight": diagnostics["maximum_weight"],
            "p95_weight": float(np.quantile(weights, 0.95)),
            "p99_weight": diagnostics["p99_weight"],
            "weight_coefficient_of_variation": diagnostics["weight_coefficient_of_variation"],
        },
        "balance_before_after_weighting": {
            "development": balance["development"]["post_match_smds"],
            "validation": balance["validation"]["post_match_smds"],
            "requirements": balance["requirements"],
        },
        "failure_scope": {
            "local_or_widespread": "local threshold breach with broader tail weight instability",
            "weights_above_median_times_10": int(
                np.sum(weights > float(np.median(weights)) * 10.0)
            ),
            "weights_above_p95": int(np.sum(weights > np.quantile(weights, 0.95))),
            "total_weighted_observations": int(len(weights)),
        },
        "c5br_transport_source": c5_transport["results"]["validation_standardized_to_development"],
        "no_trimming_capping_removal_or_threshold_change": True,
        "created_at_utc": now_utc(),
    }


def build_claim_matrix() -> list[dict[str, Any]]:
    return [
        {
            "claim_id": "A",
            "claim": "Acceptance events outperformed exact matched controls during 2015-2019.",
            "evidence": "Common-protocol development differential +13.668032786885094 points, "
            "permutation p=0.006496751624187906, CI [6.277491118674749, "
            "21.844720075312043].",
            "counterevidence": "Absolute event markout was negative at -3.66885245901655 points.",
            "status": "SUPPORTED_IN_DEVELOPMENT",
            "allowed_wording": (
                "Development evidence supports relative outperformance versus controls."
            ),
            "prohibited_wording": "Development proves standalone alpha.",
            "supporting_artifacts": [
                "results/gate_c5br/common_protocol_development_analysis.json",
                "results/gate_c5br/development_validation_reproduction.json",
            ],
        },
        {
            "claim_id": "B",
            "claim": "Acceptance relative outperformance replicated during 2020-2022.",
            "evidence": "Validation differential +27.453020134228165 points, permutation "
            "p=0.004497751124437781, CI [14.784214406740844, 40.27386831699497].",
            "counterevidence": "Replication does not by itself establish transportable "
            "dual-positive mechanism validity.",
            "status": "SUPPORTED_IN_VALIDATION",
            "allowed_wording": "The relative event-minus-control effect replicated in validation.",
            "prohibited_wording": "The validation result confirms a deployable trading edge.",
            "supporting_artifacts": [
                "results/gate_c5ar/validation_primary_estimand.json",
                "results/gate_c5ar/validation_inference.json",
            ],
        },
        {
            "claim_id": "C",
            "claim": "Acceptance events had positive absolute executable markout in validation.",
            "evidence": "Mean absolute event markout +11.33724832214778 points and bootstrap "
            "CI lower +0.7861459649301382.",
            "counterevidence": "Sign-flip p=0.12843578210894552 failed the preregistered p<=0.05 "
            "intersection rule.",
            "status": "DESCRIPTIVELY_SUPPORTED_BUT_NOT_CONFIRMED",
            "allowed_wording": "Validation absolute markout was descriptively positive but not "
            "confirmed by the full rule.",
            "prohibited_wording": "The absolute validation effect is confirmed.",
            "supporting_artifacts": [
                "results/gate_c5br/candidate_eligibility_trace.json",
                "results/gate_c6/inference_coherence_audit.json",
            ],
        },
        {
            "claim_id": "D",
            "claim": (
                "The dual-positive mechanism is transportable enough for holdout confirmation."
            ),
            "evidence": "Standardized validation event and differential signs stayed positive.",
            "counterevidence": "Maximum weight / median was 10.4 against a threshold of 10.0, "
            "so valid transport standardization failed.",
            "status": "NOT_SUPPORTED",
            "allowed_wording": "The dual-positive candidate was not transportable under the "
            "preregistered weight-validity rule.",
            "prohibited_wording": "The candidate is ready for the preserved holdout.",
            "supporting_artifacts": [
                "results/gate_c5br/transport_standardization.json",
                "results/gate_c6/transport_weight_failure_audit.json",
            ],
        },
        {
            "claim_id": "E",
            "claim": "Acceptance is a profitable standalone trading strategy.",
            "evidence": "No strategy-level backtest was run in this research closure gate.",
            "counterevidence": "The program tested event-level executable markouts, not portfolio "
            "construction or deployment.",
            "status": "NOT_TESTED_AND_NOT_CLAIMABLE",
            "allowed_wording": (
                "Standalone trading profitability was not tested and is not claimable."
            ),
            "prohibited_wording": "Acceptance is a profitable standalone trading strategy.",
            "supporting_artifacts": [
                "results/gate_c5br/quality_gate_final.json",
                "results/gate_c6/final_claim_matrix.json",
            ],
        },
    ]


def md_table(rows: list[list[Any]]) -> str:
    header = "| " + " | ".join(str(cell) for cell in rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows[1:]]
    return "\n".join([header, separator, *body])


def write_initial_docs(
    ledger: list[dict[str, Any]],
    reproduction: dict[str, Any],
    inference: dict[str, Any],
    transport: dict[str, Any],
    claim_matrix: list[dict[str, Any]],
) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    ledger_rows = [["Gate", "Data", "Result", "Decision", "Access"]]
    for item in ledger:
        ledger_rows.append(
            [
                item["gate_id"],
                item["data_interval"],
                item["result"],
                item["decision"],
                item["validation_holdout_access_status"],
            ]
        )
    (DOC_DIR / "ACCEPTANCE_RESEARCH_GATE_LEDGER.md").write_text(
        "# Acceptance Research Gate Ledger\n\n"
        "This ledger preserves blocked and successful gates in chronological order.\n\n"
        + md_table(ledger_rows)
        + "\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C6_INFERENCE_COHERENCE_AUDIT.md").write_text(
        "# Gate C6 Inference Coherence Audit\n\n"
        "The validation absolute effect has a positive mean, a positive day-cluster "
        "bootstrap lower bound, and a sign-flip permutation p-value above 0.05. "
        "This is not necessarily a software contradiction because the procedures "
        "target different nulls and use different resampling structures.\n\n"
        "The bootstrap interval summarizes mean uncertainty under day clustering. "
        "The sign-flip permutation checks a symmetry or exchangeability condition "
        "around zero using the frozen Monte Carlo implementation. Skew, heavy tails, "
        "within-day dependence, and unequal events per day can make those diagnostics "
        "diverge in finite samples.\n\n"
        f"Validation absolute mean: `{inference['validation_absolute_effect']['mean']}`\n\n"
        f"Bootstrap CI: `[{inference['validation_absolute_effect']['bootstrap_ci_lower']}, "
        f"{inference['validation_absolute_effect']['bootstrap_ci_upper']}]`\n\n"
        f"Sign-flip p: `{inference['validation_absolute_effect']['sign_flip_permutation_p']}`\n\n"
        "The preregistered intersection rule remains authoritative, so the "
        "absolute-effect criterion remains failed.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C6_TRANSPORT_WEIGHT_FAILURE.md").write_text(
        "# Gate C6 Transport Weight Failure\n\n"
        f"Maximum weight / median: `{transport['maximum_weight_median_multiple']}`\n\n"
        f"Threshold: `{transport['threshold']}`\n\n"
        "Formal result: `FAIL`.\n\n"
        "The breach is close to the threshold, but the preregistered rule is not "
        "relaxed. No observation was trimmed, capped, removed, or reweighted by a "
        "changed method.\n\n"
        f"Maximum-weight event id: `{transport['maximum_weight_observation']['event_id']}`\n\n"
        f"Source period: `{transport['maximum_weight_observation']['source_period']}`\n\n"
        f"Effective sample size: `{transport['weight_diagnostics']['effective_sample_size']}`\n\n"
        f"P95/P99 weights: `{transport['weight_diagnostics']['p95_weight']}` / "
        f"`{transport['weight_diagnostics']['p99_weight']}`\n\n"
        f"Weight coefficient of variation: "
        f"`{transport['weight_diagnostics']['weight_coefficient_of_variation']}`\n",
        encoding="utf-8",
    )
    claim_rows = [["Claim", "Status", "Allowed wording"]]
    for item in claim_matrix:
        claim_rows.append([item["claim_id"], item["status"], item["allowed_wording"]])
    (DOC_DIR / "ACCEPTANCE_FINAL_CLAIM_MATRIX.md").write_text(
        "# Acceptance Final Claim Matrix\n\n" + md_table(claim_rows) + "\n",
        encoding="utf-8",
    )
    (DOC_DIR / "ACCEPTANCE_RESEARCH_METHODS.md").write_text(
        "# Acceptance Research Methods\n\n"
        "Prospective: data-source provenance, pair-scoped USDJPY development freeze, "
        "C4 preregistration, C5 handoff amendment, and C5-B-R transport rules were "
        "frozen before their corresponding outcome adjudications.\n\n"
        "Confirmatory: event definition, confirmation semantics, next-bar execution, "
        "120-minute bid/ask executable outcomes, primary non-overlap policy, exact "
        "matching, covariate balance, paired permutation tests, day-cluster bootstrap, "
        "placebo checks, and development/validation separation were applied as frozen.\n\n"
        "Exploratory: C4-B mechanism redesign was derived from development evidence "
        "and explicitly labeled before validation. C5-B-R dual-positive transport "
        "diagnostics were validation-informed and stopped before holdout.\n\n"
        "Post-validation diagnostic: reconciliation overlays resolved artifact hash "
        "provenance without changing scientific values. Transport standardization "
        "used exact-cell stabilized covariate weighting over preregistered bins.\n\n"
        "Operational remediation: provider parity and fallback were documented after "
        "data-quality failures, including prevention of zero-row certification.\n\n"
        "Holdout preservation: the 2023-2025 holdout remained unopened and is not "
        "authorized for this closed Acceptance family.\n",
        encoding="utf-8",
    )
    annual = load_json(REPO / "results/gate_c5br/temporal_mechanism_stability.json")
    (DOC_DIR / "ACCEPTANCE_RESEARCH_RESULTS.md").write_text(
        "# Acceptance Research Results\n\n"
        "## 1. Data Certification\n\n"
        "USDJPY development data were frozen for 2015-2019. Validation data were "
        "recertified for 2020-2022 after provider remediation.\n\n"
        "## 2. Development Event Counts\n\n"
        "Common-protocol development matched events: `2440`.\n\n"
        "## 3. Development Primary Effects\n\n"
        f"Event `{reproduction['development']['event_markout']}`, control "
        f"`{reproduction['development']['control_markout']}`, differential "
        f"`{reproduction['development']['differential']}`, p "
        f"`{reproduction['development']['permutation_p']}`, CI "
        f"`{reproduction['development']['ci95']}`.\n\n"
        "## 4. Internal Temporal Replication\n\n"
        "C4-B preserved discovery differential `18.22368421052636` and internal "
        "replication differential `7.2751004016060214`.\n\n"
        "## 5. Mechanism Redesign\n\n"
        "C4-B separated absolute event response from relative resilience.\n\n"
        "## 6. Validation Matching and Balance\n\n"
        "Validation matched events: `1192`; exact-key relaxations: `0`; balance "
        "requirements passed.\n\n"
        "## 7. Validation Relative Effect\n\n"
        f"Event `{reproduction['validation']['event_markout']}`, control "
        f"`{reproduction['validation']['control_markout']}`, differential "
        f"`{reproduction['validation']['differential']}`, p "
        f"`{reproduction['validation']['relative_permutation_p']}`, CI "
        f"`{reproduction['validation']['relative_ci95']}`.\n\n"
        "## 8. Validation Absolute Effect\n\n"
        f"Absolute mean `{reproduction['validation']['event_markout']}`, sign-flip p "
        f"`{reproduction['validation']['absolute_sign_flip_p']}`, CI "
        f"`{reproduction['validation']['absolute_ci95']}`. This failed the full "
        "preregistered rule.\n\n"
        "## 9. Placebo\n\n"
        "The shifted placebo did not reproduce the relative-resilience effect.\n\n"
        "## 10. Annual Stability\n\n"
        f"Validation annual effects: `{annual['by_year']['validation']}`.\n\n"
        "## 11. Mechanism Transition\n\n"
        "Event markout changed by `15.00610078116433`, control markout by "
        "`1.2211134338212517`, and differential by `13.78498734734307`.\n\n"
        "## 12. Transport Standardization\n\n"
        f"Standardized validation event "
        f"`{reproduction['transport']['standardized_validation_event']}`, standardized "
        f"differential `{reproduction['transport']['standardized_validation_differential']}`, "
        f"maximum weight / median "
        f"`{reproduction['transport']['maximum_weight_median_multiple']}`.\n\n"
        "## 13. Failed Candidate Criteria\n\n"
        "Failed criteria: absolute-effect inference and valid transport standardization.\n\n"
        "## 14. Final Research Decision\n\n"
        f"`{FINAL_DECISION}`.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "ACCEPTANCE_RESEARCH_ABSTRACT.md").write_text(
        "# Acceptance Research Abstract\n\n"
        "## Background\n\n"
        "This study evaluated a USDJPY Acceptance event family using frozen "
        "development and validation protocols.\n\n"
        "## Methods\n\n"
        "Events were confirmed before next-bar entry, evaluated with bid/ask "
        "executable 120-minute markouts, exact matched controls, paired permutation "
        "tests, day-cluster bootstrap intervals, placebo checks, and transport "
        "standardization diagnostics.\n\n"
        "## Results\n\n"
        "The development relative differential was +13.668032786885094 points. "
        "The validation relative differential was +27.453020134228165 points. "
        "Validation absolute event markout was descriptively positive, but the "
        "sign-flip p-value was 0.12843578210894552. Transport weight validity failed "
        "with maximum weight / median equal to 10.4 against a 10.0 threshold.\n\n"
        "## Conclusions\n\n"
        "The relative effect replicated, but evidence was insufficient to establish a "
        "transportable dual-positive mechanism or standalone trading alpha.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "ACCEPTANCE_LIMITATIONS.md").write_text(
        "# Acceptance Limitations\n\n"
        "Limitations include a single pair, one event family, outcome-informed "
        "mechanism redesign, matching dependence, clustered event dependence, "
        "sign-flip/bootstrap divergence, transport-weight instability, provider "
        "remediation, development/validation regime shift, no holdout test, no "
        "strategy-level backtest, no transaction-cost model beyond observed bid/ask, "
        "and possible latent confounding.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "ACCEPTANCE_RESEARCH_LESSONS.md").write_text(
        "# Acceptance Research Lessons\n\n"
        "- Freeze every hash mode explicitly.\n"
        "- Generate locks only after all referenced artifacts.\n"
        "- Distinguish absolute and relative estimands early.\n"
        "- Predefine inference for every future co-primary estimand.\n"
        "- Align development and validation matching protocols.\n"
        "- Freeze transport-weight validity rules prospectively.\n"
        "- Validate provider errors below generic wrappers.\n"
        "- Prevent zero-row certification.\n"
        "- Preserve blocked gates as evidence.\n"
        "- Avoid repeatedly deriving hypotheses from the same validation period.\n",
        encoding="utf-8",
    )


def build_manifest() -> dict[str, Any]:
    groups = {
        "preregistrations": [
            artifact("docs/research/GATE_C4_PREREGISTRATION.md"),
            artifact("docs/research/GATE_C4B_MECHANISM_PREREGISTRATION.md"),
            artifact("docs/research/GATE_C5A_PROSPECTIVE_HANDOFF_AMENDMENT.md"),
            artifact("docs/research/GATE_C5BR_MECHANISM_TRANSITION_PREREGISTRATION.md"),
        ],
        "development_freeze": [
            artifact("docs/research/GATE_C3FCRSF_DATASET_FREEZE.md"),
            artifact("results/gate_c3fcrsf/development_dataset_freeze.json"),
        ],
        "validation_freeze": [
            artifact("docs/research/GATE_C5ADQR_VALIDATION_DATASET_FREEZE.md"),
            artifact("results/gate_c5adqr/validation_dataset_freeze.json"),
        ],
        "event_detector": [
            artifact("src/fx_smc_bot/research/gate_c4_event_alpha.py"),
            artifact("src/fx_smc_bot/research/gate_c4b_mechanism.py"),
        ],
        "event_configuration": [
            artifact("results/gate_c4b/new_hypothesis_specification.json"),
            artifact("results/gate_c5ar/scientific_code_integrity.json"),
        ],
        "row_level_artifact_manifests": [
            artifact("results/gate_c5ar/post_validation_lock.json"),
            artifact("results/gate_c5br/c5ar_artifact_integrity.json"),
        ],
        "matching_implementations": [
            artifact("src/fx_smc_bot/research/gate_c5a_amendment.py"),
            artifact("src/fx_smc_bot/research/gate_c5br.py"),
        ],
        "inference_implementations": [
            artifact("src/fx_smc_bot/research/gate_c4_event_alpha.py"),
            artifact("src/fx_smc_bot/research/gate_c5br.py"),
        ],
        "placebo_implementations": [
            artifact("results/gate_c5a/amended_development_replay.json"),
            artifact("results/gate_c5ar/validation_placebo.json"),
        ],
        "reconciliation_overlays": [
            artifact("results/gate_c5arir/artifact_reconciliation_overlay.json"),
            artifact("results/gate_c5arir/c5b_resumption_handoff.json"),
            artifact("results/gate_c5br/reconciliation_integrity.json"),
        ],
        "compact_result_artifacts": [
            artifact("results/gate_c5br/common_protocol_development_analysis.json"),
            artifact("results/gate_c5br/development_validation_reproduction.json"),
            artifact("results/gate_c5br/transport_standardization.json"),
            artifact("results/gate_c5br/candidate_eligibility_trace.json"),
            artifact("results/gate_c6/final_result_reproduction.json"),
            artifact("results/gate_c6/inference_coherence_audit.json"),
            artifact("results/gate_c6/transport_weight_failure_audit.json"),
        ],
        "research_stop_record": [
            artifact("results/gate_c5br/research_stop_record.json"),
        ],
        "final_claim_matrix": [
            artifact("results/gate_c6/final_claim_matrix.json"),
            artifact("docs/research/ACCEPTANCE_FINAL_CLAIM_MATRIX.md"),
        ],
        "methods_and_results_reports": [
            artifact("docs/research/ACCEPTANCE_RESEARCH_METHODS.md"),
            artifact("docs/research/ACCEPTANCE_RESEARCH_RESULTS.md"),
            artifact("docs/research/ACCEPTANCE_RESEARCH_ABSTRACT.md"),
            artifact("docs/research/ACCEPTANCE_LIMITATIONS.md"),
        ],
    }
    manifest = {
        "gate": "C6",
        "artifact_groups": groups,
        "raw_or_row_level_data_included": False,
        "holdout_data_included": False,
        "created_at_utc": now_utc(),
    }
    manifest["manifest_hash"] = canonical_json_sha256(manifest)
    return manifest


def write_reproducibility_doc(manifest: dict[str, Any]) -> None:
    lines = [
        "# Acceptance Reproducibility",
        "",
        f"Manifest hash: `{manifest['manifest_hash']}`",
        "",
        "The manifest records source, document, and compact result artifact hashes only. "
        "It excludes raw data, row-level parquet data, holdout data, caches, logs, "
        "and credentials.",
        "",
    ]
    for group, entries in manifest["artifact_groups"].items():
        lines.extend([f"## {group}", ""])
        for entry in entries:
            lines.append(f"- `{entry['path']}`: `{entry['sha256']}`")
        lines.append("")
    (DOC_DIR / "ACCEPTANCE_REPRODUCIBILITY.md").write_text("\n".join(lines), encoding="utf-8")


def build_holdout_integrity() -> dict[str, Any]:
    previous = load_json(REPO / "results/gate_c5br/holdout_integrity.json")
    checks = previous.get("checks", {})
    payload = {flag: bool(checks.get(flag, previous.get(flag, False))) for flag in HOLDOUT_FLAGS}
    validation = validate_holdout_unauthorized(payload)
    return {
        **payload,
        "violations": validation["violations"],
        "status": validation["status"],
        "source": "results/gate_c5br/holdout_integrity.json",
        "note": "Gate C6 read only the prior compact holdout-integrity record.",
        "created_at_utc": now_utc(),
    }


def build_lineage_seal(manifest: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    seal = {
        "seal_id": SEAL_ID,
        "status": SEAL_STATUS,
        "final_decision": FINAL_DECISION,
        "closure_statements": [
            "No further outcome-informed Acceptance hypotheses may be tested against the preserved "
            "2023-2025 holdout.",
            "The holdout remains unopened and is not authorized for this closed hypothesis family.",
            "Any future Acceptance research must use a genuinely new external dataset, "
            "new prospective "
            "data collection, or an independently specified hypothesis before data access.",
        ],
        "hashes": {
            "final_c5br_research_stop_record": artifact(
                "results/gate_c5br/research_stop_record.json"
            ),
            "reconciliation_overlay": artifact(
                "results/gate_c5arir/artifact_reconciliation_overlay.json"
            ),
            "reconciliation_handoff": artifact("results/gate_c5arir/c5b_resumption_handoff.json"),
            "c6_holdout_integrity": artifact("results/gate_c6/holdout_integrity.json"),
            "final_claim_matrix": artifact("results/gate_c6/final_claim_matrix.json"),
            "reproducibility_manifest": artifact("results/gate_c6/reproducibility_manifest.json"),
        },
        "manifest_hash": manifest["manifest_hash"],
        "holdout_integrity_status": holdout["status"],
        "created_at_utc": now_utc(),
    }
    seal["lineage_seal_hash"] = lineage_seal_hash(seal)
    return seal


def write_seal_doc(seal: dict[str, Any]) -> None:
    (DOC_DIR / "ACCEPTANCE_LINEAGE_SEAL.md").write_text(
        "# Acceptance Lineage Seal\n\n"
        f"Seal ID: `{seal['seal_id']}`\n\n"
        f"Status: `{seal['status']}`\n\n"
        f"Lineage seal hash: `{seal['lineage_seal_hash']}`\n\n"
        + "\n\n".join(seal["closure_statements"])
        + "\n",
        encoding="utf-8",
    )


def write_final_memo(
    lineage: dict[str, Any],
    reproduction: dict[str, Any],
    inference: dict[str, Any],
    transport: dict[str, Any],
    claim_validation: dict[str, Any],
    manifest_validation: dict[str, Any],
    seal_validation: dict[str, Any],
    holdout: dict[str, Any],
) -> dict[str, Any]:
    docs_to_scan = [
        DOC_DIR / "ACCEPTANCE_RESEARCH_METHODS.md",
        DOC_DIR / "ACCEPTANCE_RESEARCH_RESULTS.md",
        DOC_DIR / "ACCEPTANCE_RESEARCH_ABSTRACT.md",
        DOC_DIR / "ACCEPTANCE_LIMITATIONS.md",
        DOC_DIR / "ACCEPTANCE_REPRODUCIBILITY.md",
        DOC_DIR / "ACCEPTANCE_LINEAGE_SEAL.md",
        DOC_DIR / "ACCEPTANCE_RESEARCH_LESSONS.md",
        DOC_DIR / "GATE_C6_FINAL_DECISION_MEMO.md",
    ]
    scanned_text = "\n".join(
        path.read_text(encoding="utf-8") for path in docs_to_scan if path.exists()
    )
    no_strategy_metrics = not find_prohibited_strategy_metrics(scanned_text)
    no_handoff = validate_no_acceptance_holdout_handoff(
        [
            "results/gate_c6/repository_state.json",
            "results/gate_c6/lineage_integrity.json",
            "results/gate_c6/holdout_integrity.json",
        ]
    )
    checks = {
        "complete_lineage_integrity": lineage["status"] == "PASS",
        "final_numbers_reproduce": reproduction["status"] == "PASS",
        "inference_coherence_audit_complete": inference["status"] == "PASS",
        "transport_weight_audit_complete": transport["status"] == "PASS"
        and transport["formal_result"] == "FAIL",
        "claims_accurately_bounded": claim_validation["status"] == "PASS",
        "reproducibility_manifest_complete": manifest_validation["status"] == "PASS",
        "lineage_seal_exists": seal_validation["status"] == "PASS",
        "holdout_remains_unopened": holdout["status"] == "PASS",
        "no_new_acceptance_hypothesis_created": True,
        "no_acceptance_holdout_handoff_created": no_handoff["status"] == "PASS",
        "no_prohibited_strategy_metrics_in_publication_docs": no_strategy_metrics,
    }
    quality = {
        "gate": "C6",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "final_decision": FINAL_DECISION
        if all(checks.values())
        else "BLOCKED_BY_REPORTING_INCONSISTENCY",
        "no_acceptance_holdout_handoff": no_handoff,
        "publication_doc_prohibited_strategy_terms": find_prohibited_strategy_metrics(scanned_text),
        "created_at_utc": now_utc(),
    }
    (DOC_DIR / "GATE_C6_FINAL_DECISION_MEMO.md").write_text(
        "# Gate C6 Final Decision Memo\n\n"
        f"Final decision: `{quality['final_decision']}`\n\n"
        f"Lineage integrity: `{lineage['status']}`\n\n"
        f"Final number reproduction: `{reproduction['status']}`\n\n"
        f"Inference coherence audit: `{inference['status']}`\n\n"
        f"Transport weight audit: `{transport['formal_result']}` under the formal threshold.\n\n"
        f"Claim matrix: `{claim_validation['status']}`\n\n"
        f"Reproducibility manifest: `{manifest_validation['status']}`\n\n"
        f"Lineage seal: `{seal_validation['status']}`\n\n"
        f"Holdout integrity: `{holdout['status']}`\n\n"
        "No new Acceptance hypothesis or holdout handoff was created. The preserved "
        "holdout remains unopened and unauthorized for this closed hypothesis family.\n",
        encoding="utf-8",
    )
    return quality


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    repository_state = build_repository_state()
    ledger = build_ledger(repository_state["git_log_oneline_decorate_60"])
    lineage = build_lineage_integrity(repository_state, ledger)
    reproduction = build_final_reproduction()
    inference = build_inference_audit(reproduction)
    transport = build_transport_audit()
    claim_matrix = build_claim_matrix()
    claim_validation = validate_claim_matrix(claim_matrix)

    write_json(RESULT_DIR / "repository_state.json", repository_state)
    write_json(RESULT_DIR / "lineage_integrity.json", lineage)
    write_json(RESULT_DIR / "acceptance_research_gate_ledger.json", {"gates": ledger})
    write_json(RESULT_DIR / "final_result_reproduction.json", reproduction)
    write_json(RESULT_DIR / "inference_coherence_audit.json", inference)
    write_json(RESULT_DIR / "transport_weight_failure_audit.json", transport)
    write_json(
        RESULT_DIR / "final_claim_matrix.json",
        {"claims": claim_matrix, "validation": claim_validation},
    )
    write_initial_docs(ledger, reproduction, inference, transport, claim_matrix)

    manifest = build_manifest()
    write_reproducibility_doc(manifest)
    manifest = build_manifest()
    write_json(RESULT_DIR / "reproducibility_manifest.json", manifest)
    write_reproducibility_doc(manifest)
    manifest_validation = validate_manifest_completeness(manifest)

    holdout = build_holdout_integrity()
    write_json(RESULT_DIR / "holdout_integrity.json", holdout)
    seal = build_lineage_seal(manifest, holdout)
    write_json(RESULT_DIR / "acceptance_lineage_seal.json", seal)
    write_seal_doc(seal)
    seal_validation = validate_lineage_seal(seal)
    quality = write_final_memo(
        lineage,
        reproduction,
        inference,
        transport,
        claim_validation,
        manifest_validation,
        seal_validation,
        holdout,
    )
    write_json(RESULT_DIR / "quality_gate_final.json", quality)
    return 0 if quality["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
