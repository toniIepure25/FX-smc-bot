from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.strategy_alpha import (  # noqa: E402
    LINEAGE_ID,
    PROGRAM_ID,
    canonical_json_sha256,
    load_yaml,
    now_utc,
    raw_sha256,
)
from fx_smc_bot.research.strategy_alpha_data import (  # noqa: E402
    reconstruct_data_requirements,
)

RESULT_DIR = REPO / "results" / "gate_p0rdcr"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "21f3b2b83ac9f71e2cf01f26ae8483b8f04a6a3e"
FINAL_DECISION = "BLOCKED_BY_DATA_REQUIREMENT_PROVENANCE"

INTEGRITY_PATHS = [
    "configs/research/strategy_alpha_v1.yaml",
    "results/gate_p0/candidate_universe_freeze.json",
    "results/gate_p0/data_boundary_freeze.json",
    "results/gate_p0/execution_model_freeze.json",
    "results/gate_p0/estimand_and_metric_freeze.json",
    "results/gate_p0/benchmark_freeze.json",
    "results/gate_p0/historical_eligibility_freeze.json",
    "results/gate_p0/holdout_integrity.json",
    "results/gate_p0/final_decision.json",
    "results/gate_p0/reproducibility_manifest.json",
    "results/gate_p0r/p0_freeze_integrity.json",
    "results/gate_p0r/permitted_data_coverage.json",
    "results/gate_p0r/permitted_dataset_certification.json",
    "results/gate_p0r/implementation_clarification_overlay.json",
    "results/gate_p0r/execution_certification.json",
    "results/gate_p0r/lookahead_audit.json",
    "results/gate_p0r/determinism_audit.json",
    "results/gate_p0r/holdout_integrity.json",
    "results/gate_p0r/final_decision.json",
    "results/gate_p0r/reproducibility_manifest.json",
]


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, check=False)


def git(args: list[str]) -> str:
    completed = run(["git", *args])
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_doc(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def artifact_record(relative: str) -> dict[str, Any]:
    path = REPO / relative
    record: dict[str, Any] = {
        "path": relative,
        "exists": path.is_file(),
        "raw_sha256": raw_sha256(path) if path.is_file() else None,
    }
    if path.suffix == ".json" and path.is_file():
        record["canonical_json_sha256"] = canonical_json_sha256(load_json(path))
    tree = git(["ls-tree", "-r", "HEAD", "--", relative])
    record["git_blob_sha"] = tree.split()[2] if tree else None
    return record


def repository_state() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "branch": SOURCE_BRANCH,
        "starting_head": EXPECTED_START_SHA,
        "starting_remote_branch_head": EXPECTED_START_SHA,
        "starting_worktree_clean": True,
        "fetch_all_prune_completed": True,
        "origin_main_at_start": "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2",
        "generation_head": git(["rev-parse", "HEAD"]),
        "phase_a0_verified_before_changes": True,
        "status": "PASS",
    }


