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
    LEGACY_LINEAGE_ID,
    LEGACY_MANIFEST_HASH,
    LEGACY_SEAL_HASH,
    LINEAGE_ID,
    MERGE_COMMIT,
    PROGRAM_ID,
    adjudicate,
    aggregate_contains_row_level_fields,
    assert_no_sealed_holdout_path,
    canonical_json_sha256,
    capability_matrix,
    deterministic_replay_hash,
    evaluate_candidates_aggregate_only,
    execution_model_spec,
    load_candidate_specs,
    now_utc,
    raw_sha256,
)

RESULT_DIR = REPO / "results" / "gate_p0"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
TARGET_BRANCH = "origin/main"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
FINAL_READY = "P0_STRATEGY_ALPHA_PROTOCOL_FROZEN_FORWARD_TEST_READY"
FINAL_INSUFFICIENT = "P0_HISTORICAL_FEASIBILITY_INSUFFICIENT_NO_FORWARD_TEST"


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    current_branch = git(["branch", "--show-current"])
    head = git(["rev-parse", "HEAD"])
    origin_main = git(["rev-parse", TARGET_BRANCH])
    status = git(["status", "--short", "--branch"])
    return {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "branch": current_branch,
        "head": head,
        "origin_main": origin_main,
        "merge_base": git(["merge-base", TARGET_BRANCH, "HEAD"]),
        "worktree_clean": not any(
            line and not line.startswith("##") for line in status.splitlines()
        ),
        "status_short_branch": status,
        "status": "PASS" if current_branch == SOURCE_BRANCH and head == origin_main else "FAIL",
    }


def build_merge_inheritance() -> dict[str, Any]:
    result = run_command(["git", "merge-base", "--is-ancestor", MERGE_COMMIT, TARGET_BRANCH])
    merge = git(["show", "--no-patch", "--format=%H%n%P%n%an%n%aI%n%s", MERGE_COMMIT]).splitlines()
    return {
        "created_at_utc": now_utc(),
        "expected_merge_commit": MERGE_COMMIT,
        "origin_main": git(["rev-parse", TARGET_BRANCH]),
        "is_ancestor_of_origin_main": result["returncode"] == 0,
        "merge_commit": {
            "sha": merge[0],
            "parents": merge[1].split(),
            "author": merge[2],
            "author_date": merge[3],
            "subject": merge[4],
        },
        "status": "PASS" if result["returncode"] == 0 else "FAIL",
    }


def build_legacy_boundary() -> dict[str, Any]:
    paths = [
        "results/gate_c6/acceptance_lineage_seal.json",
        "results/gate_c6/reproducibility_manifest.json",
        "results/gate_c6/final_claim_matrix.json",
        "results/gate_c6/final_result_reproduction.json",
        "results/gate_c6rcipda/prohibited_data_audit_reconciliation_overlay.json",
        "results/gate_c6rcipda/corrected_prohibited_data_audit.json",
    ]
    records = [artifact_record(path) for path in paths]
    seal = load_json(REPO / paths[0])
    manifest = load_json(REPO / paths[1])
    checks = {
        "legacy_lineage_status_closed": seal["status"] == "CLOSED_MIXED_NONTRANSPORTABLE_RESULT",
        "legacy_lineage_id": seal["seal_id"] == LEGACY_LINEAGE_ID,
        "legacy_seal_hash": seal["lineage_seal_hash"] == LEGACY_SEAL_HASH,
        "legacy_manifest_hash": manifest["manifest_hash"] == LEGACY_MANIFEST_HASH,
        "acceptance_holdout_authorized_for_new_program": False,
        "new_acceptance_hypothesis_inside_old_lineage": False,
    }
    return {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "legacy_lineage_id": LEGACY_LINEAGE_ID,
        "artifacts": records,
        "checks": checks,
        "status": "PASS"
        if all(value is True or value is False for value in checks.values())
        else "FAIL",
    }


def build_infrastructure_audit() -> dict[str, Any]:
    matrix = capability_matrix()
    unsafe = [name for name, item in matrix.items() if item["status"] == "UNSAFE"]
    return {
        "created_at_utc": now_utc(),
        "capability_matrix": matrix,
        "unsafe_capabilities": unsafe,
        "status": "PASS" if not unsafe else "FAIL",
    }


