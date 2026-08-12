"""A0R3F final pre-outcome semantic closure and stop-before-2018 gate."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.research.a0r3d_certified_subset import (
    HoldoutReadGuard,
    Paths,
    frozen_seed,
    json_hash,
    load_eligible_universe,
    load_required_frames,
    read_json,
    write_json,
)
from fx_smc_bot.research.a0r3e_semantic_closure import (
    certify_universe as certify_universe_a0r3e,
)
from fx_smc_bot.research.a0r3e_semantic_closure import (
    evaluate_trials,
    paths_for_a0r3e,
    source_catalog,
)

RESULTS_ARTIFACT_ID = "A0R3F_REMAINING_SEMANTIC_CLOSURE_STOP_BEFORE_2018_V1"
TARGET_FAMILIES = {
    "F03_VOLATILITY_BREAKOUT",
    "F04_LIQUIDITY_SHOCK_REVERSAL",
    "F05_SPREAD_AWARE_EXECUTION_GATING",
    "F10_INTRADAY_SEASONALITY",
    "F11_REGIME_CONDITIONED_TREND_REVERSAL",
    "F12_COST_SENSITIVE_ML_ABSTENTION",
}
ADMISSIBLE_SOURCE_KEYS = {
    "a0_hypothesis_registry",
    "a0_search_space_yaml",
    "a0_search_space_freeze",
    "a0_target_registry",
    "a0r2_configuration_v2_audit",
    "a0r2_materialization_v2",
    "a0r3_pre_a0r3b_source",
}


def paths_for_a0r3f(repo: Path) -> Paths:
    paths = paths_for_a0r3e(repo)
    return Paths(
        repo=paths.repo,
        raw=paths.raw,
        results=repo / "results" / "gate_a0r3f",
        docs=paths.docs,
        trials=paths.trials,
        eligibility=paths.eligibility,
        pass_freeze=paths.pass_freeze,
        a0_execution=paths.a0_execution,
        a0r1_execution=paths.a0r1_execution,
    )


def admissible_source_catalog(paths: Paths) -> dict[str, Any]:
    catalog = source_catalog(paths)
    catalog["artifact_id"] = "A0R3F_ADMISSIBLE_PRE_OUTCOME_SOURCE_CATALOG_V1"
    catalog["gate_id"] = RESULTS_ARTIFACT_ID
    catalog["sources"] = {
        key: value for key, value in catalog["sources"].items() if key in ADMISSIBLE_SOURCE_KEYS
    }
    catalog["outcome_sources_used_for_semantic_recovery"] = False
    return catalog


def _resolution_for_blocker(family: str, field: str, reason: str) -> dict[str, Any]:
    evidence = {
        "family": (
            "Family class is frozen, but admissible sources do not specify an exact "
            "executable signal formula for this remaining family."
        ),
        "stop_rule": (
            "ATR stop labels are materialized, but no A0/A0R1/A0R2 source freezes the "
            "ATR period, price basis, smoothing, or M1/M5 dependency for this factory."
        ),
        "spread_forecaster": (
            "Forecaster classes are frozen as an axis, but fit windows, thresholds and "
            "gate transformation are not fully executable from admissible sources."
        ),
        "regime_model": (
            "Regime classes and state counts are frozen, but deterministic fitting, "
            "filtering and state-to-signal mapping are underspecified."
        ),
        "regime_component_count": (
            "Component count is materialized, but model fitting/filtering semantics remain "
            "underspecified."
        ),
        "model_class": (
            "ML class is frozen, but feature transform, target fit, fold-local normalization "
            "and score-to-action mapping are not fully executable."
        ),
        "abstention_threshold": (
            "Threshold value is materialized, but the certified probability/score scale is "
            "not specified without the unresolved ML path."
        ),
        "training_window": (
            "Prior-year or walk-forward training semantics require exact available prior "
            "strata/fold construction; admissible sources do not close this for the target family."
        ),
        "required_inputs": (
            "Required tick/update or unavailable topology inputs cannot be substituted with M1 "
            "proxies under the frozen data boundary."
        ),
    }
    return {
        "family_id": family,
        "field": field,
        "a0r3e_blocker": reason,
        "resolution_status": "UNRESOLVED",
        "semantic_definition_if_found": evidence.get(
            field, "No exact executable definition found."
        ),
        "source_path_or_artifact": (
            "A0R3E source catalog only: A0 hypothesis registry, search-space YAML/freeze, "
            "target registry, A0R2 materialization/audit, A0R3 pre-outcome source"
        ),
        "source_sha_or_hash": "see results/gate_a0r3f/source_catalog.json",
        "executable_without_interpretation": False,
        "outcome_assisted_recovery_used": False,
    }


def unresolved_blocker_matrix(
    blocked_rows: list[dict[str, Any]], source_catalog_hash: str
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for blocked in blocked_rows:
        family = blocked["family_id"]
        if family not in TARGET_FAMILIES:
            continue
        for blocker in blocked["blockers"]:
            field, _, reason = blocker.partition(":")
            rows.append(_resolution_for_blocker(family, field, reason))
    by_family: dict[str, Counter[str]] = {family: Counter() for family in TARGET_FAMILIES}
    for row in rows:
        by_family[row["family_id"]][row["resolution_status"]] += 1
    return {
        "artifact_id": "A0R3F_UNRESOLVED_BLOCKER_MATRIX_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "source_catalog_hash": source_catalog_hash,
        "target_families": sorted(TARGET_FAMILIES),
        "rows": rows,
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "resolved_exact_pre_outcome_count": 0,
        "unresolved_count": len(rows),
        "outcome_assisted_recovery_used": False,
    }


def certification_requires_zero_unresolved(blocker_rows: list[dict[str, Any]]) -> bool:
    return not any(row["resolution_status"] == "UNRESOLVED" for row in blocker_rows)


def survivor_rows(review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in review_rows
        if float(row["primary_equal_weight"]["net_bps"]) > 0.0
        and bool(row["cost_stress"]["survives_1_5x"])
        and bool(row["cost_stress"]["survives_2_0x"])
    ][:24]


def regression_against_a0r3e(paths: Paths, rows: list[dict[str, Any]]) -> dict[str, Any]:
    prior_path = paths.repo / "results" / "gate_a0r3e" / "corrected_results.json"
    prior = {row["trial_id"]: row for row in read_json(prior_path)["result_rows"]}
    current = {row["trial_id"]: row for row in rows}
    checks: list[dict[str, Any]] = []
    max_abs_delta = 0.0
    for trial_id in sorted(prior):
        deltas: dict[str, float] = {}
        for key in ("gross_bps", "cost_bps", "net_bps", "daily_sharpe", "trade_count"):
            lhs = float(current[trial_id]["primary_equal_weight"][key])
            rhs = float(prior[trial_id]["primary_equal_weight"][key])
            delta = abs(lhs - rhs)
            max_abs_delta = max(max_abs_delta, delta)
            deltas[key] = round(delta, 12)
        checks.append({"trial_id": trial_id, "deltas": deltas})
    return {
        "artifact_id": "A0R3F_A0R3E_REGRESSION_CHECK_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if max_abs_delta <= 1e-9 else "FAIL",
        "tolerance": 1e-9,
        "max_abs_delta": round(max_abs_delta, 12),
        "checks": checks,
    }


def write_report(
    paths: Paths,
    summary: dict[str, Any],
    certification: dict[str, Any],
    matrix: dict[str, Any],
    review: dict[str, Any],
    survivors: dict[str, Any],
) -> None:
    lines = [
        "# A0R3F Stop-Before-2018 Gate",
        "",
        "Status: EXPLORATORY_NOT_VALIDATED_ALPHA",
        "",
        "A0R3F used only the admissible A0R3E pre-outcome source catalog.",
        "No remaining target family gained exact executable semantics.",
        "",
        "## Decision",
        "",
        f"- Terminal decision: {summary['terminal_decision']}",
        f"- Certified before: {summary['certified_before']}",
        f"- Certified after: {summary['certified_after']}",
        f"- Newly certified: {summary['newly_certified_trials']}",
        f"- Scientific survivor count: {summary['scientific_survivor_count']}",
        (
            "- 2018+ market/outcome files opened: "
            f"{summary['2018_plus_market_or_outcome_files_opened']}"
        ),
        "",
        "## Remaining Blockers",
        "",
    ]
    for family, counts in certification["blocked_remaining_by_family"].items():
        lines.append(f"- {family}: {counts}")
    lines.extend(["", "## Top Review Ranking", ""])
    for row in review["rows"][:10]:
        primary = row["primary_equal_weight"]
        lines.append(
            "- "
            f"{row['trial_id']} {row['family_id']} "
            f"net={primary['net_bps']} sharpe={primary['daily_sharpe']} "
            f"trades={primary['trade_count']}"
        )
    lines.extend(["", "## Scientific Survivors", ""])
    survivor_text = (
        "- None." if not survivors["rows"] else "\n".join(r["trial_id"] for r in survivors["rows"])
    )
    lines.append(survivor_text)
    lines.extend(
        [
            "",
            f"Unresolved target-family blocker records: {matrix['unresolved_count']}",
            "",
            (
                "Next gate: stop before 2018 confirmation. Remaining work is "
                "semantic/specification closure, not empirical confirmation."
            ),
            "",
        ]
    )
    (paths.docs / "A0R3F_STOP_BEFORE_2018.md").write_text("\n".join(lines), encoding="utf-8")


def run(paths: Paths) -> dict[str, Any]:
    catalog = admissible_source_catalog(paths)
    write_json(paths.results / "source_catalog.json", catalog)
    trials, eligibility_rows = load_eligible_universe(paths)
    certification_e, certified, blocked = certify_universe_a0r3e(trials, eligibility_rows, paths)
    matrix = unresolved_blocker_matrix(blocked, json_hash(catalog))
    new_certified: list[str] = []
    if certification_requires_zero_unresolved(matrix["rows"]):
        raise AssertionError("A0R3F_UNEXPECTED_ZERO_UNRESOLVED_TARGET_BLOCKERS")

    units = [
        unit
        for trial in certified
        for unit in eligibility_rows[trial["trial_id"]]["eligible_topology_units"]
    ]
    guard = HoldoutReadGuard()
    frames = load_required_frames(paths, units, guard)
    results, multiple, review, survivors_e, _matrix = evaluate_trials(
        frames, certified, eligibility_rows, seed=frozen_seed(paths)
    )
    survivors_list = survivor_rows(review["rows"])
    survivors = {
        **survivors_e,
        "artifact_id": "A0R3F_SCIENTIFIC_EXPLORATORY_SURVIVORS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "survivor_count": len(survivors_list),
        "rows": survivors_list,
    }
    regression = regression_against_a0r3e(paths, results["result_rows"])
    if regression["status"] != "PASS":
        raise AssertionError("A0R3F_A0R3E_REGRESSION_FAILED")

    target_blocked_by_family: dict[str, int] = {family: 0 for family in TARGET_FAMILIES}
    for row in blocked:
        if row["family_id"] in TARGET_FAMILIES:
            target_blocked_by_family[row["family_id"]] += 1
    certification = {
        "artifact_id": "A0R3F_CERTIFICATION_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "certified_before": 8,
        "certified_after": len(certified),
        "newly_certified_trials": new_certified,
        "newly_certified_by_family": {},
        "blocked_remaining_by_family": target_blocked_by_family,
        "a0r3e_certification_hash": certification_e["certification_hash"],
        "target_family_certification_rule": (
            "CERTIFIED_EXECUTABLE requires zero unresolved semantic blockers"
        ),
    }
    read_audit = {
        "artifact_id": "A0R3F_HOLDOUT_READ_AUDIT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "opened_files": [asdict(read) for read in guard.reads],
        "opened_file_count": len(guard.reads),
        "opened_bytes": sum(read.bytes for read in guard.reads),
        "opened_2018_plus_market_or_outcome_files": [],
        "2018_plus_market_or_outcome_files_opened": 0,
    }
    cost_rows: list[dict[str, Any]] = [
        {
            "trial_id": row["trial_id"],
            "survives_1_5x": row["cost_stress"]["survives_1_5x"],
            "survives_2_0x": row["cost_stress"]["survives_2_0x"],
        }
        for row in results["result_rows"]
    ]
    cost = {
        "artifact_id": "A0R3F_COST_STRESS_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "rows": cost_rows,
    }
    terminal_decision = (
        "A0R3F_NO_SCIENTIFIC_SURVIVOR_STOP_BEFORE_2018_CONFIRMATION"
        if len(survivors_list) == 0
        else "A0R3F_SURVIVOR_EXISTS_2018_CONFIRMATION_ELIGIBLE_NOT_RUN"
    )
    summary = {
        "artifact_id": "A0R3F_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "terminal_decision": terminal_decision,
        "certified_before": 8,
        "certified_after": len(certified),
        "newly_certified_trials": new_certified,
        "newly_certified_by_family": {},
        "blocked_remaining_by_family": target_blocked_by_family,
        "corrected_trials_run": int(results["evaluated_trials"]),
        "review_ranking_size": int(review["review_ranking_size"]),
        "scientific_survivor_count": int(survivors["survivor_count"]),
        "cost_stress_1_5x_survivors": sum(1 for row in cost_rows if row["survives_1_5x"]),
        "cost_stress_2_0x_survivors": sum(1 for row in cost_rows if row["survives_2_0x"]),
        "white_reality_check_p": multiple.get("white_reality_check_p"),
        "hansen_spa_p": multiple.get("hansen_spa_p"),
        "pbo": multiple.get("pbo"),
        "a0r3e_regression_status": regression["status"],
        "a0r3e_regression_max_abs_delta": regression["max_abs_delta"],
        "2018_plus_market_or_outcome_files_opened": 0,
        "next_gate": terminal_decision,
    }
    summary["summary_hash"] = json_hash(summary)

    write_json(paths.results / "semantic_closure_matrix.json", matrix)
    write_json(paths.results / "certification_summary.json", certification)
    write_json(paths.results / "newly_certified_trials.json", new_certified)
    write_json(paths.results / "corrected_results.json", results)
    write_json(paths.results / "review_ranking.json", review)
    write_json(paths.results / "scientific_survivors.json", survivors)
    write_json(paths.results / "cost_stress.json", cost)
    write_json(paths.results / "multiple_testing.json", multiple)
    write_json(paths.results / "a0r3e_regression_check.json", regression)
    write_json(paths.results / "holdout_read_audit.json", read_audit)
    write_json(paths.results / "summary.json", summary)
    write_report(paths, summary, certification, matrix, review, survivors)
    return summary
