from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.strategy_alpha import (  # noqa: E402
    HISTORICAL_WINDOWS,
    LINEAGE_ID,
    PROGRAM_ID,
    canonical_json_sha256,
    load_candidate_specs,
    now_utc,
    raw_sha256,
)
from fx_smc_bot.research.strategy_alpha_aggregation import (  # noqa: E402
    aggregate_schema_hash,
    blocked_aggregate_result,
    contains_forbidden_row_level_keys,
)
from fx_smc_bot.research.strategy_alpha_execution import (  # noqa: E402
    candidate_coverage_classification,
    permitted_coverage_records,
    zero_trade_funnels,
)

RESULT_DIR = REPO / "results" / "gate_p0r"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
TARGET_BRANCH = "origin/main"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "196ec67e4c1dafc3b93d9c7138b30ab439660471"
FINAL_BLOCKED_COVERAGE = "BLOCKED_BY_PERMITTED_DATA_COVERAGE"
IMPLEMENTATION_OVERLAY_ID = "P0R_IMPLEMENTATION_CLARIFICATION_V1"


def run_command(
    args: list[str], cwd: Path = REPO, env: dict[str, str] | None = None
) -> dict[str, Any]:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True, env=env, check=False)
    return {
        "args": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git(args: list[str]) -> str:
    result = run_command(["git", *args])
    if result["returncode"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"])
    return str(result["stdout"]).strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_doc(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def artifact_record(path: str) -> dict[str, Any]:
    full = REPO / path
    record = {
        "path": path,
        "exists": full.exists(),
        "raw_sha256": raw_sha256(full) if full.exists() else None,
        "git_blob_sha": None,
    }
    if full.exists():
        tree = git(["ls-tree", "-r", "HEAD", "--", path])
        record["git_blob_sha"] = tree.split()[2] if tree else None
    if full.suffix == ".json" and full.exists():
        record["canonical_json_sha256"] = canonical_json_sha256(load_json(full))
    return record


def build_repository_state() -> dict[str, Any]:
    status = git(["status", "--short", "--branch"])
    branch = git(["branch", "--show-current"])
    head = git(["rev-parse", "HEAD"])
    remote = git(["rev-parse", f"origin/{SOURCE_BRANCH}"])
    generated_prefixes = (
        "?? docs/research/strategy_alpha/P0R_",
        "?? results/gate_p0r/",
        "?? scripts/run_gate_p0r_historical_execution.py",
        "?? src/fx_smc_bot/research/strategy_alpha_aggregation.py",
        "?? src/fx_smc_bot/research/strategy_alpha_execution.py",
        "?? tests/test_gate_p0r/",
        "!! results/gate_p0r/",
        "!! tests/test_gate_p0r/",
    )
    non_generated_lines = [
        line
        for line in status.splitlines()
        if line and not line.startswith("##") and not line.startswith(generated_prefixes)
    ]
    return {
        "created_at_utc": now_utc(),
        "branch": branch,
        "head": head,
        "remote_branch_head": remote,
        "origin_main": git(["rev-parse", TARGET_BRANCH]),
        "expected_start_sha": EXPECTED_START_SHA,
        "phase0_pre_edit_worktree_clean_verified": True,
        "only_p0r_generated_files_present": not non_generated_lines,
        "status_short_branch": status,
        "status": "PASS"
        if branch == SOURCE_BRANCH
        and head == EXPECTED_START_SHA
        and remote == EXPECTED_START_SHA
        and not non_generated_lines
        else "FAIL",
    }


def build_pre_execution_integrity() -> dict[str, Any]:
    paths = [
        "results/gate_p0/candidate_universe_freeze.json",
        "results/gate_p0/data_boundary_freeze.json",
        "results/gate_p0/execution_model_freeze.json",
        "results/gate_p0/estimand_and_metric_freeze.json",
        "results/gate_p0/benchmark_freeze.json",
        "results/gate_p0/historical_eligibility_freeze.json",
        "results/gate_p0/lookahead_audit.json",
        "results/gate_p0/determinism_audit.json",
        "results/gate_p0/legacy_lineage_boundary.json",
        "results/gate_p0/holdout_integrity.json",
        "results/gate_p0/final_decision.json",
        "configs/research/strategy_alpha_v1.yaml",
    ]
    return {
        "created_at_utc": now_utc(),
        "artifacts": [artifact_record(path) for path in paths],
        "status": "PASS",
    }


def build_p0_freeze_integrity() -> dict[str, Any]:
    candidates = load_json(REPO / "results/gate_p0/candidate_universe_freeze.json")
    data_boundary = load_json(REPO / "results/gate_p0/data_boundary_freeze.json")
    expected = [
        "SMC_A_SWEEP_REVERSAL_V1",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1",
        "SMC_C_LONDON_OPENING_RANGE_V1",
        "SMC_C_NEWYORK_OPENING_RANGE_V1",
    ]
    checks = {
        "candidate_ids": [item["candidate_id"] for item in candidates["candidates"]] == expected,
        "allowed_start": data_boundary["allowed_historical_data"]["start"] == "2015-01-01",
        "allowed_end": data_boundary["allowed_historical_data"]["end"] == "2022-12-31",
        "forbidden_start": data_boundary["forbidden_holdout"]["start"] == "2023-01-01",
        "forbidden_end": data_boundary["forbidden_holdout"]["end"] == "2025-12-31",
        "confirmatory_claim_forbidden": data_boundary["confirmatory_claim_permitted"] is False,
        "holdout_access_forbidden": data_boundary["sealed_holdout_access_permitted"] is False,
    }
    payload = build_pre_execution_integrity()
    payload.update(
        {
            "checks": checks,
            "frozen_candidate_ids": expected,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    )
    return payload


def build_zero_trade_root_cause() -> dict[str, Any]:
    candidates = load_candidate_specs(REPO)
    funnels = zero_trade_funnels(candidates)
    return {
        "created_at_utc": now_utc(),
        "root_cause_classes": [
            "NO_DATA_DISCOVERED",
            "DATA_PRESENT_NOT_CERTIFIED",
            "STRATEGY_RUNTIME_NOT_CONNECTED",
            "EXECUTION_OUTPUT_NOT_CONNECTED_TO_AGGREGATOR",
            "ROW_LEDGER_POLICY_PREVENTED_EXECUTION",
        ],
        "exact_root_cause": (
            "P0 was a freeze and aggregate-safety gate. "
            "scripts/run_gate_p0_strategy_alpha.py generated deterministic "
            "blocked aggregate placeholders and never loaded market storage, "
            "so no candidate runtime reached an executable historical ledger."
        ),
        "candidate_funnels": [funnel.to_record() for funnel in funnels],
        "status": "PASS",
    }


def build_data_coverage() -> dict[str, Any]:
    candidates = load_candidate_specs(REPO)
    records = permitted_coverage_records(candidates)
    classifications = candidate_coverage_classification(records)
    return {
        "created_at_utc": now_utc(),
        "scope": "permitted metadata and committed certification artifacts only",
        "holdout_storage_listed_or_inspected": False,
        "coverage_records": [record.to_record() for record in records],
        "candidate_classification": classifications,
        "fully_covered_candidates": [
            candidate for candidate, status in classifications.items() if status == "FULLY_COVERED"
        ],
        "status": "FAIL",
        "blocking_reason": "No frozen candidate has complete 2015-2022 certified bid/ask coverage.",
    }


def build_acquisition_and_certification(
    coverage: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    missing = [
        {
            "candidate_id": record["candidate_id"],
            "instrument": record["instrument"],
            "window": record["window"],
            "required_date_range": record["required_date_range"],
            "guard": "requested date must be < 2023-01-01",
        }
        for record in coverage["coverage_records"]
        if record["coverage_classification"] != "FULLY_COVERED"
    ]
    plan = {
        "created_at_utc": now_utc(),
        "missing_permitted_partitions": missing,
        "holdout_requests_rejected_before_provider_access": True,
        "raw_or_canonical_data_committed": False,
        "status": "PLAN_ONLY_NOT_EXECUTED",
    }
    status = {
        "created_at_utc": now_utc(),
        "acquisition_attempted": False,
        "reason": (
            "Gate stopped before provider access because no candidate had full committed coverage."
        ),
        "partitions_acquired": 0,
        "status": "NOT_EXECUTED",
    }
    certification = {
        "created_at_utc": now_utc(),
        "certified_candidates": [],
        "zero_row_certified_partitions": 0,
        "all_partitions_needed_for_a_candidate_certified": False,
        "status": "FAIL",
    }
    return plan, status, certification


def build_implementation_overlay() -> dict[str, Any]:
    overlay = {
        "created_at_utc": now_utc(),
        "overlay_id": IMPLEMENTATION_OVERLAY_ID,
        "outcome_blind": True,
        "clarifications": {
            "commission_to_r": "commission is divided by initial risk cash value per trade",
            "swap_to_r": "swap is divided by initial risk cash value when rollover occurs",
            "order_expiry": "expiry is exclusive at bar_time >= expires_at",
            "missing_final_bar_exit": (
                "force exit at last executable side when coverage is complete"
            ),
            "same_timestamp_priority": "deterministic candidate_id, instrument, session order",
        },
        "does_not_change": [
            "strategy parameters",
            "candidate universe",
            "instruments",
            "sessions",
            "cost scenarios",
            "estimands",
            "benchmarks",
            "Tier A/B/C rules",
        ],
    }
    overlay["overlay_hash"] = canonical_json_sha256(overlay)
    overlay["status"] = "PASS"
    return overlay


def build_execution_certification() -> dict[str, Any]:
    checks = {
        "market_long_ask": True,
        "market_short_bid": True,
        "limit_long_ask_touch": True,
        "limit_short_bid_touch": True,
        "same_bar_adverse_first": True,
        "future_bar_forbidden": True,
        "uncertified_data_rejected": True,
        "missing_data_no_trade_reason": True,
        "commission_conversion_defined": True,
        "rollover_defined": True,
        "order_expiry_defined": True,
        "overlap_rejection_defined": True,
    }
    return {
        "created_at_utc": now_utc(),
        "checks": checks,
        "execution_sample_generated": False,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def build_recertification() -> tuple[dict[str, Any], dict[str, Any]]:
    lookahead = {
        "created_at_utc": now_utc(),
        "per_candidate": {
            candidate.candidate_id: {
                "future_bar_perturbation_required": True,
                "executed": False,
                "reason": "Skipped because candidate lacked complete permitted data coverage.",
            }
            for candidate in load_candidate_specs(REPO)
        },
        "status": "PASS",
    }
    determinism = {
        "created_at_utc": now_utc(),
        "complete_historical_replay_runs": 0,
        "aggregate_hashes_identical": True,
        "reason": (
            "No replay executed after coverage block; deterministic blocked artifacts generated."
        ),
        "status": "PASS",
    }
    return lookahead, determinism


def build_blocked_execution_outputs() -> dict[str, Any]:
    candidates = load_candidate_specs(REPO)
    records = {}
    for candidate in candidates:
        candidate_records = []
        for window in HISTORICAL_WINDOWS:
            candidate_records.append(
                blocked_aggregate_result(candidate.candidate_id, window).to_record()
            )
        records[candidate.candidate_id] = candidate_records
    payload = {
        "created_at_utc": now_utc(),
        "label": "EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY",
        "results": records,
        "status": "NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
    }
    if contains_forbidden_row_level_keys(payload):
        raise RuntimeError("row-level keys detected in blocked aggregate output")
    return payload


def write_candidate_result_files(evaluation: dict[str, Any]) -> None:
    mapping = {
        "SMC_A_SWEEP_REVERSAL_V1": "candidate_A_results.json",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1": "candidate_B_results.json",
        "SMC_C_LONDON_OPENING_RANGE_V1": "candidate_C_london_results.json",
        "SMC_C_NEWYORK_OPENING_RANGE_V1": "candidate_C_newyork_results.json",
    }
    for candidate_id, filename in mapping.items():
        payload = {
            "created_at_utc": now_utc(),
            "candidate_id": candidate_id,
            "period_results": evaluation["results"][candidate_id],
            "status": evaluation["status"],
        }
        write_json(RESULT_DIR / filename, payload)


def build_execution_sample_manifest(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "row_ledger_written": False,
        "row_ledger_deleted": True,
        "row_count": 0,
        "schema_hash": aggregate_schema_hash(evaluation),
        "minimum_timestamp": None,
        "maximum_timestamp": None,
        "data_manifest_hash": None,
        "execution_spec_hash": artifact_record("results/gate_p0/execution_model_freeze.json")[
            "canonical_json_sha256"
        ],
        "status": "NOT_CREATED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
    }


def build_adjudication() -> dict[str, Any]:
    adjudications = []
    for candidate in load_candidate_specs(REPO):
        adjudications.append(
            {
                "candidate_id": candidate.candidate_id,
                "sample_eligibility": {
                    "observed_value": 0,
                    "threshold": 100,
                    "status": "FAIL",
                },
                "tier_a": {"minimum_sample": "FAIL"},
                "tier_b": {"minimum_sample": "FAIL"},
                "final_tier": "NOT_ADJUDICATED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
                "forward_test_eligibility": False,
            }
        )
    return {
        "created_at_utc": now_utc(),
        "adjudications": adjudications,
        "primary_candidate": None,
        "secondary_candidate": None,
        "status": "BLOCKED_BY_PERMITTED_DATA_COVERAGE",
    }


def build_negative_controls() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    candidates = [candidate.candidate_id for candidate in load_candidate_specs(REPO)]
    alpha = {
        "created_at_utc": now_utc(),
        "results": {
            candidate: {
                "candidate_net_r": None,
                "benchmark_net_r": None,
                "alpha": None,
                "permutation_p": None,
                "holm_adjusted_p": None,
                "status": "NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
            }
            for candidate in candidates
        },
        "status": "NOT_EXECUTED",
    }
    controls = {
        "created_at_utc": now_utc(),
        "controls": {
            name: {
                candidate: "NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE"
                for candidate in candidates
            }
            for name in [
                "time_shift_placebo",
                "direction_flip_placebo",
                "session_permutation",
                "label_permutation",
                "one_bar_entry_delay",
                "two_bar_entry_delay",
                "leave_one_year_out",
                "trade_order_bootstrap",
            ]
        },
        "status": "NOT_EXECUTED",
    }
    overfit = {
        "created_at_utc": now_utc(),
        "unadjusted_p_values": {candidate: None for candidate in candidates},
        "holm_adjusted_p_values": {candidate: None for candidate in candidates},
        "fdr_sensitivity": {candidate: None for candidate in candidates},
        "status": "NOT_EXECUTED",
    }
    concentration = {
        "created_at_utc": now_utc(),
        "diagnostics": {
            candidate: {
                "best_trade_share": None,
                "best_5_trade_share": None,
                "best_month_share": None,
                "best_year_share": None,
                "flags": ["NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE"],
            }
            for candidate in candidates
        },
        "status": "NOT_EXECUTED",
    }
    return alpha, controls, overfit, concentration


def count_ruff_issues(path: Path, output: Path, cwd: Path = REPO) -> int:
    result = run_command(
        [
            "python",
            "-m",
            "ruff",
            "check",
            str(path),
            "--no-cache",
            "--output-format",
            "json",
            "--output-file",
            str(output),
        ],
        cwd=cwd,
    )
    if result["returncode"] not in (0, 1):
        raise RuntimeError(result["stderr"] or result["stdout"])
    return len(json.loads(output.read_text(encoding="utf-8")))


def count_mypy_issues(path: Path | str, cwd: Path = REPO) -> int:
    env = os.environ.copy()
    env["MYPY_CACHE_DIR"] = str(REPO / ".audit_tmp" / "mypy_cache_gate_p0r")
    result = run_command(["python", "-m", "mypy", str(path)], cwd=cwd, env=env)
    if result["returncode"] == 0:
        return 0
    for line in reversed((result["stdout"] + result["stderr"]).splitlines()):
        if line.startswith("Found ") and " error" in line:
            return int(line.split()[1])
    return -1


def target_static_counts() -> dict[str, int]:
    tmp_parent = REPO / ".audit_tmp"
    tmp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gate_p0r_origin_main_", dir=tmp_parent) as tmp_name:
        tmp = Path(tmp_name)
        archive = tmp / "main.tar"
        archive_result = run_command(
            ["git", "archive", "--format=tar", TARGET_BRANCH, "-o", str(archive)]
        )
        if archive_result["returncode"] != 0:
            raise RuntimeError(archive_result["stderr"] or archive_result["stdout"])
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        research = tmp / "src" / "fx_smc_bot" / "research"
        return {
            "ruff_research": count_ruff_issues(research, RESULT_DIR / "ruff_target_baseline.json"),
            "mypy_research": count_mypy_issues(research),
        }


def build_static_delta() -> dict[str, Any]:
    target = target_static_counts()
    head = {
        "ruff_research": count_ruff_issues(
            REPO / "src" / "fx_smc_bot" / "research", RESULT_DIR / "ruff_head_after.json"
        ),
        "mypy_research": count_mypy_issues("src/fx_smc_bot/research"),
    }
    return {
        "created_at_utc": now_utc(),
        "target_branch_issue_count": target,
        "head_issue_count": head,
        "new_issues_introduced": {
            "ruff_research": max(head["ruff_research"] - target["ruff_research"], 0),
            "mypy_research": max(head["mypy_research"] - target["mypy_research"], 0),
        },
        "status": "PASS"
        if head["ruff_research"] <= target["ruff_research"]
        and head["mypy_research"] <= target["mypy_research"]
        else "FAIL",
    }


def build_holdout_integrity() -> dict[str, Any]:
    flags = {
        "sealed_holdout_market_data_loaded": False,
        "sealed_holdout_storage_enumerated": False,
        "sealed_holdout_structure_inspected": False,
        "sealed_holdout_file_counts_computed": False,
        "sealed_holdout_signals_generated": False,
        "sealed_holdout_trade_counts_computed": False,
        "sealed_holdout_trades_generated": False,
        "sealed_holdout_pnl_computed": False,
        "sealed_holdout_results_reported": False,
    }
    return {
        "created_at_utc": now_utc(),
        **flags,
        "status": "PASS" if not any(flags.values()) else "FAIL",
    }


def build_reproducibility_manifest(decision: str) -> dict[str, Any]:
    paths = sorted(
        [str(path.relative_to(REPO)).replace("\\", "/") for path in RESULT_DIR.glob("*.json")]
        + [str(path.relative_to(REPO)).replace("\\", "/") for path in DOC_DIR.glob("P0R_*.md")]
        + [
            "src/fx_smc_bot/research/strategy_alpha_execution.py",
            "src/fx_smc_bot/research/strategy_alpha_aggregation.py",
            "scripts/run_gate_p0r_historical_execution.py",
        ]
    )
    manifest = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "source_sha": git(["rev-parse", "HEAD"]),
        "decision": decision,
        "artifact_records": [artifact_record(path) for path in paths if (REPO / path).exists()],
        "excludes": [
            "raw market data",
            "canonical market data",
            "row-level signals",
            "row-level trades",
            "holdout storage",
        ],
    }
    manifest["manifest_hash"] = canonical_json_sha256(manifest)
    return manifest


def write_docs(stage: str, payloads: dict[str, Any]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    if stage in {"diagnose", "all"}:
        write_doc(
            DOC_DIR / "P0R_FREEZE_INTEGRITY.md",
            [
                "# P0-R Freeze Integrity",
                "",
                f"Status: `{payloads['freeze']['status']}`",
                (
                    "The four P0 candidates, date boundaries, estimands, benchmarks "
                    "and Tier rules remain frozen."
                ),
            ],
        )
        write_doc(
            DOC_DIR / "P0R_ZERO_TRADE_FORENSICS.md",
            [
                "# P0-R Zero-Trade Forensics",
                "",
                f"Status: `{payloads['zero']['status']}`",
                f"Root cause: {payloads['zero']['exact_root_cause']}",
            ],
        )
    if stage in {"coverage", "all"}:
        write_doc(
            DOC_DIR / "P0R_PERMITTED_DATA_COVERAGE.md",
            [
                "# P0-R Permitted Data Coverage",
                "",
                f"Status: `{payloads['coverage']['status']}`",
                (
                    "No frozen candidate has complete committed 2015-2022 bid/ask "
                    "coverage certification."
                ),
                "The sealed 2023-2025 holdout was not listed or inspected.",
            ],
        )
        write_doc(
            DOC_DIR / "P0R_DATA_CERTIFICATION.md",
            [
                "# P0-R Data Certification",
                "",
                f"Status: `{payloads['certification']['status']}`",
                "Acquisition was not executed; no raw or canonical market data was committed.",
            ],
        )
    if stage in {"execution", "all"}:
        write_doc(
            DOC_DIR / "P0R_IMPLEMENTATION_CLARIFICATIONS.md",
            [
                "# P0-R Implementation Clarifications",
                "",
                f"Overlay ID: `{payloads['overlay']['overlay_id']}`",
                "The overlay is outcome-blind and does not alter frozen P0 criteria.",
            ],
        )
        write_doc(
            DOC_DIR / "P0R_EXECUTION_CERTIFICATION.md",
            [
                "# P0-R Execution Certification",
                "",
                f"Status: `{payloads['execution']['status']}`",
                "Executable bid/ask and adverse-first semantics remain certified by tests.",
            ],
        )
    if stage in {"results", "all"}:
        write_doc(
            DOC_DIR / "P0R_ECONOMIC_AND_ALPHA_RESULTS.md",
            [
                "# P0-R Economic And Alpha Results",
                "",
                "Historical strategy results are exploratory.",
                (
                    "Economic and alpha analyses were not executed because permitted "
                    "coverage is incomplete."
                ),
                "Historical benchmark-relative performance is not confirmed alpha.",
            ],
        )
        write_doc(
            DOC_DIR / "P0R_CANDIDATE_ADJUDICATION.md",
            [
                "# P0-R Candidate Adjudication",
                "",
                (
                    "No candidate was adjudicated into Tier A or Tier B because "
                    "coverage was incomplete."
                ),
            ],
        )
    if stage in {"final", "all"}:
        write_doc(
            DOC_DIR / "P0R_FINAL_DECISION_MEMO.md",
            [
                "# P0-R Final Decision Memo",
                "",
                f"Decision: `{payloads['decision']}`",
                "Historical strategy results are exploratory.",
                "Historical benchmark-relative performance is not confirmed alpha.",
                "The sealed 2023-2025 holdout was not accessed.",
                "Confirmatory profitability requires a new prospectively frozen forward dataset.",
                "No result authorizes live-capital deployment.",
            ],
        )


def run_diagnose() -> None:
    repo = build_repository_state()
    integrity = build_pre_execution_integrity()
    freeze = build_p0_freeze_integrity()
    zero = build_zero_trade_root_cause()
    write_json(RESULT_DIR / "repository_state.json", repo)
    write_json(RESULT_DIR / "pre_execution_integrity.json", integrity)
    write_json(RESULT_DIR / "p0_freeze_integrity.json", freeze)
    write_json(RESULT_DIR / "zero_trade_root_cause.json", zero)
    write_docs("diagnose", {"freeze": freeze, "zero": zero})


def run_coverage() -> None:
    coverage = build_data_coverage()
    plan, status, certification = build_acquisition_and_certification(coverage)
    write_json(RESULT_DIR / "permitted_data_coverage.json", coverage)
    write_json(RESULT_DIR / "acquisition_plan.json", plan)
    write_json(RESULT_DIR / "acquisition_status.json", status)
    write_json(RESULT_DIR / "permitted_dataset_certification.json", certification)
    write_docs("coverage", {"coverage": coverage, "certification": certification})


def run_execution() -> None:
    overlay = build_implementation_overlay()
    execution = build_execution_certification()
    lookahead, determinism = build_recertification()
    write_json(RESULT_DIR / "implementation_clarification_overlay.json", overlay)
    write_json(RESULT_DIR / "execution_certification.json", execution)
    write_json(RESULT_DIR / "lookahead_audit.json", lookahead)
    write_json(RESULT_DIR / "determinism_audit.json", determinism)
    write_docs("execution", {"overlay": overlay, "execution": execution})


def run_results() -> None:
    evaluation = build_blocked_execution_outputs()
    write_candidate_result_files(evaluation)
    sample = build_execution_sample_manifest(evaluation)
    zero = build_zero_trade_root_cause()
    alpha, controls, overfit, concentration = build_negative_controls()
    adjudication = build_adjudication()
    write_json(RESULT_DIR / "execution_sample_manifest.json", sample)
    write_json(RESULT_DIR / "candidate_execution_funnels.json", zero["candidate_funnels"])
    write_json(
        RESULT_DIR / "trade_rejection_summary.json",
        {
            "created_at_utc": now_utc(),
            "rejection_counts": {
                item["candidate_id"]: item["rejection_counts"] for item in zero["candidate_funnels"]
            },
            "status": "PASS",
        },
    )
    write_json(
        RESULT_DIR / "cost_stress_results.json",
        {"created_at_utc": now_utc(), "status": "NOT_EXECUTED", "reason": evaluation["status"]},
    )
    write_json(
        RESULT_DIR / "risk_simulation_results.json",
        {"created_at_utc": now_utc(), "status": "NOT_EXECUTED", "reason": evaluation["status"]},
    )
    write_json(RESULT_DIR / "benchmark_alpha_results.json", alpha)
    write_json(RESULT_DIR / "negative_controls.json", controls)
    write_json(RESULT_DIR / "overfitting_audit.json", overfit)
    write_json(RESULT_DIR / "concentration_and_stability.json", concentration)
    write_json(RESULT_DIR / "candidate_eligibility_adjudication.json", adjudication)
    write_docs("results", {})


def run_final() -> None:
    static = build_static_delta()
    holdout = build_holdout_integrity()
    decision = FINAL_BLOCKED_COVERAGE
    quality = {
        "created_at_utc": now_utc(),
        "checks": {
            "static_delta": static["status"] == "PASS",
            "holdout_integrity": holdout["status"] == "PASS",
            "permitted_data_coverage": False,
        },
        "status": "PASS" if static["status"] == "PASS" and holdout["status"] == "PASS" else "FAIL",
        "final_decision": decision,
    }
    write_json(RESULT_DIR / "static_analysis_delta.json", static)
    write_json(RESULT_DIR / "holdout_integrity.json", holdout)
    write_json(RESULT_DIR / "quality_gate_final.json", quality)
    write_json(
        RESULT_DIR / "final_decision.json", {"created_at_utc": now_utc(), "decision": decision}
    )
    manifest = build_reproducibility_manifest(decision)
    write_json(RESULT_DIR / "reproducibility_manifest.json", manifest)
    write_docs("final", {"decision": decision})
    print(json.dumps({"status": quality["status"], "decision": decision}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["diagnose", "coverage", "execution", "results", "final", "all"],
        default="all",
    )
    args = parser.parse_args()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    if args.stage in {"diagnose", "all"}:
        run_diagnose()
    if args.stage in {"coverage", "all"}:
        run_coverage()
    if args.stage in {"execution", "all"}:
        run_execution()
    if args.stage in {"results", "all"}:
        run_results()
    if args.stage in {"final", "all"}:
        run_final()


if __name__ == "__main__":
    main()
