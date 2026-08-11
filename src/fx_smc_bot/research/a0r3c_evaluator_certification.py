"""A0R3C evaluator certification audit.

This gate is pre-outcome for corrected results. It may inspect frozen trial
configurations and evaluator source code, but it must not open market-data files.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.research.a0r3_existing_data import json_hash, sha256_file, write_json

RESULTS_ARTIFACT_ID = "A0R3C_FORENSIC_EVALUATOR_CERTIFICATION_V1"
EVALUATED_FAMILIES = (
    "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
    "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
    "F03_VOLATILITY_BREAKOUT",
    "F04_LIQUIDITY_SHOCK_REVERSAL",
    "F05_SPREAD_AWARE_EXECUTION_GATING",
    "F10_INTRADAY_SEASONALITY",
    "F11_REGIME_CONDITIONED_TREND_REVERSAL",
    "F12_COST_SENSITIVE_ML_ABSTENTION",
)


@dataclass(frozen=True, slots=True)
class AuditPaths:
    repo: Path
    results: Path
    docs: Path
    trials: Path
    a0r3b_results: Path
    evaluator_source: Path
    statistics_source: Path


def paths_for_a0r3c(repo: Path) -> AuditPaths:
    return AuditPaths(
        repo=repo,
        results=repo / "results" / "gate_a0r3c",
        docs=repo / "docs" / "research" / "fx_alpha_discovery",
        trials=repo / "results" / "gate_a0r2" / "trial_materialization_v2.jsonl",
        a0r3b_results=repo / "results" / "gate_a0r3b",
        evaluator_source=repo / "src" / "fx_smc_bot" / "research" / "a0r3b_pass_strata.py",
        statistics_source=repo / "src" / "fx_smc_bot" / "research" / "a0r2_statistics.py",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_a0r3b_eligible_ids(paths: AuditPaths) -> set[str]:
    eligibility = read_json(paths.a0r3b_results / "trial_eligibility.json")
    return {row["trial_id"] for row in eligibility["rows"] if row["status"] == "ELIGIBLE"}


def load_trial_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def compact_value(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= 160 else text[:157] + "..."


def field_status(family: str, field: str) -> tuple[str, str]:
    used_for_all = {
        "entry_threshold": "trial_signal threshold gate",
        "instrument_or_portfolio_scope": "pass-strata topology eligibility/evaluation pair",
        "lookback": "rolling feature construction",
        "required_inputs": "structural eligibility filter",
    }
    if field in used_for_all:
        return "USED", used_for_all[field]

    family_used = {
        "F01_SESSION_OPENING_MOMENTUM_REVERSAL": {
            "session_anchor": "session_mask",
            "variant": "continuation/reversal polarity branch",
        },
        "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": {
            "variant": "continuation/exhaustion polarity branch",
        },
        "F03_VOLATILITY_BREAKOUT": {
            "variant": "failed-breakout polarity branch",
        },
    }
    if field in family_used.get(family, {}):
        return "USED", family_used[family][field]

    ignored = {
        "abstention_threshold",
        "embargo",
        "exit_rule",
        "feature_lags",
        "feature_list",
        "frozen_categories",
        "holding_horizon",
        "model_class",
        "model_hyperparameters",
        "normalization_rule",
        "position_sizing",
        "purging_rule",
        "random_seed",
        "regime_component_count",
        "regime_model",
        "regime_state_use",
        "session_anchor",
        "spread_forecaster",
        "stop_rule",
        "target",
        "target_horizon",
        "training_window",
        "variant",
        "walk_forward_folds",
    }
    if field in ignored:
        return "IGNORED", "no certified A0R3B implementation consumes this field"

    unspecified = {
        "cost_contract": "frozen commission/slippage labels not resolved to certified values",
        "execution_contract": "partially referenced; side-correct fills not implemented",
        "implementation_fixed_parameters": "fixed-parameter rules not executed",
        "implementation_mapping_version": "provenance only",
        "family": "registry identity, not a runtime dimension",
        "cross_pair_edge": "topology code exists but no evaluated A0R3B trials exercised it",
        "triangle": "topology code exists but no evaluated A0R3B trials exercised it",
        "neutrality_constraint": "null in evaluated trials; no runtime semantics certified",
    }
    if field in unspecified:
        return "UNSPECIFIED", unspecified[field]
    return "UNSPECIFIED", "field not recognized by certification map"


def build_consumption_matrix(paths: AuditPaths) -> dict[str, Any]:
    eligible_ids = load_a0r3b_eligible_ids(paths)
    trials = [
        trial for trial in load_trial_jsonl(paths.trials) if trial["trial_id"] in eligible_ids
    ]
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        by_family[trial["family_id"]].append(trial)

    rows: list[dict[str, Any]] = []
    family_summary: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []
    for family in sorted(by_family):
        field_values: dict[str, set[str]] = defaultdict(set)
        for trial in by_family[family]:
            for field, value in trial["full_configuration"].items():
                field_values[field].add(compact_value(value))
        family_counter: Counter[str] = Counter()
        for field in sorted(field_values):
            status, implementation = field_status(family, field)
            values = sorted(field_values[field])
            varied = len(values) > 1
            row = {
                "family_id": family,
                "materialized_field": field,
                "unique_value_count": len(values),
                "values_sample": values[:8],
                "varies_within_evaluated_trials": varied,
                "evaluator_implementation": implementation,
                "consumption_status": status,
            }
            if varied and status != "USED":
                row["certification_blocker"] = "VARYING_CONFIGURATION_FIELD_NOT_CONSUMED"
                blockers.append(
                    {
                        "family_id": family,
                        "field": field,
                        "reason": "varies_within_evaluated_trials_but_not_used",
                    }
                )
            rows.append(row)
            family_counter[status] += 1
        family_summary[family] = {
            "evaluated_trials": len(by_family[family]),
            "field_status_counts": dict(family_counter),
        }
    return {
        "artifact_id": "A0R3C_CONFIGURATION_CONSUMPTION_MATRIX_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "FAIL" if blockers else "PASS",
        "source": "A0R3B eligible registered trial configurations; no market data opened",
        "evaluated_trial_count": len(trials),
        "evaluated_families": sorted(by_family),
        "family_summary": family_summary,
        "rows": rows,
        "blockers": blockers,
    }


def source_defect_audit(paths: AuditPaths) -> dict[str, Any]:
    evaluator = paths.evaluator_source.read_text(encoding="utf-8")
    statistics = paths.statistics_source.read_text(encoding="utf-8")
    defects = []
    if "mid.pct_change()" in evaluator:
        defects.append(
            {
                "defect": "SURROGATE_MID_RETURN_EXECUTION",
                "evidence": "execution_components_bps uses mid.pct_change() for gross PnL",
                "required_fix": "use side-correct ask/bid entry and exit fills",
            }
        )
    if "spread_bps / 2.0" in evaluator:
        defects.append(
            {
                "defect": "SYNTHETIC_HALF_SPREAD_COST_APPROXIMATION",
                "evidence": "costs subtract half-spread approximation rather than fill prices",
                "required_fix": "compute execution prices directly from bid/ask fills",
            }
        )
    if "from fx_smc_bot.research.a0r2_statistics import" in evaluator:
        defects.append(
            {
                "defect": "SYNTHETIC_STATISTICS_IMPORT",
                "evidence": "A0R3B imports a0r2_statistics synthetic-only interfaces",
                "required_fix": (
                    "replace with certified deterministic bootstrap/statistical methods"
                ),
            }
        )
    if "Synthetic-only" in statistics:
        defects.append(
            {
                "defect": "A0R2_STATISTICS_MARKED_SYNTHETIC_ONLY",
                "evidence": "a0r2_statistics.py module docstring says synthetic-only",
                "required_fix": "do not use these outputs for scientific claims",
            }
        )
    if "holding_horizon" not in evaluator or "target_horizon" not in evaluator:
        defects.append(
            {
                "defect": "FROZEN_HORIZONS_NOT_EXECUTED",
                "evidence": "A0R3B source has no certified holding/target horizon state machine",
                "required_fix": "implement frozen holding/exit semantics before rerun",
            }
        )
    return {
        "artifact_id": "A0R3C_SOURCE_DEFECT_AUDIT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "FAIL" if defects else "PASS",
        "evaluator_source_sha256": sha256_file(paths.evaluator_source),
        "statistics_source_sha256": sha256_file(paths.statistics_source),
        "defects": defects,
    }


def certification_artifact(
    paths: AuditPaths, matrix: dict[str, Any], source_audit: dict[str, Any]
) -> dict[str, Any]:
    a0r3b_summary = read_json(paths.a0r3b_results / "summary.json")
    materialization_hash = sha256_file(paths.trials)
    deterministic_seed_source = (
        a0r3b_summary["frozen_dataset_sha256"] + materialization_hash + RESULTS_ARTIFACT_ID
    )
    blockers = []
    blockers.extend(matrix["blockers"])
    blockers.extend(source_audit["defects"])
    blockers.extend(
        [
            {
                "defect": "CERTIFIED_GOLDEN_TESTS_MISSING",
                "reason": "long/short/flip/flat/rollover/delayed-exit golden tests absent",
            },
            {
                "defect": "CORRECTED_STATISTICS_NOT_CERTIFIED",
                "reason": "bootstrap WRC/SPA/Romano-Wolf/PSR/DSR/PBO replacements absent",
            },
        ]
    )
    precert_by_family = {
        family: int(summary["evaluated_trials"])
        for family, summary in matrix["family_summary"].items()
    }
    certified_by_family = {
        family: 0 if blockers else count for family, count in precert_by_family.items()
    }
    return {
        "artifact_id": "A0R3C_EVALUATOR_CERTIFICATION_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "FAIL" if blockers else "PASS",
        "claim": "A0R3B_NUMERICAL_RESULTS_NOT_ELIGIBLE_FOR_SCIENTIFIC_NO_GO",
        "a0r3b_freeze_hash": a0r3b_summary["frozen_dataset_sha256"],
        "registered_trial_universe_sha256": materialization_hash,
        "registered_trial_universe_count": 1200,
        "a0r3b_evaluated_trials": a0r3b_summary["evaluated_trials"],
        "precert_a0r3b_evaluated_by_family": precert_by_family,
        "certified_truly_executable_by_family": certified_by_family,
        "deterministic_seed_sha256": json_hash({"seed_source": deterministic_seed_source}),
        "requirements": {
            "no_silently_ignored_materialized_dimensions": matrix["status"] == "PASS",
            "exact_side_correct_fill_semantics": False,
            "synthetic_statistics_replaced": False,
            "deterministic_regression_golden_tests": False,
            "zero_2018_plus_reads": True,
        },
        "opened_2018_plus_market_or_outcome_files": [],
        "market_data_files_opened_by_a0r3c": 0,
        "corrected_rerun_status": "NOT_RUN_CERTIFICATION_FAILED",
        "differences_versus_a0r3b": [
            (
                "A0R3B numerical outcomes are not superseded by corrected outcomes "
                "because certification failed."
            ),
            "A0R3B used surrogate mid-return execution instead of actual side-correct fills.",
            "A0R3B used synthetic-only statistical approximations from a0r2_statistics.py.",
            "A0R3B ignored or left unspecified materialized dimensions before outcome computation.",
        ],
        "blockers": blockers,
    }


def corrected_rerun_manifest(certification: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": "A0R3C_CORRECTED_RERUN_MANIFEST_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "NOT_RUN",
        "reason": "EVALUATOR_CERTIFICATION_FAILED",
        "certification_status": certification["status"],
        "same_pass_strata_preserved": True,
        "same_1200_trial_universe_preserved": True,
        "no_new_hypotheses": True,
        "no_performance_informed_tuning": True,
        "opened_2018_plus_market_or_outcome_files": [],
    }


def write_report(paths: AuditPaths, artifacts: dict[str, Any]) -> None:
    cert = artifacts["certification"]
    matrix = artifacts["configuration_consumption_matrix"]
    source = artifacts["source_defect_audit"]
    lines = [
        "# A0R3C Forensic Evaluator Certification",
        "",
        f"Certification verdict: `{cert['status']}`",
        "Corrected exploratory rerun: `NOT_RUN_CERTIFICATION_FAILED`",
        "",
        "A0R3B numerical results are not eligible for scientific no-go adjudication.",
        "",
        "## Blocking Source Defects",
        "",
        "| Defect | Evidence | Required fix |",
        "|---|---|---|",
    ]
    for defect in source["defects"]:
        lines.append(
            "| {defect} | {evidence} | {fix} |".format(
                defect=defect["defect"],
                evidence=defect["evidence"],
                fix=defect["required_fix"],
            )
        )
    lines.extend(
        [
            "",
            "## Configuration Consumption Summary",
            "",
            "| Family | Evaluated trials | USED | IGNORED | UNSPECIFIED |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for family, summary in matrix["family_summary"].items():
        counts = summary["field_status_counts"]
        lines.append(
            f"| {family} | {summary['evaluated_trials']} | {counts.get('USED', 0)} | "
            f"{counts.get('IGNORED', 0)} | {counts.get('UNSPECIFIED', 0)} |"
        )
    lines.extend(
        [
            "",
            "## First Blocked Dimensions",
            "",
            "| Family | Field | Reason |",
            "|---|---|---|",
        ]
    )
    for blocker in matrix["blockers"][:40]:
        lines.append(f"| {blocker['family_id']} | {blocker['field']} | {blocker['reason']} |")
    lines.extend(
        [
            "",
            "## Certified Executable Trials",
            "",
            "| Family | A0R3B pre-cert evaluated | Certified executable |",
            "|---|---:|---:|",
        ]
    )
    for family, count in cert["precert_a0r3b_evaluated_by_family"].items():
        certified = cert["certified_truly_executable_by_family"][family]
        lines.append(f"| {family} | {count} | {certified} |")
    lines.extend(
        [
            "",
            "## Holdout Integrity",
            "",
            "- 2018+ market/outcome files opened by A0R3C: `0`",
            "- Provider acquisition run: `False`",
            "- Frozen PASS-strata dataset changed: `False`",
            "- Registered 1200-trial universe changed: `False`",
        ]
    )
    paths.docs.mkdir(parents=True, exist_ok=True)
    (paths.docs / "A0R3C_FORENSIC_EVALUATOR_CERTIFICATION.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run(paths: AuditPaths) -> dict[str, Any]:
    paths.results.mkdir(parents=True, exist_ok=True)
    matrix = build_consumption_matrix(paths)
    source_audit = source_defect_audit(paths)
    certification = certification_artifact(paths, matrix, source_audit)
    rerun = corrected_rerun_manifest(certification)
    artifacts = {
        "configuration_consumption_matrix": matrix,
        "source_defect_audit": source_audit,
        "certification": certification,
        "corrected_rerun_manifest": rerun,
    }
    hashes = {
        name: write_json(paths.results / f"{name}.json", artifact)
        for name, artifact in artifacts.items()
    }
    summary = {
        "artifact_id": "A0R3C_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": certification["status"],
        "artifact_hashes": hashes,
        "evaluator_certification_verdict": certification["status"],
        "corrected_rerun_status": rerun["status"],
        "a0r3b_evaluated_trials": certification["a0r3b_evaluated_trials"],
        "precert_a0r3b_evaluated_by_family": certification[
            "precert_a0r3b_evaluated_by_family"
        ],
        "certified_truly_executable_by_family": certification[
            "certified_truly_executable_by_family"
        ],
        "registered_trial_universe_count": 1200,
        "configuration_blocker_count": len(matrix["blockers"]),
        "source_defect_count": len(source_audit["defects"]),
        "opened_2018_plus_market_or_outcome_files": [],
        "any_2018_plus_market_or_outcome_data_accessed": False,
        "provider_acquisition_run": False,
    }
    write_json(paths.results / "summary.json", summary)
    artifacts["summary"] = summary
    write_report(paths, artifacts)
    return summary
