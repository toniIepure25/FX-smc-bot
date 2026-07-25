"""Gate C.5-B-R mechanism-transition audit helpers.

The helpers operate on frozen C4/C5 compact and row-level artifacts only. They
do not read or enumerate holdout data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.gate_c4_event_alpha import (
    cluster_bootstrap_ci,
    paired_permutation_p_value,
)

CANDIDATE_CLASS = "DUAL_POSITIVE_ACCEPTANCE_RESPONSE"
FINAL_STOP = "VALIDATION_SIGNAL_NONTRANSPORTABLE_RESEARCH_STOP"
FINAL_FREEZE = "ACCEPTANCE_DUAL_POSITIVE_HYPOTHESIS_FROZEN_FOR_HOLDOUT"
PROHIBITED_STRATEGY_METRICS = {
    "pnl",
    "equity",
    "sharpe",
    "sortino",
    "drawdown",
    "profit_factor",
    "position_sizing",
}


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def mean(values: pd.Series | np.ndarray) -> float:
    return float(np.mean(np.asarray(values, dtype=float)))


def smd(a: pd.Series, b: pd.Series) -> float:
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    pooled = np.sqrt((np.var(av, ddof=1) + np.var(bv, ddof=1)) / 2.0)
    if pooled == 0:
        return 0.0
    return float((np.mean(av) - np.mean(bv)) / pooled)


def effective_sample_size(weights: np.ndarray) -> float:
    weights = np.asarray(weights, dtype=float)
    if np.sum(weights) == 0:
        return 0.0
    return float(np.square(weights.sum()) / np.square(weights).sum())


def normalized_weight_diagnostics(weights: np.ndarray) -> dict[str, float | bool]:
    weights = np.asarray(weights, dtype=float)
    median = float(np.median(weights))
    max_weight = float(np.max(weights))
    return {
        "effective_sample_size": effective_sample_size(weights),
        "maximum_weight": max_weight,
        "p99_weight": float(np.quantile(weights, 0.99)),
        "weight_coefficient_of_variation": float(np.std(weights) / np.mean(weights)),
        "max_weight_median_multiple": max_weight / median if median else float("inf"),
    }


def infer_absolute_effect(
    values: np.ndarray,
    days: np.ndarray,
    seed: int = 4242,
    iterations: int = 2000,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    return {
        "mean": mean(values),
        "sign_flip_permutation_p_value": paired_permutation_p_value(
            np.asarray(values, dtype=float),
            seed,
            iterations,
        ),
        "ci95_day_cluster_bootstrap": cluster_bootstrap_ci(
            np.asarray(values, dtype=float),
            np.asarray(days),
            seed,
            bootstrap_iterations,
        ),
        "passes": None,
    }


def summarize_pairs(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls,
        on="event_id",
        how="inner",
        suffixes=("", "_control"),
    )
    event = merged["primary_executable_markout_points"].to_numpy(float)
    control = merged["primary_control_executable_markout_points"].to_numpy(float)
    diff = event - control
    days = pd.to_datetime(merged["utc_date"]).astype(str).to_numpy()
    return {
        "n": int(len(merged)),
        "mean_event_executable_markout_points": mean(event),
        "mean_control_executable_markout_points": mean(control),
        "mean_event_minus_control_points": mean(diff),
        "mean_event_mid_return_points": mean(merged["primary_mid_markout_points"]),
        "mean_control_mid_return_points": mean(merged["primary_control_mid_markout_points"]),
        "event_minus_control_mid_differential": mean(
            merged["primary_mid_markout_points"] - merged["primary_control_mid_markout_points"]
        ),
        "paired_permutation_p_value": paired_permutation_p_value(diff, 4242, 2000),
        "ci95_day_cluster_bootstrap": cluster_bootstrap_ci(diff, days, 4242, 1000),
        "positive_event_probability": float(np.mean(event > 0)),
        "positive_control_probability": float(np.mean(control > 0)),
    }


def primary_validation(events: pd.DataFrame) -> pd.DataFrame:
    return events[(events["non_overlap_primary"]) & (events["h120_complete"])].copy()


def primary_development(events: pd.DataFrame) -> pd.DataFrame:
    family = "liquidity_acceptance_fvg_continuation"
    return events[
        (events["family"] == family) & (events["non_overlap_primary"]) & (events["h120_complete"])
    ].copy()


def post_match_smd(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, float]:
    merged = events.merge(controls, on="event_id", how="inner")
    covariates = {
        "spread": ("spread", "control_spread"),
        "atr": ("atr", "control_atr"),
        "pre_event_volatility": (
            "pre_event_volatility",
            "control_pre_event_volatility",
        ),
        "pre_event_trend": ("pre_event_trend", "control_pre_event_trend"),
        "range_position": ("range_position", "control_range_position"),
    }
    return {
        name: smd(merged[event_col], merged[control_col])
        for name, (event_col, control_col) in covariates.items()
    }


def exact_cell_weights(
    source: pd.DataFrame,
    target: pd.DataFrame,
    columns: list[str],
) -> np.ndarray:
    source_keys = source[columns].astype(str).agg("|".join, axis=1)
    target_keys = target[columns].astype(str).agg("|".join, axis=1)
    source_freq = source_keys.value_counts(normalize=True)
    target_freq = target_keys.value_counts(normalize=True)
    weights = source_keys.map(lambda key: target_freq.get(key, 0.0) / source_freq[key])
    return weights.to_numpy(float)


def add_transport_bins(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for src, dst in [
        ("spread", "spread_bin"),
        ("atr", "atr_bin"),
        ("pre_event_volatility", "volatility_bin"),
        ("pre_event_trend", "trend_bin"),
        ("range_position", "range_position_bin"),
    ]:
        out[dst] = pd.qcut(out[src].rank(method="first"), 3, labels=False)
    return out


@dataclass(frozen=True, slots=True)
class CandidateCriterion:
    number: int
    name: str
    passed: bool
    observed: Any
    threshold: Any


def intersection_union(passes: dict[str, bool]) -> bool:
    return bool(passes.get("co_primary_a") and passes.get("co_primary_b"))


def validate_single_candidate(candidate_class: str) -> bool:
    return candidate_class == CANDIDATE_CLASS


def validate_no_strategy_metrics(payload: Any) -> bool:
    text = json.dumps(payload, sort_keys=True).lower()
    return not any(metric in text for metric in PROHIBITED_STRATEGY_METRICS)


def validate_holdout_closed(holdout: dict[str, Any]) -> dict[str, Any]:
    flags = [
        "holdout_market_data_loaded",
        "holdout_structural_data_inspected",
        "holdout_files_enumerated_for_content",
        "holdout_events_detected",
        "holdout_event_counts_computed",
        "holdout_controls_constructed",
        "holdout_outcomes_computed",
        "holdout_results_reported",
    ]
    checks = {flag: bool(holdout.get(flag, False)) for flag in flags}
    violations = [flag for flag, value in checks.items() if value]
    return {
        "checks": checks,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }
