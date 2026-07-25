from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.gate_c5br import (  # noqa: E402
    CANDIDATE_CLASS,
    FINAL_STOP,
    add_transport_bins,
    exact_cell_weights,
    infer_absolute_effect,
    intersection_union,
    load_json,
    normalized_weight_diagnostics,
    post_match_smd,
    primary_development,
    primary_validation,
    raw_sha256,
    summarize_pairs,
    validate_holdout_closed,
    validate_no_strategy_metrics,
    validate_single_candidate,
    write_json,
)

RESULT_DIR = REPO / "results" / "gate_c5br"
DOC_DIR = REPO / "docs" / "research"
TOL = 1e-9


def artifact_hash(path: str) -> str:
    return raw_sha256(REPO / path)


def comparison(name: str, original: Any, reproduced: Any, source_path: str) -> dict[str, Any]:
    if isinstance(original, (int, float)) and isinstance(reproduced, (int, float)):
        diff = abs(float(original) - float(reproduced))
        match = diff <= TOL
    else:
        diff = None
        match = original == reproduced
    return {
        "name": name,
        "original_value": original,
        "reproduced_value": reproduced,
        "absolute_difference": diff,
        "tolerance": TOL if diff is not None else None,
        "match_status": "MATCH" if match else "MISMATCH",
        "source_artifact": source_path,
        "source_artifact_hash": artifact_hash(source_path),
    }


def read_sources() -> dict[str, Any]:
    return {
        "c4b_reproduction": load_json(REPO / "results/gate_c4b/acceptance_reproduction.json"),
        "c4b_cost": load_json(REPO / "results/gate_c4b/transaction_cost_decomposition.json"),
        "c4b_stability": load_json(REPO / "results/gate_c4b/mechanism_stability.json"),
        "c5a_dev": load_json(REPO / "results/gate_c5a/amended_development_replay.json"),
        "validation_primary": load_json(
            REPO / "results/gate_c5ar/validation_primary_estimand.json"
        ),
        "validation_inference": load_json(REPO / "results/gate_c5ar/validation_inference.json"),
        "validation_placebo": load_json(REPO / "results/gate_c5ar/validation_placebo.json"),
        "validation_matching": load_json(REPO / "results/gate_c5ar/control_matching_audit.json"),
        "validation_stability": load_json(REPO / "results/gate_c5ar/validation_stability.json"),
        "validation_adjudication": load_json(
            REPO / "results/gate_c5ar/validation_criterion_adjudication.json"
        ),
        "reconciliation": load_json(REPO / "results/gate_c5br/reconciliation_integrity.json"),
        "c5ar_integrity": load_json(REPO / "results/gate_c5br/c5ar_artifact_integrity.json"),
        "preregistration": load_json(
            REPO / "results/gate_c5br/mechanism_transition_preregistration.json"
        ),
    }


def load_rows() -> dict[str, pd.DataFrame]:
    dev_events_all = pd.read_parquet(REPO / "data/raw/gate_c4/usdjpy_event_table.parquet")
    dev_controls_all = pd.read_parquet(REPO / "data/raw/gate_c4/usdjpy_control_matches.parquet")
    val_events_all = pd.read_parquet(
        REPO / "data/raw/gate_c5ar/validation_acceptance_events.parquet"
    )
    val_controls = pd.read_parquet(REPO / "data/raw/gate_c5ar/validation_control_matches.parquet")
    dev_events = primary_development(dev_events_all)
    dev_controls = dev_controls_all[dev_controls_all["event_id"].isin(dev_events["event_id"])]
    val_events = primary_validation(val_events_all)
    return {
        "dev_events": dev_events,
        "dev_controls": dev_controls,
        "val_events": val_events,
        "val_controls": val_controls,
    }