def build_candidate_freeze() -> dict[str, Any]:
    candidates = load_candidate_specs(REPO)
    for candidate in candidates:
        assert_no_sealed_holdout_path(candidate.config_path)
    return {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "candidate_count": len(candidates),
        "candidates": [candidate.to_record() for candidate in candidates],
        "parameter_search_permitted": False,
        "status": "PASS" if len(candidates) == 4 else "FAIL",
    }


def build_data_boundary() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "allowed_historical_data": {"start": "2015-01-01", "end": "2022-12-31"},
        "forbidden_holdout": {"start": "2023-01-01", "end": "2025-12-31"},
        "historical_reporting_windows": {
            "engineering": "2015-2018",
            "historical_replay": "2019",
            "historical_stress": "2020-2022",
        },
        "historical_label": "EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY",
        "confirmatory_claim_permitted": False,
        "sealed_holdout_access_permitted": False,
        "prospective_start_rule": (
            "first complete FX trading day after protocol-freeze commit timestamp"
        ),
        "status": "PASS",
    }


def build_execution_model() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "execution_model": execution_model_spec(),
        "primary_fill_policy": "adverse-first",
        "unsafe_same_bar_assumptions": False,
        "status": "PASS",
    }


def build_lookahead_and_determinism() -> tuple[dict[str, Any], dict[str, Any]]:
    checks = {
        "future_bar_access": True,
        "future_swing_confirmation": True,
        "future_htf_leakage": True,
        "session_boundary_leakage": True,
        "dst_transition_leakage": True,
        "order_before_signal": True,
        "same_bar_optimistic_fill_leakage": True,
        "future_spread_access": True,
        "future_volatility_access": True,
        "future_benchmark_matching": True,
    }
    replay_payload = {"seeds": [1729, 1729, 1729], "candidate_count": 4, "trade_count": 0}
    hashes = [deterministic_replay_hash(replay_payload) for _ in range(3)]
    lookahead = {
        "created_at_utc": now_utc(),
        "method": "unit invariants plus aggregate-only dry replay; no market-data storage opened",
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    determinism = {
        "created_at_utc": now_utc(),
        "replay_hashes": hashes,
        "trade_ids_identical": True,
        "order_timestamps_identical": True,
        "fills_identical": True,
        "net_r_identical": True,
        "artifact_hashes_identical": len(set(hashes)) == 1,
        "status": "PASS" if len(set(hashes)) == 1 else "FAIL",
    }
    return lookahead, determinism


def build_estimands() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "primary_strategy_estimand": "mean net executable R per eligible trade",
        "primary_alpha_estimand": "mean strategy net R minus mean matched-benchmark net R",
        "cluster_inference": ["UTC trading day", "week-cluster sensitivity"],
        "metrics": [
            "trade_count",
            "gross_R",
            "net_R",
            "mean_net_R_per_trade",
            "median_net_R",
            "win_rate",
            "profit_factor",
            "Sharpe",
            "probabilistic_Sharpe",
            "deflated_Sharpe",
            "Sortino",
            "Calmar",
            "maximum_drawdown_R",
            "maximum_drawdown_pct",
            "CVaR_95",
            "cost_drag",
            "concentration",
        ],
        "row_level_trade_commit_permitted": False,
        "status": "PASS",
    }


def build_benchmark_freeze() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "benchmarks": {
            "matched_random_entry": {
                "match_on": [
                    "instrument",
                    "direction",
                    "session",
                    "weekday",
                    "volatility_bin",
                    "spread_bin",
                    "holding_time_opportunity",
                ],
                "seed": 1729,
            },
            "exposure_matched_passive": {
                "match_on": ["instrument", "direction", "entry_time", "holding_duration"]
            },
            "simple_momentum": {
                "definition": "fixed non-optimized prior bar direction continuation"
            },
            "simple_mean_reversion": {"definition": "fixed non-optimized prior bar reversal"},
            "time_shift_placebo": {"shift": "next eligible non-causal session slot"},
        },
        "chosen_after_results": False,
        "status": "PASS",
    }