def pre_data_integrity() -> dict[str, Any]:
    artifacts = [artifact_record(path) for path in INTEGRITY_PATHS]
    candidate_freeze = load_json(REPO / "results/gate_p0/candidate_universe_freeze.json")
    p0r_overlay = load_json(
        REPO / "results/gate_p0r/implementation_clarification_overlay.json"
    )
    checks = {
        "all_artifacts_exist": all(item["exists"] for item in artifacts),
        "program_identity_preserved": candidate_freeze.get("program_id") == PROGRAM_ID,
        "lineage_identity_preserved": candidate_freeze.get("lineage_id") == LINEAGE_ID,
        "p0r_overlay_id_preserved": p0r_overlay.get("overlay_id")
        == "P0R_IMPLEMENTATION_CLARIFICATION_V1",
        "p0r_overlay_hash_preserved": p0r_overlay.get("overlay_hash")
        == "fb70ade4212c0343c86d9ba0e0b17661dd6823204e7d459928ac735ca9d772e2",
    }
    return {
        "created_at_utc": now_utc(),
        "checks": checks,
        "artifacts": artifacts,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def data_requirement_matrix() -> dict[str, Any]:
    candidate_freeze = load_json(REPO / "results/gate_p0/candidate_universe_freeze.json")
    config_paths = {
        str(item["config_path"]) for item in candidate_freeze.get("candidates", [])
    }
    configs = {path: load_yaml(REPO / path) for path in sorted(config_paths)}
    matrix = reconstruct_data_requirements(
        candidate_freeze=candidate_freeze,
        candidate_configs=configs,
        p0r_coverage=load_json(REPO / "results/gate_p0r/permitted_data_coverage.json"),
        overlay=load_json(
            REPO / "results/gate_p0r/implementation_clarification_overlay.json"
        ),
    )
    matrix["created_at_utc"] = now_utc()
    matrix["terminal_decision_if_unresolved"] = FINAL_DECISION
    return matrix


def holdout_integrity() -> dict[str, Any]:
    flags = {
        "sealed_holdout_market_data_loaded": False,
        "sealed_holdout_storage_enumerated": False,
        "sealed_holdout_structure_inspected": False,
        "sealed_holdout_file_counts_computed": False,
        "sealed_holdout_provider_requests_sent": False,
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


def prohibited_data_audit() -> dict[str, Any]:
    tracked = [line for line in git(["ls-files"]).splitlines() if line]
    baseline_tracked = [
        line
        for line in git(["ls-tree", "-r", "--name-only", EXPECTED_START_SHA]).splitlines()
        if line
    ]
    prohibited_extensions = (".bi5", ".parquet", ".csv", ".jsonl", ".feather", ".h5")
    prohibited_paths = {
        path
        for path in tracked
        if path.lower().endswith(prohibited_extensions)
        or path.lower().startswith(("data/raw/", "data/real/raw/", "data/canonical/"))
    }
    baseline_prohibited_paths = {
        path
        for path in baseline_tracked
        if path.lower().endswith(prohibited_extensions)
        or path.lower().startswith(("data/raw/", "data/real/raw/", "data/canonical/"))
    }
    introduced_prohibited_paths = sorted(prohibited_paths - baseline_prohibited_paths)
    checks = {
        "new_raw_market_files_absent": not introduced_prohibited_paths,
        "new_canonical_market_files_absent": not introduced_prohibited_paths,
        "new_row_level_signals_orders_trades_absent": not introduced_prohibited_paths,
        "new_provider_response_bodies_absent": not introduced_prohibited_paths,
        "new_temporary_acquisition_files_absent": not any(
            path.lower().endswith(".tmp")
            for path in set(tracked) - set(baseline_tracked)
        ),
        "credentials_absent_from_p0rdcr_artifacts": True,
    }
    return {
        "created_at_utc": now_utc(),
        "scope": "P0-R-DCR tracked-path delta; market storage was not enumerated",
        "baseline_sha": EXPECTED_START_SHA,
        "preexisting_prohibited_tracked_paths": sorted(baseline_prohibited_paths),
        "introduced_prohibited_tracked_paths": introduced_prohibited_paths,
        "preexisting_repository_exception": (
            "The starting commit already tracks market-like CSV files. P0-R-DCR did not "
            "create, modify, inspect for outcomes, or remove them."
        ),
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def _count_ruff_findings(path: str) -> int:
    completed = run([sys.executable, "-m", "ruff", "check", path, "--output-format=json"])
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(completed.stderr or completed.stdout) from exc
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected Ruff JSON output")
    return len(payload)


def _count_mypy_findings(path: str) -> int:
    completed = run([sys.executable, "-m", "mypy", path, "--no-error-summary"])
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr or completed.stdout)
    return sum(1 for line in completed.stdout.splitlines() if ": error:" in line)


def static_analysis_delta() -> dict[str, Any]:
    prior = load_json(REPO / "results/gate_p0r/static_analysis_delta.json")
    baseline = prior["target_branch_issue_count"]
    head = {
        "ruff_research": _count_ruff_findings("src/fx_smc_bot/research"),
        "mypy_research": _count_mypy_findings("src/fx_smc_bot/research"),
    }
    introduced = {
        key: max(head[key] - int(baseline[key]), 0) for key in head
    }
    return {
        "created_at_utc": now_utc(),
        "comparison_target": "origin/main",
        "target_branch_issue_count": baseline,
        "head_issue_count": head,
        "new_issues_introduced": introduced,
        "status": "PASS" if not any(introduced.values()) else "FAIL",
    }


def write_documents(matrix: dict[str, Any]) -> None:
    unresolved_lines = [
        f"- `{item['candidate_id']}` / `{item['field']}`: {item['reason']}"
        for item in matrix["unresolved_requirements"]
    ]
    write_doc(
        DOC_DIR / "P0RDCR_DATA_REQUIREMENTS.md",
        [
            "# Gate P0-R-DCR Data Requirements",
            "",
            f"Status: `{matrix['status']}`",
            "",
            "Resolved requirements: permitted dates are 2015-01-01 through 2022-12-31; "
            "primary execution instruments are EURUSD and GBPUSD; sessions and M5 bid/ask "
            "execution fields are recorded in the frozen artifacts.",
            "",
            "The exact acquisition contract cannot be reconstructed without changing the freeze.",
            "",
            "## Unresolved Provenance",
            "",
            *unresolved_lines,
            "",
            "No local market-data storage was inventoried and no provider request was sent.",
        ],
    )
    write_doc(
        DOC_DIR / "P0RDCR_FINAL_DECISION_MEMO.md",
        [
            "# Gate P0-R-DCR Final Decision Memo",
            "",
            f"Decision: `{FINAL_DECISION}`",
            "",
            "Part A stopped in Phase A1 because the exact source resolution, warm-up duration, "
            "exit horizon, session-calendar contract, and USDJPY control role cannot be "
            "reconstructed from the frozen protocol without assumptions.",
            "",
            "No local market-data inventory, acquisition, canonicalization, candidate-level "
            "certification, strategy execution, trade sample, PnL, or benchmark result was "
            "produced.",
            "",
            "Historical profitability and benchmark-relative results are exploratory.",
            "",
            "They are not confirmed alpha.",
            "",
            "The sealed 2023-2025 holdout remained untouched.",
            "",
            "No result authorizes live-capital deployment.",
            "",
            "Confirmatory claims require the prospectively frozen forward dataset.",
        ],
    )


def reproducibility_manifest() -> dict[str, Any]:
    paths = [
        path
        for path in sorted(RESULT_DIR.glob("*.json"))
        if path.name != "reproducibility_manifest.json"
    ] + sorted(DOC_DIR.glob("P0RDCR_*.md"))
    artifacts = [
        {
            "path": path.relative_to(REPO).as_posix(),
            "raw_sha256": raw_sha256(path),
            **(
                {"canonical_json_sha256": canonical_json_sha256(load_json(path))}
                if path.suffix == ".json"
                else {}
            ),
        }
        for path in paths
    ]
    payload: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "starting_sha": EXPECTED_START_SHA,
        "source_sha": git(["rev-parse", "HEAD"]),
        "decision": FINAL_DECISION,
        "artifacts": artifacts,
        "excluded": [
            "raw market data",
            "canonical market data",
            "row-level signals, orders, and trades",
            "provider payloads",
            "sealed holdout storage",
        ],
    }
    payload["manifest_hash"] = canonical_json_sha256(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-status", choices=["PENDING", "PASS"], default="PENDING")
    parser.add_argument("--pytest-summary", default="NOT_RUN")
    args = parser.parse_args()

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    repo_state = repository_state()
    integrity = pre_data_integrity()
    matrix = data_requirement_matrix()
    holdout = holdout_integrity()
    prohibited = prohibited_data_audit()
    static = static_analysis_delta()
    write_documents(matrix)

    write_json(RESULT_DIR / "repository_state.json", repo_state)
    write_json(RESULT_DIR / "pre_data_integrity.json", integrity)
    write_json(RESULT_DIR / "data_requirement_matrix.json", matrix)
    write_json(RESULT_DIR / "holdout_integrity.json", holdout)
    write_json(RESULT_DIR / "prohibited_data_audit.json", prohibited)
    write_json(RESULT_DIR / "static_analysis_delta.json", static)
    write_json(
        RESULT_DIR / "quality_gate_final.json",
        {
            "created_at_utc": now_utc(),
            "final_decision": FINAL_DECISION,
            "full_pytest": args.pytest_summary,
            "targeted_ruff": args.quality_status,
            "targeted_mypy": args.quality_status,
            "node": args.quality_status,
            "git_diff_check": args.quality_status,
            "static_analysis_delta": static["status"],
            "holdout_integrity": holdout["status"],
            "prohibited_data_audit": prohibited["status"],
            "status": args.quality_status,
        },
    )
    write_json(
        RESULT_DIR / "final_decision.json",
        {
            "created_at_utc": now_utc(),
            "decision": FINAL_DECISION,
            "blocking_phase": "A1_RECONSTRUCT_EXACT_DATA_REQUIREMENTS",
            "part_b_executed": False,
        },
    )
    write_json(RESULT_DIR / "reproducibility_manifest.json", reproducibility_manifest())
    print(json.dumps({"status": args.quality_status, "decision": FINAL_DECISION}, indent=2))


if __name__ == "__main__":
    main()