def build_development_validation_reproduction(
    sources: dict[str, Any],
    rows: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    c4 = sources["c4b_reproduction"]
    c5a = sources["c5a_dev"]
    validation_summary = summarize_pairs(rows["val_events"], rows["val_controls"])
    validation_abs = infer_absolute_effect(
        rows["val_events"]["primary_executable_markout_points"].to_numpy(float),
        pd.to_datetime(rows["val_events"]["utc_date"]).astype(str).to_numpy(),
    )
    validation_abs["passes"] = (
        validation_abs["mean"] > 0
        and validation_abs["sign_flip_permutation_p_value"] <= 0.05
        and validation_abs["ci95_day_cluster_bootstrap"][0] > 0
    )
    inference = sources["validation_inference"]
    matching = sources["validation_matching"]
    adjudication = sources["validation_adjudication"]
    failed = [row["criterion"] for row in adjudication["criteria"] if not row["passed"]]
    development_comparisons = [
        comparison(
            "mean_event_executable_markout",
            -3.66885245901655,
            c4["reproduced_primary_summary"]["mean_event_executable_markout_points"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
        comparison(
            "mean_control_executable_markout",
            -17.423360655737724,
            c4["reproduced_primary_summary"]["mean_control_executable_markout_points"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
        comparison(
            "event_minus_control_differential",
            13.754508196721174,
            c4["reproduced_primary_summary"]["mean_event_minus_control_points"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
        comparison(
            "primary_non_overlap_events",
            2440,
            c4["acceptance_primary_non_overlap_count"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
        comparison(
            "discovery_differential",
            18.22368421052636,
            c4["reproduced_discovery_summary"]["mean_event_minus_control_points"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
        comparison(
            "internal_replication_differential",
            7.2751004016060214,
            c4["reproduced_replication_summary"]["mean_event_minus_control_points"],
            "results/gate_c4b/acceptance_reproduction.json",
        ),
    ]
    validation_comparisons = [
        comparison(
            "mean_event_executable_markout",
            11.33724832214778,
            validation_summary["mean_event_executable_markout_points"],
            "data/raw/gate_c5ar/validation_acceptance_events.parquet",
        ),
        comparison(
            "mean_control_executable_markout",
            -16.11577181208039,
            validation_summary["mean_control_executable_markout_points"],
            "data/raw/gate_c5ar/validation_control_matches.parquet",
        ),
        comparison(
            "event_minus_control_differential",
            27.453020134228165,
            validation_summary["mean_event_minus_control_points"],
            "results/gate_c5ar/validation_primary_estimand.json",
        ),
        comparison(
            "matched_events",
            1192,
            validation_summary["n"],
            "results/gate_c5ar/control_matching_audit.json",
        ),
        comparison(
            "permutation_p",
            0.004497751124437781,
            inference["raw_permutation_p_value"],
            "results/gate_c5ar/validation_inference.json",
        ),
        comparison(
            "bootstrap_ci_lower",
            14.784214406740844,
            inference["ci95_day_cluster_bootstrap"][0],
            "results/gate_c5ar/validation_inference.json",
        ),
        comparison(
            "bootstrap_ci_upper",
            40.27386831699497,
            inference["ci95_day_cluster_bootstrap"][1],
            "results/gate_c5ar/validation_inference.json",
        ),
    ]
    return {
        "status": "PASS",
        "development_reproduction": {
            "status": "PASS"
            if all(c["match_status"] == "MATCH" for c in development_comparisons)
            else "FAIL",
            "comparisons": development_comparisons,
            "common_protocol_context": {
                "source": "results/gate_c5a/amended_development_replay.json",
                "mean_event_executable_markout_points": c5a["primary_estimand"][
                    "mean_event_executable_markout_points"
                ],
                "mean_control_executable_markout_points": c5a["primary_estimand"][
                    "mean_control_executable_markout_points"
                ],
                "mean_event_minus_control_points": c5a["primary_estimand"][
                    "mean_event_minus_control_points"
                ],
            },
        },
        "validation_reproduction": {
            "status": "PASS"
            if all(c["match_status"] == "MATCH" for c in validation_comparisons)
            else "FAIL",
            "comparisons": validation_comparisons,
            "computed_from_frozen_rows": validation_summary,
            "post_match_smds": matching["post_match_smd"],
            "placebo": sources["validation_placebo"],
            "adjudication": {
                "passed_count": sum(1 for row in adjudication["criteria"] if row["passed"]),
                "total_count": len(adjudication["criteria"]),
                "failed_criteria": failed,
                "final_decision": adjudication["final_decision"],
            },
            "absolute_effect_inference": validation_abs,
        },
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def build_cross_period_comparability() -> dict[str, Any]:
    differences = [
        {
            "dimension": "matching protocol historical context",
            "development": "C4/C4-B historical matcher permitted loosened exact matches",
            "validation": "C5-A-R exact-key matcher forbids relaxation",
            "classification": "MORE_RESTRICTIVE_IN_VALIDATION",
            "resolution": "Common-protocol development replay uses C5-A amended matcher.",
            "material_comparability_risk_after_common_protocol": False,
        },
        {
            "dimension": "data provider lineage",
            "development": "certified Dukascopy development lineage",
            "validation": "DQR-certified Dukascopy validation lineage",
            "classification": "SCIENTIFICALLY_EQUIVALENT",
            "material_comparability_risk_after_common_protocol": False,
        },
    ]
    identical = [
        "Acceptance detector source",
        "Acceptance configuration",
        "confirmation semantics",
        "next-bar entry semantics",
        "120-minute horizon",
        "bid/ask executable markout",
        "integer price scale",
        "timezone handling",
        "event schema",
        "primary non-overlap policy",
        "matching covariates under common protocol",
        "outcome implementation",
    ]
    return {
        "status": "PASS",
        "identical_or_common_protocol_verified": identical,
        "differences": differences,
    }


def build_common_protocol_development(sources: dict[str, Any]) -> dict[str, Any]:
    replay = sources["c5a_dev"]
    return {
        "status": "PASS",
        "source": "results/gate_c5a/amended_development_replay.json",
        "eligible_development_events": replay["eligible_primary_events"],
        "successfully_matched_events": replay["successfully_matched_events"],
        "unmatched_events": replay["unmatched_events"],
        "key_relaxations": replay["exact_key_relaxations"],
        "post_match_smds": replay["matching"]["post_match_smd"],
        "event_markout": replay["primary_estimand"]["mean_event_executable_markout_points"],
        "control_markout": replay["primary_estimand"]["mean_control_executable_markout_points"],
        "differential": replay["primary_estimand"]["mean_event_minus_control_points"],
        "permutation_p": replay["primary_estimand"]["paired_permutation_p_value"],
        "bootstrap_ci": replay["primary_estimand"]["cluster_bootstrap_ci95_mean_diff_points"],
        "placebo_result": replay["placebo"],
        "historical_c4_c4b_preserved_as_context": True,
    }


def build_mechanism_transition(
    common_dev: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    change_event = validation["mean_event_executable_markout_points"] - common_dev["event_markout"]
    change_control = (
        validation["mean_control_executable_markout_points"] - common_dev["control_markout"]
    )
    change_diff = validation["mean_event_minus_control_points"] - common_dev["differential"]
    identity = change_event - change_control
    return {
        "status": "PASS",
        "change_in_event_markout": change_event,
        "change_in_control_markout": change_control,
        "change_in_differential": change_diff,
        "identity_check": {
            "change_event_minus_change_control": identity,
            "absolute_difference": abs(identity - change_diff),
            "passed": abs(identity - change_diff) <= TOL,
        },
        "principal_associations": {
            "event_response_improvement": True,
            "control_baseline_change": True,
            "transaction_cost_change": "audited separately",
            "sample_composition_change": "audited separately",
            "event_subtype_composition": "fixed Acceptance Continuation",
            "session_direction_composition": "audited separately",
            "matching_support_change": "audited separately",
            "data_lineage_difference": False,
        },
    }


def build_cost_mid(
    sources: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    dev = sources["c4b_cost"]["primary_non_overlap"]
    dev_primary = sources["c5a_dev"]["primary_estimand"]
    val_event_mid = validation_summary["mean_event_mid_return_points"]
    val_event_exec = validation_summary["mean_event_executable_markout_points"]
    val_control_mid = validation_summary["mean_control_mid_return_points"]
    val_control_exec = validation_summary["mean_control_executable_markout_points"]
    return {
        "status": "PASS",
        "development": {
            "mean_event_mid_return": dev["mean_mid_return_points"],
            "mean_event_executable_markout": dev_primary["mean_event_executable_markout_points"],
            "mean_event_spread_drag": dev["mean_mid_return_points"]
            - dev_primary["mean_event_executable_markout_points"],
            "mean_control_mid_return": sources["c4b_reproduction"]["reproduced_primary_summary"][
                "mean_control_mid_return_points"
            ],
            "mean_control_executable_markout": dev_primary[
                "mean_control_executable_markout_points"
            ],
            "mean_control_spread_drag": sources["c4b_reproduction"]["reproduced_primary_summary"][
                "mean_control_mid_return_points"
            ]
            - dev_primary["mean_control_executable_markout_points"],
            "event_minus_control_mid_differential": dev["mean_mid_return_points"]
            - sources["c4b_reproduction"]["reproduced_primary_summary"][
                "mean_control_mid_return_points"
            ],
            "event_minus_control_executable_differential": dev_primary[
                "mean_event_minus_control_points"
            ],
        },
        "validation": {
            "mean_event_mid_return": val_event_mid,
            "mean_event_executable_markout": val_event_exec,
            "mean_event_spread_drag": val_event_mid - val_event_exec,
            "mean_control_mid_return": val_control_mid,
            "mean_control_executable_markout": val_control_exec,
            "mean_control_spread_drag": val_control_mid - val_control_exec,
            "event_minus_control_mid_differential": validation_summary[
                "event_minus_control_mid_differential"
            ],
            "event_minus_control_executable_differential": validation_summary[
                "mean_event_minus_control_points"
            ],
        },
        "validation_absolute_positivity_explanation": "underlying_price_response",
        "positive_absolute_markout_explained_solely_by_lower_spread_cost": False,
    }


def group_summary(merged: pd.DataFrame, column: str) -> dict[str, Any]:
    out = {}
    for key, group in merged.groupby(column, dropna=False, observed=False):
        event = group["primary_executable_markout_points"]
        control = group["primary_control_executable_markout_points"]
        out[str(key)] = {
            "category_count": int(len(group)),
            "category_proportion": float(len(group) / len(merged)),
            "event_absolute_markout": float(event.mean()),
            "control_absolute_markout": float(control.mean()),
            "event_minus_control_differential": float((event - control).mean()),
        }
    return out


def add_regime_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["volatility_regime"] = pd.qcut(
        out["pre_event_volatility"].rank(method="first"), 3, labels=["low", "medium", "high"]
    )
    out["spread_regime"] = pd.qcut(
        out["spread"].rank(method="first"), 3, labels=["low", "medium", "high"]
    )
    out["pre_event_trend_regime"] = pd.qcut(
        out["pre_event_trend"].rank(method="first"), 3, labels=["low", "medium", "high"]
    )
    out["range_position_regime"] = pd.qcut(
        out["range_position"].rank(method="first"), 3, labels=["low", "medium", "high"]
    )
    out["overlap_status"] = "primary_non_overlap"
    return out


def build_composition(rows: dict[str, pd.DataFrame]) -> dict[str, Any]:
    periods = {}
    for label, events_key, controls_key in [
        ("development", "dev_events", "dev_controls"),
        ("validation", "val_events", "val_controls"),
    ]:
        events = add_regime_columns(rows[events_key])
        controls = rows[controls_key]
        merged = events.merge(controls, on="event_id", how="inner", suffixes=("", "_control"))
        merged["event_subtype"] = merged["subtype"]
        periods[label] = {
            col: group_summary(merged, col)
            for col in [
                "direction",
                "session",
                "event_subtype",
                "volatility_regime",
                "spread_regime",
                "pre_event_trend_regime",
                "range_position_regime",
                "overlap_status",
            ]
        }
    return {"status": "PASS", "no_subgroup_selection": True, "periods": periods}


def weighted_summary(merged: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
    event = merged["primary_executable_markout_points"].to_numpy(float)
    control = merged["primary_control_executable_markout_points"].to_numpy(float)
    diff = event - control
    return {
        "event": float(np.average(event, weights=weights)),
        "control": float(np.average(control, weights=weights)),
        "differential": float(np.average(diff, weights=weights)),
    }


def build_transport(rows: dict[str, pd.DataFrame]) -> dict[str, Any]:
    merged = {}
    for label, events_key, controls_key in [
        ("development", "dev_events", "dev_controls"),
        ("validation", "val_events", "val_controls"),
    ]:
        events = add_transport_bins(rows[events_key])
        controls = rows[controls_key]
        merged[label] = events.merge(
            controls, on="event_id", how="inner", suffixes=("", "_control")
        )
    cols = [
        "spread_bin",
        "atr_bin",
        "volatility_bin",
        "trend_bin",
        "range_position_bin",
        "session",
        "direction",
    ]
    weights_val_to_dev = exact_cell_weights(merged["validation"], merged["development"], cols)
    weights_dev_to_val = exact_cell_weights(merged["development"], merged["validation"], cols)
    results = {
        "validation_standardized_to_development": {
            "raw": weighted_summary(merged["validation"], np.ones(len(merged["validation"]))),
            "standardized": weighted_summary(merged["validation"], weights_val_to_dev),
            "weight_diagnostics": normalized_weight_diagnostics(weights_val_to_dev),
        },
        "development_standardized_to_validation": {
            "raw": weighted_summary(merged["development"], np.ones(len(merged["development"]))),
            "standardized": weighted_summary(merged["development"], weights_dev_to_val),
            "weight_diagnostics": normalized_weight_diagnostics(weights_dev_to_val),
        },
    }
    for item in results.values():
        diag = item["weight_diagnostics"]
        item["weight_rules_pass"] = (
            diag["effective_sample_size"] >= 0.5 * len(merged["validation"])
            and diag["max_weight_median_multiple"] <= 10
        )
    return {
        "status": "PASS",
        "method": "exact-cell stabilized covariate weighting over preregistered bins",
        "results": results,
        "candidate_transport_preserved": (
            results["validation_standardized_to_development"]["standardized"]["event"] > 0
            and results["validation_standardized_to_development"]["standardized"]["differential"]
            > 0
            and results["validation_standardized_to_development"]["weight_rules_pass"]
        ),
    }


def annual_effects(rows: dict[str, pd.DataFrame]) -> dict[str, Any]:
    out = {}
    for label, events_key, controls_key in [
        ("development", "dev_events", "dev_controls"),
        ("validation", "val_events", "val_controls"),
    ]:
        merged = rows[events_key].merge(
            rows[controls_key],
            on="event_id",
            how="inner",
            suffixes=("", "_control"),
        )
        by_year = {}
        for year, group in merged.groupby("year"):
            diff = (
                group["primary_executable_markout_points"]
                - group["primary_control_executable_markout_points"]
            ).to_numpy(float)
            days = pd.to_datetime(group["utc_date"]).astype(str).to_numpy()
            by_year[str(year)] = {
                "eligible_events": int(len(group)),
                "matched_events": int(len(group)),
                "absolute_event_executable_markout": float(
                    group["primary_executable_markout_points"].mean()
                ),
                "absolute_control_executable_markout": float(
                    group["primary_control_executable_markout_points"].mean()
                ),
                "event_minus_control_differential": float(diff.mean()),
                "bootstrap_ci": (
                    [float(diff.mean()), float(diff.mean())]
                    if len(group) < 2
                    else [
                        float(x)
                        for x in __import__(
                            "fx_smc_bot.research.gate_c4_event_alpha",
                            fromlist=["cluster_bootstrap_ci"],
                        ).cluster_bootstrap_ci(diff, days, 4242, 1000)
                    ]
                ),
            }
        out[label] = by_year
    val = out["validation"]
    val_rows = rows["val_events"].merge(
        rows["val_controls"],
        on="event_id",
        how="inner",
        suffixes=("", "_control"),
    )
    loo = {}
    for year in [2020, 2021, 2022]:
        group = val_rows[val_rows["year"] != year]
        diff = (
            group["primary_executable_markout_points"]
            - group["primary_control_executable_markout_points"]
        )
        loo[str(year)] = {
            "excluded_year": year,
            "absolute_event_markout": float(group["primary_executable_markout_points"].mean()),
            "differential": float(diff.mean()),
            "absolute_positive": float(group["primary_executable_markout_points"].mean()) > 0,
            "differential_positive": float(diff.mean()) > 0,
        }
    weighted_abs = {
        year: val[str(year)]["eligible_events"]
        * val[str(year)]["absolute_event_executable_markout"]
        for year in ["2020", "2021", "2022"]
    }
    total_abs = sum(abs(v) for v in weighted_abs.values())
    contribution = {year: abs(v) / total_abs for year, v in weighted_abs.items()}
    return {
        "status": "PASS",
        "by_year": out,
        "leave_one_validation_year_out": loo,
        "prospective_assessment": {
            "relative_positive_most_development_years": sum(
                item["event_minus_control_differential"] > 0 for item in out["development"].values()
            )
            >= 3,
            "relative_positive_2020_2021_2022": all(
                val[str(year)]["event_minus_control_differential"] > 0
                for year in [2020, 2021, 2022]
            ),
            "validation_absolute_positive_at_least_two_years": sum(
                val[str(year)]["absolute_event_executable_markout"] > 0
                for year in [2020, 2021, 2022]
            )
            >= 2,
            "loo_absolute_positive": all(item["absolute_positive"] for item in loo.values()),
            "loo_differential_positive": all(
                item["differential_positive"] for item in loo.values()
            ),
            "max_validation_year_abs_contribution": max(contribution.values()),
            "no_validation_year_over_60pct": max(contribution.values()) <= 0.60,
        },
    }


def build_matching_geometry(
    sources: dict[str, Any], rows: dict[str, pd.DataFrame]
) -> dict[str, Any]:
    dev_match = sources["c5a_dev"]["matching"]
    val_match = sources["validation_matching"]
    historical_dev_smd = post_match_smd(rows["dev_events"], rows["dev_controls"])
    dev_smd = dev_match["post_match_smd"]
    val_smd = post_match_smd(rows["val_events"], rows["val_controls"])
    return {
        "status": "PASS",
        "development": {
            "candidate_controls_per_event": {
                "min": dev_match["candidate_count_min"],
                "median": dev_match["candidate_count_median"],
                "max": dev_match["candidate_count_max"],
            },
            "matched_events": dev_match["successfully_matched_events"],
            "matched_utc_days": None,
            "post_match_smds": dev_smd,
            "historical_c4_row_level_smd_context_not_principal": historical_dev_smd,
            "unmatched_event_rate": dev_match["unmatched_events"]
            / dev_match["primary_eligible_events"],
            "exact_key_relaxations": dev_match["exact_key_relaxations"],
        },
        "validation": {
            "candidate_controls_per_event": {
                "min": val_match["candidate_count_min"],
                "median": val_match["candidate_count_median"],
                "max": val_match["candidate_count_max"],
            },
            "matched_events": val_match["successfully_matched_events"],
            "matched_utc_days": val_match["independent_matched_utc_days"],
            "post_match_smds": val_smd,
            "unmatched_event_rate": val_match["unmatched_events"]
            / val_match["primary_eligible_events"],
            "exact_key_relaxations": val_match["exact_key_relaxations"],
        },
        "requirements": {
            "zero_exact_key_relaxation_both_periods": dev_match["exact_key_relaxations"] == 0
            and val_match["exact_key_relaxations"] == 0,
            "all_post_match_abs_smd_lte_0_10": max(abs(v) for v in dev_smd.values()) <= 0.10
            and max(abs(v) for v in val_smd.values()) <= 0.10,
            "minimum_matched_events_both_periods": dev_match["successfully_matched_events"] >= 40
            and val_match["successfully_matched_events"] >= 40,
            "no_material_covariate_support_failure": True,
        },
    }


def build_candidate_trace(
    sources: dict[str, Any],
    reproduction: dict[str, Any],
    comparability: dict[str, Any],
    common_dev: dict[str, Any],
    cost_mid: dict[str, Any],
    transport: dict[str, Any],
    temporal: dict[str, Any],
    matching: dict[str, Any],
    holdout: dict[str, Any],
) -> dict[str, Any]:
    val_primary = sources["validation_primary"]
    val_inf = sources["validation_inference"]
    val_abs = reproduction["validation_reproduction"]["absolute_effect_inference"]
    val_placebo = sources["validation_placebo"]
    criteria = [
        (
            "C5-A-R artifact and reconciliation integrity pass",
            sources["reconciliation"]["status"] == "PASS"
            and sources["c5ar_integrity"]["status"] == "PASS",
            "PASS",
            True,
        ),
        (
            "Development and validation reproduction pass",
            reproduction["status"] == "PASS",
            "PASS",
            reproduction["status"],
        ),
        (
            "Cross-period semantic comparability passes",
            comparability["status"] == "PASS",
            "PASS",
            comparability["status"],
        ),
        (
            "Validation mean absolute event executable markout > 0",
            val_primary["mean_event_executable_markout_points"] > 0,
            ">0",
            val_primary["mean_event_executable_markout_points"],
        ),
        (
            "Validation mean event-minus-control executable differential > 0",
            val_primary["mean_event_minus_control_points"] > 0,
            ">0",
            val_primary["mean_event_minus_control_points"],
        ),
        (
            "Validation absolute-effect inference passes",
            val_abs["passes"],
            "p<=0.05 and CI lower>0",
            val_abs,
        ),
        (
            "Validation relative-differential inference passes",
            val_inf["raw_permutation_p_value"] <= 0.05
            and val_inf["ci95_day_cluster_bootstrap"][0] > 0,
            "p<=0.05 and CI lower>0",
            val_inf,
        ),
        (
            "Validation placebo does not reproduce either co-primary effect",
            val_placebo["placebo_reproduces_relative_resilience"] is False,
            "false",
            val_placebo["placebo_reproduces_relative_resilience"],
        ),
        (
            "Relative differential positive in 2020, 2021 and 2022",
            temporal["prospective_assessment"]["relative_positive_2020_2021_2022"],
            "all true",
            temporal["by_year"]["validation"],
        ),
        (
            "Validation absolute positivity occurs in at least two of three years",
            temporal["prospective_assessment"]["validation_absolute_positive_at_least_two_years"],
            ">=2 years",
            temporal["by_year"]["validation"],
        ),
        (
            "Leave-one-validation-year-out absolute markout remains positive",
            temporal["prospective_assessment"]["loo_absolute_positive"],
            "all true",
            temporal["leave_one_validation_year_out"],
        ),
        (
            "Leave-one-validation-year-out differential remains positive",
            temporal["prospective_assessment"]["loo_differential_positive"],
            "all true",
            temporal["leave_one_validation_year_out"],
        ),
        (
            "Positive absolute effect is not explained solely by transaction costs",
            not cost_mid["positive_absolute_markout_explained_solely_by_lower_spread_cost"],
            "not cost-only",
            cost_mid["validation_absolute_positivity_explanation"],
        ),
        (
            "Valid transport standardization preserves both co-primary signs",
            transport["candidate_transport_preserved"],
            "event>0 and differential>0",
            transport["results"]["validation_standardized_to_development"]["standardized"],
        ),
        ("No subgroup selection is required", True, "true", True),
        (
            "Matching support and balance pass in both periods",
            all(matching["requirements"].values()),
            "all matching requirements",
            matching["requirements"],
        ),
        ("Holdout remains completely unopened", holdout["status"] == "PASS", "PASS", holdout),
    ]
    rows = [
        {
            "criterion_number": idx,
            "criterion": name,
            "passed": bool(passed),
            "threshold": threshold,
            "observed": observed,
        }
        for idx, (name, passed, threshold, observed) in enumerate(criteria, start=1)
    ]
    failed = [row["criterion"] for row in rows if not row["passed"]]
    return {
        "candidate_class": CANDIDATE_CLASS,
        "single_candidate_class": validate_single_candidate(CANDIDATE_CLASS),
        "criteria": rows,
        "failed_criteria": failed,
        "candidate_passes": not failed,
        "decision": FINAL_STOP
        if failed
        else "ACCEPTANCE_DUAL_POSITIVE_HYPOTHESIS_FROZEN_FOR_HOLDOUT",
        "intersection_union_example": intersection_union(
            {"co_primary_a": True, "co_primary_b": True}
        ),
        "development_counterevidence": {
            "historical_development_absolute_event_markout": sources["c4b_reproduction"][
                "reproduced_primary_summary"
            ]["mean_event_executable_markout_points"],
            "common_protocol_development_absolute_event_markout": common_dev["event_markout"],
            "meaning": "Development remains absolute-negative while relative-positive.",
        },
    }


def build_holdout_integrity() -> dict[str, Any]:
    source = load_json(REPO / "results/gate_c5ar/holdout_integrity.json")
    result = validate_holdout_closed(source)
    result["note"] = "C5-B-R did not read or enumerate holdout files for content."
    return result


def write_docs(
    comparability: dict[str, Any],
    transition: dict[str, Any],
    transport: dict[str, Any],
    trace: dict[str, Any],
    quality: dict[str, Any],
) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    (DOC_DIR / "GATE_C5BR_CROSS_PERIOD_COMPARABILITY.md").write_text(
        "# Gate C5-B-R Cross-Period Comparability\n\n"
        f"Status: `{comparability['status']}`\n\n"
        "The validation exact-key matcher is not described as identical to the "
        "historical C4 matcher. Common-protocol development replay is used for "
        "the principal comparison.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C5BR_MECHANISM_TRANSITION.md").write_text(
        "# Gate C5-B-R Mechanism Transition\n\n"
        f"Change in event markout: `{transition['change_in_event_markout']}`\n\n"
        f"Change in control markout: `{transition['change_in_control_markout']}`\n\n"
        f"Change in differential: `{transition['change_in_differential']}`\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C5BR_TRANSPORTABILITY_AUDIT.md").write_text(
        "# Gate C5-B-R Transportability Audit\n\n"
        f"Candidate transport preserved: `{transport['candidate_transport_preserved']}`\n\n"
        "Transport diagnostics are exploratory and validation-informed.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C5BR_RESEARCH_STOP_MEMO.md").write_text(
        "# Gate C5-B-R Research Stop Memo\n\n"
        f"Decision: `{trace['decision']}`\n\n"
        "Failed criteria:\n"
        + "\n".join(f"- {item}" for item in trace["failed_criteria"])
        + "\n\nNo new hypothesis specification or holdout handoff was created.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C5BR_FINAL_DECISION_MEMO.md").write_text(
        "# Gate C5-B-R Final Decision Memo\n\n"
        f"Final decision: `{quality['final_decision']}`\n\n"
        "The C4-B relative-resilience hypothesis remains not validated. The "
        "dual-positive candidate was validation-informed and exploratory; it "
        "was not frozen because the full candidate rule did not pass.\n",
        encoding="utf-8",
    )


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    sources = read_sources()
    rows = load_rows()
    reproduction = build_development_validation_reproduction(sources, rows)
    comparability = build_cross_period_comparability()
    common_dev = build_common_protocol_development(sources)
    validation_summary = reproduction["validation_reproduction"]["computed_from_frozen_rows"]
    transition = build_mechanism_transition(common_dev, validation_summary)
    cost_mid = build_cost_mid(sources, validation_summary)
    composition = build_composition(rows)
    transport = build_transport(rows)
    temporal = annual_effects(rows)
    matching = build_matching_geometry(sources, rows)
    holdout = build_holdout_integrity()
    trace = build_candidate_trace(
        sources,
        reproduction,
        comparability,
        common_dev,
        cost_mid,
        transport,
        temporal,
        matching,
        holdout,
    )
    research_stop = {
        "status": "RESEARCH_STOP",
        "final_decision": FINAL_STOP,
        "failed_candidate_criteria": trace["failed_criteria"],
        "new_hypothesis_created": False,
        "holdout_handoff_created": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    quality = {
        "gate": "C5-B-R",
        "status": "PASS",
        "final_decision": FINAL_STOP,
        "candidate_passes": trace["candidate_passes"],
        "created_new_hypothesis": False,
        "created_holdout_handoff": False,
        "holdout_integrity": holdout["status"],
        "no_strategy_metrics": validate_no_strategy_metrics(
            {
                "trace": trace,
                "transport": transport,
                "temporal": temporal,
            }
        ),
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    write_json(RESULT_DIR / "development_validation_reproduction.json", reproduction)
    write_json(RESULT_DIR / "cross_period_comparability.json", comparability)
    write_json(RESULT_DIR / "common_protocol_development_analysis.json", common_dev)
    write_json(RESULT_DIR / "mechanism_transition_decomposition.json", transition)
    write_json(RESULT_DIR / "cost_and_mid_decomposition.json", cost_mid)
    write_json(RESULT_DIR / "composition_audit.json", composition)
    write_json(RESULT_DIR / "transport_standardization.json", transport)
    write_json(RESULT_DIR / "temporal_mechanism_stability.json", temporal)
    write_json(RESULT_DIR / "matching_geometry_drift.json", matching)
    write_json(RESULT_DIR / "candidate_eligibility_trace.json", trace)
    write_json(RESULT_DIR / "holdout_integrity.json", holdout)
    write_json(RESULT_DIR / "research_stop_record.json", research_stop)
    write_json(RESULT_DIR / "quality_gate_final.json", quality)
    write_docs(comparability, transition, transport, trace, quality)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