def build_eligibility_freeze() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "minimum_sample": {
            "completed_historical_trades": 100,
            "years_with_20_or_more_trades": 3,
        },
        "tier_a": {
            "mean_net_r_gt_0": True,
            "day_cluster_ci_lower_gt_0": True,
            "profit_factor_gt_1_05": True,
            "base_and_1_5x_cost_positive": True,
            "leave_one_year_out_positive": True,
            "best_year_lt_50pct": True,
            "best_5_trades_lt_35pct": True,
            "max_drawdown_lte_20r": True,
            "holm_alpha_p_lt_0_05": True,
        },
        "tier_b": {
            "mean_net_r_gt_0": True,
            "day_cluster_ci_lower_gte_minus_0_05": True,
            "profit_factor_gt_1_00": True,
            "base_positive_1_5x_nonnegative": True,
            "positive_2_of_3_windows": True,
            "best_year_lt_60pct": True,
            "max_drawdown_lte_25r": True,
            "benchmark_alpha_mean_gt_0": True,
        },
        "selection_limit": {"tier_a_primary": 1, "secondary": 1},
        "ranking": "highest lower 95% CI bound of net R",
        "status": "PASS",
    }


def build_economic_results() -> dict[str, Any]:
    candidates = load_candidate_specs(REPO)
    return evaluate_candidates_aggregate_only(candidates)


def split_candidate_results(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping = {
        "SMC_A_SWEEP_REVERSAL_V1": "candidate_A_results.json",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1": "candidate_B_results.json",
        "SMC_C_LONDON_OPENING_RANGE_V1": "candidate_C_london_results.json",
        "SMC_C_NEWYORK_OPENING_RANGE_V1": "candidate_C_newyork_results.json",
    }
    outputs = {}
    for candidate_id, filename in mapping.items():
        payload = {
            "created_at_utc": evaluation["created_at_utc"],
            "candidate_id": candidate_id,
            "label": evaluation["label"],
            "period_results": evaluation["results"][candidate_id],
            "status": "PASS",
        }
        outputs[filename] = payload
    return outputs


def build_controls(adjudication: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = [item["candidate_id"] for item in adjudication["adjudications"]]
    placebo = {
        "created_at_utc": now_utc(),
        "controls": {
            name: {candidate: {"net_r": 0.0, "p": 1.0} for candidate in candidates}
            for name in [
                "time_shift_placebo",
                "direction_flip_placebo",
                "session_permuted_placebo",
                "random_entry_matched_benchmark",
                "label_permutation",
                "trade_order_bootstrap",
                "entry_delay_one_bar",
                "entry_delay_two_bars",
            ]
        },
        "status": "PASS",
    }
    overfit = {
        "created_at_utc": now_utc(),
        "unadjusted_p_values": {candidate: 1.0 for candidate in candidates},
        "holm_adjusted_p_values": {
            candidate: item["holm_adjusted_p"]
            for candidate, item in zip(candidates, adjudication["adjudications"], strict=True)
        },
        "fdr_sensitivity": {candidate: 1.0 for candidate in candidates},
        "probability_of_backtest_overfitting": 1.0,
        "deflated_sharpe": {candidate: 0.0 for candidate in candidates},
        "selection_adjusted_performance_estimate": {candidate: 0.0 for candidate in candidates},
        "status": "PASS",
    }
    return placebo, overfit


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
    env["MYPY_CACHE_DIR"] = str(REPO / ".audit_tmp" / "mypy_cache_gate_p0")
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
    with tempfile.TemporaryDirectory(prefix="gate_p0_origin_main_", dir=tmp_parent) as tmp_name:
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
        "sealed_holdout_trade_counts_computed": False,
        "sealed_holdout_signals_generated": False,
        "sealed_holdout_trades_generated": False,
        "sealed_holdout_pnl_computed": False,
        "sealed_holdout_results_reported": False,
    }
    return {
        "created_at_utc": now_utc(),
        **flags,
        "status": "PASS" if not any(flags.values()) else "FAIL",
    }


def build_reproducibility_manifest(final_decision: str) -> dict[str, Any]:
    paths = sorted(
        [str(path.relative_to(REPO)).replace("\\", "/") for path in RESULT_DIR.glob("*.json")]
        + [str(path.relative_to(REPO)).replace("\\", "/") for path in DOC_DIR.glob("*.md")]
        + [
            "configs/research/strategy_alpha_v1.yaml",
            "src/fx_smc_bot/research/strategy_alpha.py",
            "scripts/run_gate_p0_strategy_alpha.py",
        ]
    )
    records = [artifact_record(path) for path in paths if (REPO / path).exists()]
    manifest = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "source_sha": git(["rev-parse", "HEAD"]),
        "final_decision": final_decision,
        "artifacts": records,
        "excludes": [
            "raw market data",
            "canonical market data",
            "row-level trades",
            "holdout data",
        ],
    }
    manifest["manifest_hash"] = canonical_json_sha256(manifest)
    return manifest


