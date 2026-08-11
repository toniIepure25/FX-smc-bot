"""A0R3B pass-strata exploratory discovery workflow.

A0R3B is intentionally complete-case only: it uses the pair-years that passed
the A0R3 quality gate and excludes failed pair-years before any outcome ranking.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r2_statistics import (
    benjamini_hochberg_fdr,
    deflated_sharpe_ratio,
    hansen_spa,
    holm_adjust,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    romano_wolf,
    white_reality_check,
)
from fx_smc_bot.research.a0r3_existing_data import (
    AVAILABLE_FIELDS,
    PAIRS,
    Paths,
    canonical_hash,
    invalid_ohlc,
    json_hash,
    load_trials,
    m5_frame,
    metrics_from_returns,
    month_dir,
    read_json,
    sha256_bytes,
    sha256_file,
    trial_signal,
    write_json,
)

RESULTS_ARTIFACT_ID = "A0R3B_PASS_STRATA_EXPLORATORY_DISCOVERY_V1"
PASS_STRATA = (
    ("EURUSD", 2015),
    ("GBPUSD", 2017),
    ("USDJPY", 2015),
    ("USDJPY", 2016),
    ("USDJPY", 2017),
)
FAILED_STRATA = (
    ("EURUSD", 2016),
    ("EURUSD", 2017),
    ("GBPUSD", 2015),
    ("GBPUSD", 2016),
)
MULTIVARIATE_LOCAL_FAMILIES = {
    "F07_CURRENCY_FACTOR_RESIDUALS",
    "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL",
}


@dataclass(frozen=True, slots=True)
class MarketRead:
    path: str
    pair: str
    side: str
    year: int
    month: int
    bytes: int
    sha256: str


class MarketReadGuard:
    def __init__(self) -> None:
        self.reads: list[MarketRead] = []

    def read_side(self, paths: Paths, pair: str, side: str, year: int, month: int) -> pd.DataFrame:
        if year >= 2018:
            raise ValueError("A0R3B_2018_PLUS_MARKET_DATA_ACCESS_FORBIDDEN")
        path = month_dir(paths.raw, pair, side, year, month) / "data.json"
        self.reads.append(
            MarketRead(
                path=str(path),
                pair=pair,
                side=side,
                year=year,
                month=month,
                bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
        rows = read_json(path)
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    f"{side}_open",
                    f"{side}_high",
                    f"{side}_low",
                    f"{side}_close",
                    f"{side}_volume",
                ]
            )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        frame = frame.rename(
            columns={
                "open": f"{side}_open",
                "high": f"{side}_high",
                "low": f"{side}_low",
                "close": f"{side}_close",
                "volume": f"{side}_volume",
            }
        )
        return frame[
            [
                "timestamp",
                f"{side}_open",
                f"{side}_high",
                f"{side}_low",
                f"{side}_close",
                f"{side}_volume",
            ]
        ].sort_values("timestamp")

    def assert_holdout_intact(self) -> None:
        bad = [read for read in self.reads if read.year >= 2018]
        if bad:
            raise AssertionError("A0R3B_2018_PLUS_MARKET_OR_OUTCOME_FILE_OPENED")


def paths_for_a0r3b(repo: Path) -> Paths:
    return Paths(
        repo=repo,
        raw=repo / "data" / "raw" / "dukascopy-node",
        results=repo / "results" / "gate_a0r3b",
        docs=repo / "docs" / "research" / "fx_alpha_discovery",
        trials=repo / "results" / "gate_a0r2" / "trial_materialization_v2.jsonl",
    )


def pass_strata_amendment(paths: Paths) -> dict[str, Any]:
    payload = {
        "artifact_id": "A0R3B_PROSPECTIVE_PASS_STRATA_AMENDMENT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "mode": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "amends": "A0R3 all-9-pair-year gate",
        "reason": "A0R3 outcomes were not observed; complete-case PASS strata are frozen.",
        "exploratory_pass_strata": [{"pair": pair, "year": year} for pair, year in PASS_STRATA],
        "excluded_failed_strata": [{"pair": pair, "year": year} for pair, year in FAILED_STRATA],
        "aggregation_rule": {
            "primary": "equal_weight_across_eligible_topology_units",
            "sensitivity": "observation_weighted_pooling",
            "no_performance_weighting": True,
            "no_year_or_pair_selection_after_outcomes": True,
            "single_unit_label": "SINGLE_STRATUM_EXPLORATORY_LEAD",
        },
        "holdout_policy": {
            "2018_internal_confirmation": "untouched",
            "2019_external_validation": "untouched",
            "2020_2022_replication": "untouched",
            "2023_2025_quarantine": "untouched",
        },
        "source_hashes": {
            "a0r2_trial_materialization_v2_jsonl": sha256_file(paths.trials),
        },
    }
    payload["self_hash"] = json_hash(payload)
    return payload


def pass_map() -> dict[str, set[int]]:
    out: dict[str, set[int]] = defaultdict(set)
    for pair, year in PASS_STRATA:
        out[pair].add(year)
    return dict(out)


def load_pass_strata_frames(
    paths: Paths, guard: MarketReadGuard
) -> dict[tuple[str, int], pd.DataFrame]:
    frames: dict[tuple[str, int], pd.DataFrame] = {}
    for pair, year in PASS_STRATA:
        monthly_frames: list[pd.DataFrame] = []
        for month in range(1, 13):
            bid = guard.read_side(paths, pair, "bid", year, month)
            ask = guard.read_side(paths, pair, "ask", year, month)
            monthly_frames.append(pd.merge(bid, ask, on="timestamp", how="inner"))
        frame = (
            pd.concat(monthly_frames, ignore_index=True)
            .drop_duplicates("timestamp", keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        frame["mid_close"] = (frame["bid_close"] + frame["ask_close"]) / 2.0
        frame["spread"] = frame["ask_close"] - frame["bid_close"]
        frame["mid_return"] = frame["mid_close"].pct_change().fillna(0.0)
        frames[(pair, year)] = frame
    guard.assert_holdout_intact()
    return frames


def freeze_pass_strata(
    paths: Paths,
    frames: dict[tuple[str, int], pd.DataFrame],
    guard: MarketReadGuard,
    amendment: dict[str, Any],
) -> dict[str, Any]:
    file_rows = [
        {
            "path": read.path,
            "pair": read.pair,
            "side": read.side,
            "year": read.year,
            "month": read.month,
            "bytes": read.bytes,
            "sha256": read.sha256,
        }
        for read in guard.reads
    ]
    strata_rows = []
    for pair, year in PASS_STRATA:
        frame = frames[(pair, year)]
        m5 = m5_frame(frame)
        strata_rows.append(
            {
                "pair": pair,
                "year": year,
                "rows_m1": int(len(frame)),
                "rows_m5": int(len(m5)),
                "negative_spreads": int((frame["ask_close"] < frame["bid_close"]).sum()),
                "invalid_ohlc_rows": invalid_ohlc(frame, "bid") + invalid_ohlc(frame, "ask"),
                "m1_canonical_hash": canonical_hash(frame),
                "m5_canonical_hash": canonical_hash(m5),
                "source_file_sha256_set_hash": sha256_bytes(
                    "".join(
                        sorted(
                            read.sha256
                            for read in guard.reads
                            if read.pair == pair and read.year == year
                        )
                    ).encode()
                ),
            }
        )
    freeze_inputs = {
        "amendment_hash": json_hash(amendment),
        "strata": strata_rows,
        "source_files": file_rows,
        "aggregation_rule": amendment["aggregation_rule"],
    }
    payload = {
        "artifact_id": "A0R3B_PASS_STRATA_DATASET_FREEZE_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "raw_root": str(paths.raw),
        "pass_strata": strata_rows,
        "excluded_failed_strata": [{"pair": pair, "year": year} for pair, year in FAILED_STRATA],
        "source_files": file_rows,
        "no_imputation": True,
        "no_synthetic_fills": True,
        "no_2018_plus_market_or_outcome_data_opened": True,
        "freeze_hash_inputs_hash": json_hash(freeze_inputs),
    }
    payload["frozen_dataset_sha256"] = json_hash(payload)
    return payload


def required_pairs_for_trial(config: dict[str, Any], family: str) -> tuple[set[str], list[str]]:
    required: set[str] = set()
    reasons: list[str] = []
    scope = config.get("instrument_or_portfolio_scope")
    if scope == "nine_pair_portfolio":
        reasons.append("scope_requires_nine_pair_portfolio")
    elif scope:
        if scope in PAIRS:
            required.add(str(scope))
        else:
            reasons.append(f"scope_pair_unavailable:{scope}")

    edge = config.get("cross_pair_edge")
    if isinstance(edge, dict):
        for key in ("leader", "target"):
            pair = edge.get(key)
            if pair in PAIRS:
                required.add(str(pair))
            elif pair:
                reasons.append(f"cross_pair_edge_{key}_unavailable:{pair}")

    triangle = config.get("triangle")
    if triangle:
        for pair in triangle:
            if pair in PAIRS:
                required.add(str(pair))
            else:
                reasons.append(f"triangle_leg_unavailable:{pair}")

    if family in MULTIVARIATE_LOCAL_FAMILIES and not edge and not triangle:
        required.update(PAIRS)

    missing_inputs = sorted(set(config.get("required_inputs", [])) - AVAILABLE_FIELDS)
    if missing_inputs:
        reasons.append("required_fields_unavailable:" + ",".join(missing_inputs))
    if not required and not reasons:
        reasons.append("no_executable_pair_topology")
    return required, reasons


def evaluation_pair(config: dict[str, Any], required_pairs: set[str]) -> str | None:
    edge = config.get("cross_pair_edge")
    if isinstance(edge, dict) and edge.get("target") in required_pairs:
        return str(edge["target"])
    scope = config.get("instrument_or_portfolio_scope")
    if scope in required_pairs:
        return str(scope)
    triangle = config.get("triangle")
    if triangle:
        for pair in reversed(triangle):
            if pair in required_pairs:
                return str(pair)
    return sorted(required_pairs)[0] if required_pairs else None


def topology_units(required_pairs: set[str], eval_pair: str | None) -> list[dict[str, Any]]:
    if eval_pair is None:
        return []
    available = pass_map()
    years = sorted(set.intersection(*(available.get(pair, set()) for pair in required_pairs)))
    return [
        {
            "topology_id": "+".join(sorted(required_pairs)) + f":{year}",
            "year": year,
            "legs": sorted(required_pairs),
            "evaluation_pair": eval_pair,
        }
        for year in years
        if year in available.get(eval_pair, set())
    ]


def pass_strata_trial_eligibility(trials: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for trial in trials:
        config = trial["full_configuration"]
        family = trial["family_id"]
        required_pairs, reasons = required_pairs_for_trial(config, family)
        eval_pair = evaluation_pair(config, required_pairs)
        units = topology_units(required_pairs, eval_pair)
        if required_pairs and not units:
            reasons.append("required_topology_has_no_complete_case_pass_strata")
        status = "ELIGIBLE" if not reasons and units else "INELIGIBLE"
        by_family[family][status] += int(trial.get("candidate_equivalent_weight", 1))
        rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": family,
                "status": status,
                "candidate_equivalent_weight": trial.get("candidate_equivalent_weight", 1),
                "required_pairs": sorted(required_pairs),
                "evaluation_pair": eval_pair if status == "ELIGIBLE" else None,
                "eligible_topology_units": units if status == "ELIGIBLE" else [],
                "topology_unit_count": len(units) if status == "ELIGIBLE" else 0,
                "ineligibility_reasons": reasons,
                "configuration_sha256": trial["configuration_sha256"],
            }
        )
    return {
        "artifact_id": "A0R3B_PASS_STRATA_TRIAL_ELIGIBILITY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "candidate_equivalent_count": sum(
            int(trial.get("candidate_equivalent_weight", 1)) for trial in trials
        ),
        "eligible_trials": sum(1 for row in rows if row["status"] == "ELIGIBLE"),
        "ineligible_trials": sum(1 for row in rows if row["status"] == "INELIGIBLE"),
        "filter_basis": [
            "available fields",
            "exact required pair topology",
            "complete-case PASS strata only",
        ],
        "performance_informed_filtering": False,
        "invalid_trials_remain_in_multiplicity_count": True,
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "rows": rows,
    }


def execution_components_bps(
    frame: pd.DataFrame, signal: pd.Series, cost_multiplier: float
) -> pd.DataFrame:
    position = signal.shift(1).fillna(0).astype(int)
    eastern = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York")
    local_time = eastern.dt.time
    rollover = (local_time >= datetime.strptime("16:30", "%H:%M").time()) & (
        local_time <= datetime.strptime("17:30", "%H:%M").time()
    )
    position.loc[rollover] = 0
    previous = position.shift(1).fillna(0).astype(int)
    mid = frame["mid_close"].astype(float)
    spread_bps = (frame["spread"].astype(float) / mid).replace([np.inf, -np.inf], np.nan).fillna(
        0.0
    ) * 10_000.0
    gross = previous * mid.pct_change().fillna(0.0) * 10_000.0
    turnover = (position - previous).abs()
    commission_slippage_bps = 0.10
    costs = turnover * cost_multiplier * (spread_bps / 2.0 + commission_slippage_bps)
    return pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "gross_bps": gross.astype(float),
            "cost_bps": costs.astype(float),
            "net_bps": (gross - costs).astype(float),
            "turnover": turnover.astype(float),
            "position": position.astype(int),
        }
    )


def unit_metrics(components: pd.DataFrame) -> dict[str, float | int]:
    net_metrics = metrics_from_returns(components["net_bps"])
    gross_total = float(components["gross_bps"].sum())
    cost_total = float(components["cost_bps"].sum())
    turnover = float(components["turnover"].sum())
    trades = int((components["turnover"] > 0).sum())
    return {
        **net_metrics,
        "gross_bps": round(gross_total, 6),
        "cost_bps": round(cost_total, 6),
        "turnover": round(turnover, 6),
        "trades": trades,
        "net_bps_per_trade": round(float(net_metrics["net_bps"]) / max(trades, 1), 9),
    }


def average_unit_metrics(unit_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    keys = [
        "bars",
        "net_bps",
        "gross_bps",
        "cost_bps",
        "mean_bps",
        "sharpe",
        "max_drawdown_bps",
        "positive_bar_rate",
        "p_value",
        "turnover",
        "trades",
        "net_bps_per_trade",
    ]
    out: dict[str, float | int] = {}
    for key in keys:
        values = [float(row["metrics"][key]) for row in unit_rows]
        value = float(np.mean(values)) if values else 0.0
        out[key] = int(round(value)) if key in {"bars", "trades"} else round(value, 9)
    return out


def evidence_tier(row: dict[str, Any]) -> str:
    if int(row["topology_unit_count"]) == 1:
        return "SINGLE_STRATUM_EXPLORATORY_LEAD"
    if row["cost_stress"]["survives_2_0x"] and row["cross_stratum_stability"] >= 0.5:
        return "MULTI_STRATUM_COST_ROBUST_EXPLORATORY"
    return "MULTI_STRATUM_EXPLORATORY"


def rank_rows_for_review(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row["corrected_significance"]["bh_fdr_p"]),
            not bool(row["cost_stress"]["survives_2_0x"]),
            -int(row["topology_unit_count"]),
            -float(row["cross_stratum_stability"]),
            -float(row["primary_equal_weight"]["net_bps"]),
            -float(row["corrected_significance"]["dsr"]),
            row["trial_id"],
        ),
    )[:limit]


def evaluate_pass_strata_trials(
    frames: dict[tuple[str, int], pd.DataFrame],
    trials: list[dict[str, Any]],
    eligibility: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    eligible = {row["trial_id"]: row for row in eligibility["rows"] if row["status"] == "ELIGIBLE"}
    result_rows: list[dict[str, Any]] = []
    p_values: list[float] = []
    sharpes: list[float] = []
    train_ranks: list[float] = []
    test_ranks: list[float] = []

    for trial in trials:
        eligible_row = eligible.get(trial["trial_id"])
        if eligible_row is None:
            continue
        unit_rows: list[dict[str, Any]] = []
        net_components: list[pd.DataFrame] = []
        for unit in eligible_row["eligible_topology_units"]:
            year = int(unit["year"])
            eval_pair = str(unit["evaluation_pair"])
            context = {pair: frames[(pair, year)] for pair in unit["legs"]}
            frame = frames[(eval_pair, year)]
            signal = trial_signal(frame, trial, context)
            base = execution_components_bps(frame, signal, 1.0)
            stress_15 = execution_components_bps(frame, signal, 1.5)
            stress_20 = execution_components_bps(frame, signal, 2.0)
            metrics = unit_metrics(base)
            unit_rows.append(
                {
                    "topology_id": unit["topology_id"],
                    "pair": eval_pair,
                    "year": year,
                    "legs": unit["legs"],
                    "metrics": metrics,
                    "stress_1_5x": unit_metrics(stress_15),
                    "stress_2_0x": unit_metrics(stress_20),
                }
            )
            net_components.append(base)

        primary = average_unit_metrics(unit_rows)
        pooled = pd.concat(net_components, ignore_index=True)
        observation_weighted = unit_metrics(pooled)
        net_positive = [float(unit["metrics"]["net_bps"]) > 0.0 for unit in unit_rows]
        stress_15_positive = [float(unit["stress_1_5x"]["net_bps"]) > 0.0 for unit in unit_rows]
        stress_20_positive = [float(unit["stress_2_0x"]["net_bps"]) > 0.0 for unit in unit_rows]
        stability = float(np.mean(net_positive)) if net_positive else 0.0
        row = {
            "trial_id": trial["trial_id"],
            "family_id": trial["family_id"],
            "status": "COMPLETED_EXPLORATORY",
            "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
            "configuration_sha256": trial["configuration_sha256"],
            "required_pairs": eligible_row["required_pairs"],
            "evaluation_pair": eligible_row["evaluation_pair"],
            "topology_unit_count": eligible_row["topology_unit_count"],
            "eligible_topology_units": eligible_row["eligible_topology_units"],
            "unit_results": unit_rows,
            "primary_equal_weight": primary,
            "observation_weighted_sensitivity": observation_weighted,
            "trade_count": int(sum(int(unit["metrics"]["trades"]) for unit in unit_rows)),
            "cross_stratum_stability": round(stability, 6),
            "cost_stress": {
                "survives_1_5x": bool(all(stress_15_positive)),
                "survives_2_0x": bool(all(stress_20_positive)),
                "survival_rate_1_5x": round(float(np.mean(stress_15_positive)), 6),
                "survival_rate_2_0x": round(float(np.mean(stress_20_positive)), 6),
            },
            "same_bar_handling": "adverse_first",
            "entry_latency": "one_completed_M1_bar",
            "rollover_restrictions": "16:30-17:30 America/New_York flat/no new entries",
            "synthetic_fills_used": 0,
            "aggregation": "equal_weight_across_eligible_topology_units",
        }
        row["evidence_tier"] = evidence_tier(row)
        p_values.append(float(primary["p_value"]))
        sharpes.append(float(primary["sharpe"]))
        if int(row["topology_unit_count"]) >= 2:
            unit_sharpes = [float(unit["metrics"]["sharpe"]) for unit in unit_rows]
            train_ranks.append(float(np.mean(unit_sharpes[:-1])))
            test_ranks.append(unit_sharpes[-1])
        result_rows.append(row)

    holm = holm_adjust(p_values) if p_values else []
    bh = benjamini_hochberg_fdr(p_values) if p_values else []
    rw = romano_wolf(p_values) if p_values else []
    for index, row in enumerate(result_rows):
        sharpe = float(row["primary_equal_weight"]["sharpe"])
        row["corrected_significance"] = {
            "raw_p": p_values[index],
            "holm_p": holm[index],
            "bh_fdr_p": bh[index],
            "romano_wolf_p": rw[index],
            "psr": probabilistic_sharpe_ratio(sharpe),
            "dsr": deflated_sharpe_ratio(sharpe, trial_count=1200),
        }

    scores = np.array(sharpes, dtype=float)
    pbo: float | str
    pbo_reason = ""
    if len(train_ranks) >= 2 and len(test_ranks) >= 2:
        train_rank = pd.Series(train_ranks).rank(pct=True).to_numpy(dtype=float)
        test_rank = pd.Series(test_ranks).rank(pct=True).to_numpy(dtype=float)
        pbo = probability_of_backtest_overfitting(
            float(np.mean(train_rank)), float(np.mean(test_rank))
        )
    else:
        pbo = "NOT_APPLICABLE"
        pbo_reason = "fewer_than_two_multi_stratum_candidates"

    multiple_testing = {
        "artifact_id": "A0R3B_MULTIPLE_TESTING_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "evaluated_trials": len(result_rows),
        "registered_candidate_equivalent_denominator": 1200,
        "white_reality_check_p": white_reality_check(scores) if len(scores) else "NOT_APPLICABLE",
        "hansen_spa_p": hansen_spa(scores) if len(scores) else "NOT_APPLICABLE",
        "pbo": pbo,
        "pbo_not_applicable_reason": pbo_reason,
        "methods": [
            "White Reality Check",
            "Hansen SPA",
            "Romano-Wolf",
            "Holm",
            "BH-FDR",
            "PSR",
            "DSR",
            "PBO",
        ],
    }
    results = {
        "artifact_id": "A0R3B_EXPLORATORY_RESULT_TABLE_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "evaluated_trials": len(result_rows),
        "rows": result_rows,
    }
    stress_rows = [
        {
            "trial_id": row["trial_id"],
            "family_id": row["family_id"],
            "topology_unit_count": row["topology_unit_count"],
            "base_net_bps": row["primary_equal_weight"]["net_bps"],
            "stress_1_5_survives_all_units": row["cost_stress"]["survives_1_5x"],
            "stress_2_0_survives_all_units": row["cost_stress"]["survives_2_0x"],
            "survival_rate_1_5x": row["cost_stress"]["survival_rate_1_5x"],
            "survival_rate_2_0x": row["cost_stress"]["survival_rate_2_0x"],
        }
        for row in result_rows
    ]
    cost_stress = {
        "artifact_id": "A0R3B_COST_STRESS_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "rows": stress_rows,
        "survivors_1_5x": sum(1 for row in stress_rows if row["stress_1_5_survives_all_units"]),
        "survivors_2_0x": sum(1 for row in stress_rows if row["stress_2_0_survives_all_units"]),
    }
    top_candidate_rows = rank_rows_for_review(result_rows, 10)
    shortlist_rows = sorted(
        [row for row in result_rows if float(row["primary_equal_weight"]["net_bps"]) > 0.0],
        key=lambda row: (
            float(row["corrected_significance"]["bh_fdr_p"]),
            not bool(row["cost_stress"]["survives_2_0x"]),
            -int(row["topology_unit_count"]),
            -float(row["cross_stratum_stability"]),
            -float(row["primary_equal_weight"]["net_bps"]),
            -float(row["corrected_significance"]["dsr"]),
            row["trial_id"],
        ),
    )[:24]
    single_stratum_rows = sorted(
        [
            row
            for row in result_rows
            if row["evidence_tier"] == "SINGLE_STRATUM_EXPLORATORY_LEAD"
            and float(row["primary_equal_weight"]["net_bps"]) > 0.0
        ],
        key=lambda row: (
            float(row["corrected_significance"]["bh_fdr_p"]),
            -float(row["primary_equal_weight"]["net_bps"]),
            row["trial_id"],
        ),
    )[:24]
    shortlist = {
        "artifact_id": "A0R3B_EXPLORATORY_SHORTLIST_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "cap": 24,
        "selection_rule": (
            "corrected_significance_then_cost_robustness_then_sample_support_then_"
            "stability_then_net_economics"
        ),
        "shortlist_size": len(shortlist_rows),
        "rows": shortlist_rows,
    }
    top_candidates = {
        "artifact_id": "A0R3B_TOP_EXPLORATORY_CANDIDATES_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "ranking_rule": (
            "corrected_significance_then_cost_robustness_then_sample_support_then_"
            "stability_then_net_economics"
        ),
        "note": (
            "ranked review table; candidates are not promoted into the shortlist "
            "unless net-positive"
        ),
        "rows": top_candidate_rows,
    }
    single_stratum = {
        "artifact_id": "A0R3B_SINGLE_STRATUM_LEADS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "rows": single_stratum_rows,
        "lead_count": len(single_stratum_rows),
    }
    return results, multiple_testing, cost_stress, shortlist, single_stratum, top_candidates


def write_report(paths: Paths, artifacts: dict[str, Any]) -> None:
    freeze = artifacts["freeze"]
    eligibility = artifacts["trial_eligibility"]
    results = artifacts["results"]
    testing = artifacts["multiple_testing"]
    stress = artifacts["cost_stress"]
    shortlist = artifacts["shortlist"]
    single = artifacts["single_stratum_leads"]
    top_candidates = artifacts["top_candidates"]
    lines = [
        "# A0R3B Pass-Strata Exploratory Discovery",
        "",
        "Status: `EXPLORATORY_NOT_VALIDATED_ALPHA`",
        "",
        f"Freeze hash: `{freeze['frozen_dataset_sha256']}`",
        f"Evaluated trials: `{results['evaluated_trials']}` of `1200` registered trials.",
        f"Shortlist size: `{shortlist['shortlist_size']}`",
        (
            "2018+ market/outcome files opened: "
            f"`{artifacts['summary']['opened_2018_plus_market_or_outcome_files']}`"
        ),
        "",
        "## PASS Strata",
        "",
        "| Pair | Year | M1 rows | M5 rows | M1 hash | M5 hash |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in freeze["pass_strata"]:
        lines.append(
            "| {pair} | {year} | {m1} | {m5} | `{h1}` | `{h5}` |".format(
                pair=row["pair"],
                year=row["year"],
                m1=row["rows_m1"],
                m5=row["rows_m5"],
                h1=row["m1_canonical_hash"][:16],
                h5=row["m5_canonical_hash"][:16],
            )
        )
    lines.extend(
        [
            "",
            "Excluded failed strata: "
            + ", ".join(f"`{pair}-{year}`" for pair, year in FAILED_STRATA),
            "",
            "## Trial Eligibility By Family",
            "",
            "| Family | Eligible | Ineligible |",
            "|---|---:|---:|",
        ]
    )
    for family, counts in eligibility["by_family"].items():
        lines.append(f"| {family} | {counts.get('ELIGIBLE', 0)} | {counts.get('INELIGIBLE', 0)} |")
    lines.extend(
        [
            "",
            "## Multiple Testing",
            "",
            f"- White Reality Check p: `{testing['white_reality_check_p']}`",
            f"- Hansen SPA p: `{testing['hansen_spa_p']}`",
            f"- PBO: `{testing['pbo']}`",
            f"- PBO note: `{testing.get('pbo_not_applicable_reason', '')}`",
            "",
            "## Cost Stress",
            "",
            f"- 1.5x survivors: `{stress['survivors_1_5x']}`",
            f"- 2.0x survivors: `{stress['survivors_2_0x']}`",
            "",
            "## Top 10 Exploratory Candidates",
            "",
            (
                "| Trial | Family | Units | Tier | Trades | Net bps | Net/trade | Sharpe | "
                "BH-FDR | PSR | DSR | 1.5x | 2.0x |"
            ),
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in top_candidates["rows"]:
        metrics = row["primary_equal_weight"]
        sig = row["corrected_significance"]
        lines.append(
            (
                "| {trial} | {family} | {units} | {tier} | {trades} | {net:.3f} | "
                "{per_trade:.6f} | {sharpe:.3f} | {bh:.6f} | {psr:.6f} | "
                "{dsr:.6f} | {s15} | {s20} |"
            ).format(
                trial=row["trial_id"],
                family=row["family_id"],
                units=row["topology_unit_count"],
                tier=row["evidence_tier"],
                trades=row["trade_count"],
                net=float(metrics["net_bps"]),
                per_trade=float(metrics["net_bps_per_trade"]),
                sharpe=float(metrics["sharpe"]),
                bh=float(sig["bh_fdr_p"]),
                psr=float(sig["psr"]),
                dsr=float(sig["dsr"]),
                s15=row["cost_stress"]["survives_1_5x"],
                s20=row["cost_stress"]["survives_2_0x"],
            )
        )
    lines.extend(
        [
            "",
            "## Top Exploratory Shortlist",
            "",
            (
                "| Trial | Family | Units | Tier | Trades | Net bps | Net/trade | Sharpe | "
                "BH-FDR | PSR | DSR | 1.5x | 2.0x |"
            ),
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in shortlist["rows"]:
        metrics = row["primary_equal_weight"]
        sig = row["corrected_significance"]
        lines.append(
            (
                "| {trial} | {family} | {units} | {tier} | {trades} | {net:.3f} | "
                "{per_trade:.6f} | {sharpe:.3f} | {bh:.6f} | {psr:.6f} | "
                "{dsr:.6f} | {s15} | {s20} |"
            ).format(
                trial=row["trial_id"],
                family=row["family_id"],
                units=row["topology_unit_count"],
                tier=row["evidence_tier"],
                trades=row["trade_count"],
                net=float(metrics["net_bps"]),
                per_trade=float(metrics["net_bps_per_trade"]),
                sharpe=float(metrics["sharpe"]),
                bh=float(sig["bh_fdr_p"]),
                psr=float(sig["psr"]),
                dsr=float(sig["dsr"]),
                s15=row["cost_stress"]["survives_1_5x"],
                s20=row["cost_stress"]["survives_2_0x"],
            )
        )
    lines.extend(
        [
            "",
            "## Interesting Single-Stratum Leads",
            "",
            "| Trial | Family | Stratum | Net bps | Sharpe | BH-FDR | DSR |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in single["rows"]:
        unit = row["eligible_topology_units"][0]
        metrics = row["primary_equal_weight"]
        sig = row["corrected_significance"]
        lines.append(
            "| {trial} | {family} | {pair}-{year} | {net:.3f} | {sharpe:.3f} | "
            "{bh:.6f} | {dsr:.6f} |".format(
                trial=row["trial_id"],
                family=row["family_id"],
                pair=unit["evaluation_pair"],
                year=unit["year"],
                net=float(metrics["net_bps"]),
                sharpe=float(metrics["sharpe"]),
                bh=float(sig["bh_fdr_p"]),
                dsr=float(sig["dsr"]),
            )
        )
    paths.docs.mkdir(parents=True, exist_ok=True)
    (paths.docs / "A0R3B_PASS_STRATA_EXPLORATORY_DISCOVERY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run(paths: Paths) -> dict[str, Any]:
    paths.results.mkdir(parents=True, exist_ok=True)
    amendment = pass_strata_amendment(paths)
    trials = load_trials(paths)
    eligibility = pass_strata_trial_eligibility(trials)
    guard = MarketReadGuard()
    frames = load_pass_strata_frames(paths, guard)
    freeze = freeze_pass_strata(paths, frames, guard, amendment)
    results, multiple_testing, cost_stress, shortlist, single_stratum, top_candidates = (
        evaluate_pass_strata_trials(frames, trials, eligibility)
    )
    artifacts = {
        "amendment": amendment,
        "freeze": freeze,
        "trial_eligibility": eligibility,
        "results": results,
        "multiple_testing": multiple_testing,
        "cost_stress": cost_stress,
        "shortlist": shortlist,
        "single_stratum_leads": single_stratum,
        "top_candidates": top_candidates,
    }
    hashes = {
        name: write_json(paths.results / f"{name}.json", artifact)
        for name, artifact in artifacts.items()
    }
    opened_2018_plus = [read.path for read in guard.reads if read.year >= 2018]
    summary = {
        "artifact_id": "A0R3B_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "artifact_hashes": hashes,
        "frozen_dataset_sha256": freeze["frozen_dataset_sha256"],
        "pass_strata": [{"pair": pair, "year": year} for pair, year in PASS_STRATA],
        "excluded_failed_strata": [{"pair": pair, "year": year} for pair, year in FAILED_STRATA],
        "eligible_trials": eligibility["eligible_trials"],
        "ineligible_trials": eligibility["ineligible_trials"],
        "evaluated_trials": results["evaluated_trials"],
        "shortlist_size": shortlist["shortlist_size"],
        "single_stratum_lead_count": single_stratum["lead_count"],
        "top_candidate_count": len(top_candidates["rows"]),
        "opened_market_data_file_count": len(guard.reads),
        "opened_2018_plus_market_or_outcome_files": opened_2018_plus,
        "any_2018_plus_market_or_outcome_data_accessed": bool(opened_2018_plus),
        "raw_market_data_modified": False,
    }
    write_json(paths.results / "summary.json", summary)
    artifacts["summary"] = summary
    write_report(paths, artifacts)
    return summary
