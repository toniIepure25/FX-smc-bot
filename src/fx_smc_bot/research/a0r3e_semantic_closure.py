"""A0R3E semantic closure and expanded certified exploratory discovery."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import (
    REGISTERED_TRIAL_DENOMINATOR,
    HoldoutReadGuard,
    Paths,
    _sample_moments,
    bh_fdr,
    bootstrap_family_stats,
    compact_execution_window,
    daily_metrics,
    dsr,
    frozen_seed,
    holm_adjust,
    json_hash,
    load_eligible_universe,
    load_required_frames,
    normal_p_value_from_mean,
    psr,
    read_json,
    sha256_file,
    signal_f01,
    simulate_state_machine,
    write_json,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    certify_trial as certify_trial_a0r3d,
)

RESULTS_ARTIFACT_ID = "A0R3E_PRE_OUTCOME_SEMANTIC_CLOSURE_V1"
A0R3D_F01_IDS = {
    "A0R1-01-0002",
    "A0R1-01-0020",
    "A0R1-01-0047",
    "A0R1-01-0065",
    "A0R1-01-0092",
    "A0R1-01-0110",
}


def paths_for_a0r3e(repo: Path) -> Paths:
    return Paths(
        repo=repo,
        raw=repo / "data" / "raw" / "dukascopy-node",
        results=repo / "results" / "gate_a0r3e",
        docs=repo / "docs" / "research" / "fx_alpha_discovery",
        trials=repo / "results" / "gate_a0r2" / "trial_materialization_v2.jsonl",
        eligibility=repo / "results" / "gate_a0r3b" / "trial_eligibility.json",
        pass_freeze=repo / "results" / "gate_a0r3b" / "freeze.json",
        a0_execution=repo / "results" / "gate_a0" / "execution_certification.json",
        a0r1_execution=repo / "results" / "gate_a0r1" / "execution_certification.json",
    )


def source_catalog(paths: Paths) -> dict[str, Any]:
    sources = {
        "a0_hypothesis_registry": paths.repo / "results" / "gate_a0" / "hypothesis_registry.json",
        "a0_search_space_yaml": paths.repo
        / "configs"
        / "research"
        / "fx_intraday_alpha_search_v1.yaml",
        "a0_search_space_freeze": paths.repo / "results" / "gate_a0" / "search_space_freeze.json",
        "a0_target_registry": paths.repo / "results" / "gate_a0" / "target_registry.json",
        "a0r2_materialization_v2": paths.trials,
        "a0r2_configuration_v2_audit": paths.repo
        / "results"
        / "gate_a0r2"
        / "trial_configuration_v2_audit.json",
        "a0r3_pre_a0r3b_source": paths.repo
        / "src"
        / "fx_smc_bot"
        / "research"
        / "a0r3_existing_data.py",
    }
    return {
        "artifact_id": "A0R3E_PRE_OUTCOME_SOURCE_CATALOG_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "sources": {
            key: {"path": str(path), "sha256": sha256_file(path)} for key, path in sources.items()
        },
        "outcome_sources_used": False,
    }


def _matrix_row(
    trial: dict[str, Any],
    field: str,
    definition: str,
    source: str,
    executable: bool,
    status: str,
) -> dict[str, Any]:
    return {
        "trial_id": trial["trial_id"],
        "family_id": trial["family_id"],
        "field": field,
        "semantic_definition": definition,
        "source_path_or_artifact": source,
        "executable_without_interpretation": executable,
        "status": status,
    }


def certify_trial_a0r3e(trial: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]]]:
    d_status, d_blockers, d_rows = certify_trial_a0r3d(trial)
    if d_status == "CERTIFIED_EXECUTABLE":
        inherited_rows = [
            _matrix_row(
                trial,
                row["materialized_field"],
                row["evaluator_implementation"],
                row["pre_outcome_source"],
                row["status"] != "BLOCKED",
                row["status"],
            )
            for row in d_rows
        ]
        return d_status, d_blockers, inherited_rows

    cfg = trial["full_configuration"]
    family = trial["family_id"]
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    def used(field: str, definition: str, source: str) -> None:
        rows.append(_matrix_row(trial, field, definition, source, True, "USED"))

    def inert(field: str, definition: str, source: str) -> None:
        rows.append(_matrix_row(trial, field, definition, source, True, "DOCUMENTED_INERT"))

    def blocked(field: str, reason: str, source: str) -> None:
        blockers.append(f"{field}:{reason}")
        rows.append(_matrix_row(trial, field, reason, source, False, "BLOCKED"))

    if family == "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION":
        frozen = cfg.get("frozen_categories", {})
        m1_direction_run = frozen.get("data_variants") == "M1-compatible direction-run"
        if m1_direction_run:
            used(
                "family",
                "M1-compatible direction-run uses signed M1 mid-return run length",
                "configs/research/fx_intraday_alpha_search_v1.yaml; "
                "src/fx_smc_bot/research/a0r3_existing_data.py",
            )
            used(
                "frozen_categories",
                (
                    "data_variants/horizons/variants map to M1 direction run, "
                    "holding_horizon and continuation/exhaustion"
                ),
                "results/gate_a0r2/trial_materialization_v2.jsonl",
            )
        else:
            blocked(
                "required_inputs",
                (
                    "tick-only quote-arrival/update-count semantics are unavailable "
                    "in frozen M1 PASS strata"
                ),
                "configs/research/fx_intraday_alpha_search_v1.yaml",
            )
        if cfg.get("stop_rule") == "none":
            used(
                "stop_rule",
                "no stop path active",
                "results/gate_a0r2/trial_materialization_v2.jsonl",
            )
        else:
            blocked(
                "stop_rule",
                "ATR stop construction lacks exact pre-outcome ATR definition for this factory",
                "results/gate_a0r2/trial_materialization_v2.jsonl",
            )
        if cfg.get("exit_rule") == "time_exit":
            used(
                "exit_rule",
                "time_exit closes at first valid bar after holding_horizon",
                "results/gate_a0/search_space_freeze.json",
            )
        else:
            blocked(
                "exit_rule",
                "only time_exit exact semantics certified",
                "A0 execution contract",
            )
        for field in ("lookback", "entry_threshold", "variant", "holding_horizon"):
            used(field, f"consumed by F02 direction-run signal: {cfg.get(field)!r}", "A0R2 V2")
        inert(
            "session_anchor",
            "F02 frozen family has no session-anchor axis; materialized generic field is inert",
            "configs/research/fx_intraday_alpha_search_v1.yaml",
        )
        inert(
            "target_horizon",
            "not behaviorally active for deterministic time_exit F02 without target/stop",
            "results/gate_a0/target_registry.json",
        )
        if cfg.get("model_class") in (None, "none"):
            inert("model_class", "deterministic non-ML F02", "A0 hypothesis/search-space freeze")
        else:
            blocked(
                "model_class",
                "trainable model semantics not certified",
                "A0 search-space freeze",
            )
    else:
        blocked(
            "family",
            "no exact executable pre-outcome signal formula recovered for A0R3E",
            (
                "results/gate_a0/hypothesis_registry.json and "
                "configs/research/fx_intraday_alpha_search_v1.yaml"
            ),
        )
        if cfg.get("stop_rule") != "none":
            blocked(
                "stop_rule",
                "ATR stop construction lacks exact pre-outcome ATR definition for this factory",
                "A0/A0R2 artifacts",
            )
        if cfg.get("spread_forecaster"):
            blocked(
                "spread_forecaster",
                (
                    "forecaster class is named but fit/threshold/execution-gate "
                    "semantics are not fully executable"
                ),
                "configs/research/fx_intraday_alpha_search_v1.yaml",
            )
        if cfg.get("regime_model"):
            blocked(
                "regime_model",
                (
                    "regime model class/state-count is named but no deterministic "
                    "fit/filter specification is complete"
                ),
                "configs/research/fx_intraday_alpha_search_v1.yaml",
            )
        if cfg.get("model_class") not in (None, "none"):
            blocked(
                "model_class",
                "ML target/features/normalization/walk-forward/abstention path not fully certified",
                "configs/research/fx_intraday_alpha_search_v1.yaml",
            )
        if cfg.get("abstention_threshold") is not None:
            blocked(
                "abstention_threshold",
                (
                    "threshold is materialized but no certified model probability/score "
                    "mapping is available"
                ),
                "results/gate_a0r2/trial_materialization_v2.jsonl",
            )
        if family == "F10_INTRADAY_SEASONALITY":
            blocked(
                "training_window",
                (
                    "prior-year-only cell estimates require eligible prior PASS strata "
                    "absent for GBPUSD 2017"
                ),
                "configs/research/fx_intraday_alpha_search_v1.yaml",
            )

    status = "CERTIFIED_EXECUTABLE" if not blockers else "IMPLEMENTATION_BLOCKED"
    return status, blockers, rows


def signal_f02(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    lookback = max(int(config["lookback"]), 1)
    threshold = float(config["entry_threshold"])
    run = np.sign(frame["mid_return"]).rolling(lookback, min_periods=3).sum().fillna(0.0)
    raw = run / math.sqrt(max(lookback, 1))
    if "exhaust" in str(config["variant"]).lower():
        raw = -raw
    return pd.Series(
        np.where(raw >= threshold, 1, np.where(raw <= -threshold, -1, 0)),
        index=frame.index,
    )


def trial_signal(frame: pd.DataFrame, trial: dict[str, Any]) -> pd.Series:
    family = trial["family_id"]
    if family == "F01_SESSION_OPENING_MOMENTUM_REVERSAL":
        return signal_f01(frame, trial["full_configuration"])
    if family == "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION":
        return signal_f02(frame, trial["full_configuration"])
    raise ValueError(f"uncertified family {family}")


def certify_universe(
    trials: list[dict[str, Any]], eligibility_rows: dict[str, dict[str, Any]], paths: Paths
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    matrix: list[dict[str, Any]] = []
    certified: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    newly_certified: list[str] = []

    for trial in trials:
        status, blockers, rows = certify_trial_a0r3e(trial)
        matrix.extend(rows)
        family = trial["family_id"]
        by_family[family][status] += 1
        if status == "CERTIFIED_EXECUTABLE":
            certified.append(trial)
            if trial["trial_id"] not in A0R3D_F01_IDS:
                newly_certified.append(trial["trial_id"])
        else:
            blocked_rows.append(
                {
                    "trial_id": trial["trial_id"],
                    "family_id": family,
                    "configuration_sha256": trial["configuration_sha256"],
                    "eligible_topology_units": eligibility_rows[trial["trial_id"]][
                        "eligible_topology_units"
                    ],
                    "blockers": blockers,
                }
            )

    payload = {
        "artifact_id": "A0R3E_CERTIFICATION_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if certified else "BLOCKED",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "supersedes": "A0R3D_EVALUATOR_CERTIFICATION_V1",
        "a0r3b_eligible_trials": len(trials),
        "certified_executable_trials": len(certified),
        "blocked_trials": len(blocked_rows),
        "certified_before_a0r3d": 6,
        "certified_after_a0r3e": len(certified),
        "newly_certified_trials": newly_certified,
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "semantic_closure_matrix": matrix,
        "blocked_trials_detail": blocked_rows,
        "source_catalog_hash": json_hash(source_catalog(paths)),
        "no_2018_plus_market_or_outcome_files_opened": True,
    }
    payload["certification_hash"] = json_hash(payload)
    return payload, certified, blocked_rows


def evaluate_trials(
    frames: dict[tuple[str, int], pd.DataFrame],
    trials: list[dict[str, Any]],
    eligibility_rows: dict[str, dict[str, Any]],
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    matrix_parts: list[pd.Series] = []
    p_values: list[float] = []

    for trial in trials:
        cfg = trial["full_configuration"]
        unit_rows: list[dict[str, Any]] = []
        daily_parts: list[pd.DataFrame] = []
        for unit in eligibility_rows[trial["trial_id"]]["eligible_topology_units"]:
            pair = str(unit["evaluation_pair"])
            year = int(unit["year"])
            frame = frames[(pair, year)]
            signal = trial_signal(frame, trial)
            exec_frame, exec_signal = compact_execution_window(
                frame, signal, horizon=int(cfg.get("holding_horizon") or 1)
            )
            base_daily, trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=1.0
            )
            stress15, stress15_trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=1.5
            )
            stress20, stress20_trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=2.0
            )
            unit_rows.append(
                {
                    "topology_id": unit["topology_id"],
                    "pair": pair,
                    "year": year,
                    "legs": unit["legs"],
                    "metrics": daily_metrics(base_daily, trades),
                    "stress_1_5x": daily_metrics(stress15, stress15_trades),
                    "stress_2_0x": daily_metrics(stress20, stress20_trades),
                }
            )
            daily_parts.append(base_daily[["date", "net_bps"]])
        pooled = pd.concat(daily_parts, ignore_index=True)
        daily = pooled.groupby("date", as_index=False)["net_bps"].mean()
        values = daily["net_bps"].to_numpy(dtype=float)
        primary_trades = sum(int(unit["metrics"]["trade_count"]) for unit in unit_rows)
        primary = {
            "days": int(len(daily)),
            "trade_count": primary_trades,
            "gross_bps": round(
                float(np.mean([unit["metrics"]["gross_bps"] for unit in unit_rows])), 6
            ),
            "cost_bps": round(
                float(np.mean([unit["metrics"]["cost_bps"] for unit in unit_rows])), 6
            ),
            "net_bps": round(float(np.mean([unit["metrics"]["net_bps"] for unit in unit_rows])), 6),
            "net_bps_per_trade": round(
                float(np.mean([unit["metrics"]["net_bps_per_trade"] for unit in unit_rows])), 9
            ),
            "daily_sharpe": round(
                float(np.mean([unit["metrics"]["daily_sharpe"] for unit in unit_rows])), 6
            ),
            "max_drawdown_bps": round(
                float(np.mean([unit["metrics"]["max_drawdown_bps"] for unit in unit_rows])), 6
            ),
            "hit_rate": round(
                float(np.mean([unit["metrics"]["hit_rate"] for unit in unit_rows])), 6
            ),
            "turnover": round(
                float(np.mean([unit["metrics"]["turnover"] for unit in unit_rows])), 6
            ),
        }
        p_values.append(normal_p_value_from_mean(values))
        matrix_parts.append(daily.set_index("date")["net_bps"].rename(trial["trial_id"]))
        stress15_positive = [float(unit["stress_1_5x"]["net_bps"]) > 0 for unit in unit_rows]
        stress20_positive = [float(unit["stress_2_0x"]["net_bps"]) > 0 for unit in unit_rows]
        positive_units = [float(unit["metrics"]["net_bps"]) > 0 for unit in unit_rows]
        rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": trial["family_id"],
                "status": "CORRECTED_EXPLORATORY_COMPLETED",
                "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
                "configuration_sha256": trial["configuration_sha256"],
                "eligible_topology_units": eligibility_rows[trial["trial_id"]][
                    "eligible_topology_units"
                ],
                "topology_unit_count": eligibility_rows[trial["trial_id"]]["topology_unit_count"],
                "unit_results": unit_rows,
                "primary_equal_weight": primary,
                "trade_count": primary_trades,
                "cross_stratum_stability": round(float(np.mean(positive_units)), 6),
                "cost_stress": {
                    "survives_1_5x": bool(all(stress15_positive)),
                    "survives_2_0x": bool(all(stress20_positive)),
                    "survival_rate_1_5x": round(float(np.mean(stress15_positive)), 6),
                    "survival_rate_2_0x": round(float(np.mean(stress20_positive)), 6),
                },
                "evidence_tier": "SINGLE_STRATUM_EXPLORATORY_LEAD",
                "execution_engine": "A0R3D_SIDE_CORRECT_EVENT_STATE_MACHINE",
                "synthetic_fills_used": 0,
            }
        )

    return_matrix = pd.concat(matrix_parts, axis=1).fillna(0.0) if matrix_parts else pd.DataFrame()
    bootstrap = bootstrap_family_stats(return_matrix, seed=seed)
    holm = holm_adjust(p_values)
    bh = bh_fdr(p_values)
    rw = bootstrap.get("romano_wolf_stepdown_p", [])
    for index, row in enumerate(rows):
        values = return_matrix[row["trial_id"]].to_numpy(dtype=float)
        skew, kurt = _sample_moments(values)
        row["corrected_significance"] = {
            "raw_daily_mean_p": round(p_values[index], 9),
            "holm_p": round(holm[index], 9),
            "bh_fdr_p": round(bh[index], 9),
            "romano_wolf_p": rw[index] if index < len(rw) else "NOT_APPLICABLE",
            "psr": round(
                psr(float(row["primary_equal_weight"]["daily_sharpe"]), len(values), skew, kurt),
                9,
            ),
            "dsr": round(
                dsr(
                    float(row["primary_equal_weight"]["daily_sharpe"]),
                    len(values),
                    skew,
                    kurt,
                    REGISTERED_TRIAL_DENOMINATOR,
                ),
                9,
            ),
            "skew": round(skew, 9),
            "kurtosis": round(kurt, 9),
        }

    review_rows = rank_review(rows)
    survivors_rows = rank_survivors(rows)
    multiple = {
        "artifact_id": "A0R3E_MULTIPLE_TESTING_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "evaluated_trials": len(rows),
        "registered_candidate_equivalent_denominator": REGISTERED_TRIAL_DENOMINATOR,
        **bootstrap,
        "pbo": "NOT_APPLICABLE",
        "pbo_not_applicable_reason": (
            "fewer_than_four_independent_strata_or_folds_in_certified_subset"
        ),
    }
    results = {
        "artifact_id": "A0R3E_CORRECTED_EXPLORATORY_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "result_rows": rows,
        "evaluated_trials": len(rows),
        "daily_return_matrix_sha256": (
            json_hash(return_matrix.to_dict()) if not return_matrix.empty else ""
        ),
        "no_2018_plus_market_or_outcome_files_opened": True,
    }
    review = {
        "artifact_id": "A0R3E_REVIEW_RANKING_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "supersedes": "A0R3D_SHORTLIST_V1",
        "review_ranking_size": len(review_rows),
        "negative_net_candidates_are_not_scientific_survivors": True,
        "rows": review_rows,
    }
    survivors = {
        "artifact_id": "A0R3E_SCIENTIFIC_EXPLORATORY_SURVIVORS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "survivor_criteria": [
            "executable net_bps > 0",
            "1.5x cost-stress net_bps > 0",
            "2.0x cost-stress net_bps > 0",
            "candidate remains exploratory, not validated",
        ],
        "survivor_count": len(survivors_rows),
        "rows": survivors_rows,
    }
    return results, multiple, review, survivors, return_matrix.to_dict()


def rank_review(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row["corrected_significance"]["bh_fdr_p"]),
            float(row["primary_equal_weight"]["net_bps"]) <= 0.0,
            not bool(row["cost_stress"]["survives_2_0x"]),
            -float(row["primary_equal_weight"]["net_bps"]),
            -float(row["primary_equal_weight"]["daily_sharpe"]),
            row["trial_id"],
        ),
    )


def rank_survivors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    survivors = [
        row
        for row in rows
        if float(row["primary_equal_weight"]["net_bps"]) > 0
        and row["cost_stress"]["survives_1_5x"]
        and row["cost_stress"]["survives_2_0x"]
    ]
    return rank_review(survivors)[:24]


def regression_against_a0r3d(paths: Paths, rows: list[dict[str, Any]]) -> dict[str, Any]:
    prior_path = paths.repo / "results" / "gate_a0r3d" / "corrected_results.json"
    prior = {
        row["trial_id"]: row
        for row in read_json(prior_path)["result_rows"]
        if row["trial_id"] in A0R3D_F01_IDS
    }
    current = {row["trial_id"]: row for row in rows if row["trial_id"] in A0R3D_F01_IDS}
    checks: list[dict[str, Any]] = []
    max_abs_delta = 0.0
    for trial_id in sorted(A0R3D_F01_IDS):
        deltas: dict[str, float] = {}
        for key in ("gross_bps", "cost_bps", "net_bps", "daily_sharpe", "trade_count"):
            lhs = float(current[trial_id]["primary_equal_weight"][key])
            rhs = float(prior[trial_id]["primary_equal_weight"][key])
            delta = abs(lhs - rhs)
            max_abs_delta = max(max_abs_delta, delta)
            deltas[key] = round(delta, 12)
        checks.append({"trial_id": trial_id, "deltas": deltas})
    return {
        "artifact_id": "A0R3E_A0R3D_REGRESSION_CHECK_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if max_abs_delta <= 1e-9 else "FAIL",
        "tolerance": 1e-9,
        "max_abs_delta": round(max_abs_delta, 12),
        "checks": checks,
    }


def write_report(
    paths: Paths,
    certification: dict[str, Any],
    results: dict[str, Any],
    multiple: dict[str, Any],
    review: dict[str, Any],
    survivors: dict[str, Any],
    regression: dict[str, Any],
) -> None:
    lines = [
        "# A0R3E Semantic Closure",
        "",
        "Status: EXPLORATORY_NOT_VALIDATED_ALPHA",
        "",
        "A0R3E supersedes A0R3D reporting taxonomy without rewriting A0R3D artifacts.",
        "Negative-net candidates are retained in REVIEW_RANKING only.",
        "",
        "## Certification",
        "",
        f"- A0R3B eligible trials: {certification['a0r3b_eligible_trials']}",
        f"- Certified executable before: {certification['certified_before_a0r3d']}",
        f"- Certified executable after: {certification['certified_after_a0r3e']}",
        f"- Newly certified: {', '.join(certification['newly_certified_trials'])}",
        f"- Blocked: {certification['blocked_trials']}",
        f"- A0R3D regression: {regression['status']} max_delta={regression['max_abs_delta']}",
        "",
        "## Corrected Discovery",
        "",
        f"- Evaluated trials: {results['evaluated_trials']}",
        f"- WRC p: {multiple.get('white_reality_check_p')}",
        f"- SPA p: {multiple.get('hansen_spa_p')}",
        f"- Review ranking size: {review['review_ranking_size']}",
        f"- Scientific survivor count: {survivors['survivor_count']}",
        "- 2018+ market/outcome files opened: 0",
        "",
        "## Top Review Ranking",
        "",
    ]
    for row in review["rows"][:10]:
        primary = row["primary_equal_weight"]
        sig = row["corrected_significance"]
        lines.append(
            "- "
            f"{row['trial_id']} {row['family_id']} "
            f"net={primary['net_bps']} gross={primary['gross_bps']} "
            f"sharpe={primary['daily_sharpe']} trades={primary['trade_count']} "
            f"bh={sig['bh_fdr_p']} dsr={sig['dsr']} "
            f"stress2={row['cost_stress']['survives_2_0x']}"
        )
    lines.extend(["", "## Scientific Exploratory Survivors", ""])
    if survivors["rows"]:
        for row in survivors["rows"]:
            lines.append(f"- {row['trial_id']} {row['family_id']}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            (
                "Next gate: close remaining pre-outcome semantics for "
                "F03/F04/F05/F10/F11/F12 or stop before 2018 confirmation unless "
                "a corrected survivor exists."
            ),
            "",
        ]
    )
    (paths.docs / "A0R3E_SEMANTIC_CLOSURE.md").write_text("\n".join(lines), encoding="utf-8")


def run(paths: Paths) -> dict[str, Any]:
    catalog = source_catalog(paths)
    write_json(paths.results / "source_catalog.json", catalog)
    trials, eligibility_rows = load_eligible_universe(paths)
    certification, certified, blocked = certify_universe(trials, eligibility_rows, paths)
    write_json(paths.results / "certification.json", certification)
    write_json(
        paths.results / "semantic_closure_matrix.json",
        certification["semantic_closure_matrix"],
    )
    write_json(paths.results / "blocked_trials.json", blocked)

    units = [
        unit
        for trial in certified
        for unit in eligibility_rows[trial["trial_id"]]["eligible_topology_units"]
    ]
    guard = HoldoutReadGuard()
    frames = load_required_frames(paths, units, guard)
    results, multiple, review, survivors, matrix = evaluate_trials(
        frames, certified, eligibility_rows, seed=frozen_seed(paths)
    )
    regression = regression_against_a0r3d(paths, results["result_rows"])
    if regression["status"] != "PASS":
        raise AssertionError("A0R3E_A0R3D_REGRESSION_FAILED")
    read_audit = {
        "artifact_id": "A0R3E_HOLDOUT_READ_AUDIT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "opened_files": [asdict(read) for read in guard.reads],
        "opened_file_count": len(guard.reads),
        "opened_bytes": sum(read.bytes for read in guard.reads),
        "opened_2018_plus_market_or_outcome_files": [],
        "2018_plus_market_or_outcome_files_opened": 0,
    }
    write_json(paths.results / "holdout_read_audit.json", read_audit)
    write_json(paths.results / "corrected_results.json", results)
    write_json(paths.results / "multiple_testing.json", multiple)
    write_json(paths.results / "review_ranking.json", review)
    write_json(paths.results / "scientific_survivors.json", survivors)
    write_json(paths.results / "a0r3d_regression_check.json", regression)
    write_json(paths.results / "daily_return_matrix.json", matrix)

    cost_rows = [
        {
            "trial_id": row["trial_id"],
            "survives_1_5x": row["cost_stress"]["survives_1_5x"],
            "survives_2_0x": row["cost_stress"]["survives_2_0x"],
        }
        for row in results["result_rows"]
    ]
    cost = {
        "artifact_id": "A0R3E_COST_STRESS_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "rows": cost_rows,
    }
    write_json(paths.results / "cost_stress.json", cost)
    summary = {
        "artifact_id": "A0R3E_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "starting_a0r3d_certified_trials": 6,
        "certified_executable_trials": len(certified),
        "blocked_trials": len(blocked),
        "newly_certified_trials": certification["newly_certified_trials"],
        "corrected_trials_run": int(results["evaluated_trials"]),
        "review_ranking_size": int(review["review_ranking_size"]),
        "scientific_survivor_count": int(survivors["survivor_count"]),
        "cost_stress_1_5x_survivors": sum(1 for row in cost_rows if row["survives_1_5x"]),
        "cost_stress_2_0x_survivors": sum(1 for row in cost_rows if row["survives_2_0x"]),
        "white_reality_check_p": multiple.get("white_reality_check_p"),
        "hansen_spa_p": multiple.get("hansen_spa_p"),
        "pbo": multiple.get("pbo"),
        "a0r3d_regression_status": regression["status"],
        "2018_plus_market_or_outcome_files_opened": 0,
        "next_gate": "A0R3F_REMAINING_SEMANTICS_OR_NO_2018_CONFIRMATION_WITHOUT_SURVIVOR",
    }
    summary["summary_hash"] = json_hash(summary)
    write_json(paths.results / "summary.json", summary)
    write_report(paths, certification, results, multiple, review, survivors, regression)
    return summary