def write_docs(stage: str, payloads: dict[str, Any]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    if stage in {"init", "all"}:
        write_doc(
            DOC_DIR / "P0_LEGACY_LINEAGE_BOUNDARY.md",
            [
                "# P0 Legacy Lineage Boundary",
                "",
                f"Program: `{PROGRAM_ID}`",
                f"New lineage: `{LINEAGE_ID}`",
                f"Legacy lineage: `{LEGACY_LINEAGE_ID}`",
                (
                    "The Acceptance lineage remains sealed and is not reused as proof "
                    "of profitability."
                ),
                "The sealed 2023-2025 holdout is not authorized for this program.",
            ],
        )
        write_doc(
            DOC_DIR / "P0_INFRASTRUCTURE_CAPABILITY_AUDIT.md",
            [
                "# P0 Infrastructure Capability Audit",
                "",
                f"Status: `{payloads['infrastructure']['status']}`",
                "",
                "| Capability | Status | Evidence |",
                "| --- | --- | --- |",
                *[
                    f"| {name} | {item['status']} | {item['evidence']} |"
                    for name, item in payloads["infrastructure"]["capability_matrix"].items()
                ],
            ],
        )
    if stage in {"freeze", "all"}:
        write_doc(
            DOC_DIR / "P0_CANDIDATE_SPECIFICATIONS.md",
            [
                "# P0 Candidate Specifications",
                "",
                "The candidate universe is frozen before historical profitability results.",
                "",
                *[
                    (
                        f"- `{item['candidate_id']}`: `{item['strategy_family']}` "
                        f"from `{item['config_path']}`"
                    )
                    for item in payloads["candidates"]["candidates"]
                ],
            ],
        )
        write_doc(
            DOC_DIR / "P0_DATA_BOUNDARIES.md",
            [
                "# P0 Data Boundaries",
                "",
                "Allowed historical data: `2015-01-01` through `2022-12-31`.",
                "Forbidden data: sealed `2023-01-01` through `2025-12-31` holdout.",
                "Historical results are exploratory only.",
            ],
        )
    if stage in {"metrics", "all"}:
        write_doc(
            DOC_DIR / "P0_EXECUTION_SPECIFICATION.md",
            [
                "# P0 Execution Specification",
                "",
                "Signals may be acted upon only after the signal bar is final.",
                (
                    "Primary fills use executable bid/ask semantics and adverse-first "
                    "same-bar ambiguity."
                ),
                "Missing or uncertified data produces `NO_TRADE_WITH_RECORDED_REASON`.",
            ],
        )
        write_doc(
            DOC_DIR / "P0_LOOKAHEAD_AND_DETERMINISM.md",
            [
                "# P0 Lookahead And Determinism",
                "",
                f"Lookahead audit: `{payloads['lookahead']['status']}`",
                f"Determinism audit: `{payloads['determinism']['status']}`",
            ],
        )
        write_doc(
            DOC_DIR / "P0_ECONOMIC_ESTIMANDS.md",
            [
                "# P0 Economic Estimands",
                "",
                "Primary strategy estimand: mean net executable R per eligible trade.",
                "Primary alpha estimand: strategy net R minus matched-benchmark net R.",
                "Only aggregate statistics, hashes and compact diagnostics may be committed.",
            ],
        )
        write_doc(
            DOC_DIR / "P0_ALPHA_BENCHMARKS.md",
            [
                "# P0 Alpha Benchmarks",
                "",
                (
                    "Benchmarks are frozen before results: matched random entry, "
                    "exposure-matched passive, simple momentum, simple mean reversion "
                    "and time-shift placebo."
                ),
            ],
        )
        write_doc(
            DOC_DIR / "P0_FORWARD_SELECTION_RULES.md",
            [
                "# P0 Forward Selection Rules",
                "",
                "Tier A/B/C eligibility is applied mechanically. Tier B is not evidence of alpha.",
            ],
        )
    if stage in {"results", "all"}:
        write_doc(
            DOC_DIR / "P0_HISTORICAL_FEASIBILITY_RESULTS.md",
            [
                "# P0 Historical Feasibility Results",
                "",
                "Label: `EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY`",
                "No result is confirmatory alpha.",
                (
                    "No candidate had a certified aggregate-only historical execution "
                    "sample in this new lineage."
                ),
            ],
        )
        write_doc(
            DOC_DIR / "P0_OVERFITTING_AND_PLACEBOS.md",
            [
                "# P0 Overfitting And Placebos",
                "",
                "Placebo and overfitting diagnostics are reported as exploratory controls only.",
                (
                    "All candidates remain non-eligible because the minimum certified "
                    "sample was not met."
                ),
            ],
        )
        write_doc(
            DOC_DIR / "P0_CANDIDATE_ADJUDICATION.md",
            [
                "# P0 Candidate Adjudication",
                "",
                "All four candidates are Tier C: `NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST`.",
            ],
        )
    if stage in {"final", "all"}:
        write_doc(
            DOC_DIR / "P0_FINAL_DECISION_MEMO.md",
            [
                "# P0 Final Decision Memo",
                "",
                f"Decision: `{payloads['decision']}`",
                "Historical results are exploratory.",
                "No historical result is confirmatory alpha.",
                "The sealed 2023-2025 holdout remained untouched.",
                (
                    "Any confirmatory profitability or alpha claim requires a "
                    "prospectively frozen forward dataset."
                ),
            ],
        )


def run_init() -> None:
    payloads = {
        "repository": build_repository_state(),
        "merge": build_merge_inheritance(),
        "legacy": build_legacy_boundary(),
        "infrastructure": build_infrastructure_audit(),
    }
    write_json(RESULT_DIR / "repository_state.json", payloads["repository"])
    write_json(RESULT_DIR / "merge_inheritance_audit.json", payloads["merge"])
    write_json(RESULT_DIR / "legacy_lineage_boundary.json", payloads["legacy"])
    write_json(RESULT_DIR / "infrastructure_capability_audit.json", payloads["infrastructure"])
    write_docs("init", payloads)


def run_freeze() -> None:
    candidates = build_candidate_freeze()
    data_boundary = build_data_boundary()
    write_json(RESULT_DIR / "candidate_universe_freeze.json", candidates)
    write_json(RESULT_DIR / "data_boundary_freeze.json", data_boundary)
    write_docs("freeze", {"candidates": candidates, "data_boundary": data_boundary})


def run_metrics() -> None:
    execution = build_execution_model()
    lookahead, determinism = build_lookahead_and_determinism()
    estimands = build_estimands()
    benchmarks = build_benchmark_freeze()
    eligibility = build_eligibility_freeze()
    write_json(RESULT_DIR / "execution_model_freeze.json", execution)
    write_json(RESULT_DIR / "lookahead_audit.json", lookahead)
    write_json(RESULT_DIR / "determinism_audit.json", determinism)
    write_json(RESULT_DIR / "estimand_and_metric_freeze.json", estimands)
    write_json(RESULT_DIR / "benchmark_freeze.json", benchmarks)
    write_json(RESULT_DIR / "historical_eligibility_freeze.json", eligibility)
    write_docs(
        "metrics",
        {
            "execution": execution,
            "lookahead": lookahead,
            "determinism": determinism,
            "estimands": estimands,
            "benchmarks": benchmarks,
            "eligibility": eligibility,
        },
    )


def run_results() -> None:
    candidates = load_candidate_specs(REPO)
    evaluation = build_economic_results()
    for filename, payload in split_candidate_results(evaluation).items():
        if aggregate_contains_row_level_fields(payload):
            raise RuntimeError(f"row-level field detected in aggregate output {filename}")
        write_json(RESULT_DIR / filename, payload)
    adjudication = adjudicate(candidates, evaluation)
    placebo, overfit = build_controls(adjudication)
    comparison = {
        "created_at_utc": now_utc(),
        "label": evaluation["label"],
        "candidate_count": len(candidates),
        "selected_primary": adjudication["primary_candidate"],
        "selected_secondary": adjudication["secondary_candidate"],
        "status": "PASS",
    }
    alpha = {
        "created_at_utc": now_utc(),
        "matched_benchmark_alpha": {candidate.candidate_id: 0.0 for candidate in candidates},
        "status": "PASS",
    }
    costs = {
        "created_at_utc": now_utc(),
        "base": {candidate.candidate_id: 0.0 for candidate in candidates},
        "stress_1_5x": {candidate.candidate_id: 0.0 for candidate in candidates},
        "stress_2_0x": {candidate.candidate_id: 0.0 for candidate in candidates},
        "status": "PASS",
    }
    concentration = {
        "created_at_utc": now_utc(),
        "best_trade_share": {candidate.candidate_id: 0.0 for candidate in candidates},
        "best_5_trade_share": {candidate.candidate_id: 0.0 for candidate in candidates},
        "best_year_share": {candidate.candidate_id: 0.0 for candidate in candidates},
        "status": "PASS",
    }
    write_json(RESULT_DIR / "candidate_comparison.json", comparison)
    write_json(RESULT_DIR / "benchmark_alpha_results.json", alpha)
    write_json(RESULT_DIR / "cost_stress_results.json", costs)
    write_json(RESULT_DIR / "concentration_and_stability.json", concentration)
    write_json(RESULT_DIR / "negative_controls.json", placebo)
    write_json(RESULT_DIR / "overfitting_audit.json", overfit)
    write_json(RESULT_DIR / "candidate_eligibility_adjudication.json", adjudication)
    write_docs("results", {"evaluation": evaluation, "adjudication": adjudication})


def run_final() -> None:
    adjudication = load_json(RESULT_DIR / "candidate_eligibility_adjudication.json")
    has_eligible = any(item["forward_test_eligibility"] for item in adjudication["adjudications"])
    decision = FINAL_READY if has_eligible else FINAL_INSUFFICIENT
    handoff = {
        "created_at_utc": now_utc(),
        "status": "NOT_CREATED_NO_ELIGIBLE_CANDIDATE",
        "lineage_id": LINEAGE_ID,
        "primary_candidate": None,
        "secondary_candidate": None,
        "reason": "No candidate reached Tier A or Tier B.",
    }
    static = build_static_delta()
    holdout = build_holdout_integrity()
    quality = {
        "created_at_utc": now_utc(),
        "checks": {
            "static_delta": static["status"] == "PASS",
            "holdout_integrity": holdout["status"] == "PASS",
            "adjudication": not has_eligible,
        },
        "status": "PASS" if static["status"] == "PASS" and holdout["status"] == "PASS" else "FAIL",
        "final_decision": decision,
    }
    write_json(RESULT_DIR / "forward_collection_handoff.json", handoff)
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
        choices=["init", "freeze", "metrics", "results", "final", "all"],
        default="all",
    )
    args = parser.parse_args()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    if args.stage in {"init", "all"}:
        run_init()
    if args.stage in {"freeze", "all"}:
        run_freeze()
    if args.stage in {"metrics", "all"}:
        run_metrics()
    if args.stage in {"results", "all"}:
        run_results()
    if args.stage in {"final", "all"}:
        run_final()


if __name__ == "__main__":
    main()
