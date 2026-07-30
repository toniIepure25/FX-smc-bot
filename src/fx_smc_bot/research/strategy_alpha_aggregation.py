"""Gate P0-R aggregate-only result helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy import stats  # type: ignore[import-untyped]

from fx_smc_bot.research.statistical_inference import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from fx_smc_bot.research.strategy_alpha import canonical_json_sha256

ROW_LEVEL_FORBIDDEN_KEYS = {
    "signal_id",
    "order_id",
    "trade_id",
    "timestamp",
    "entry_timestamp",
    "exit_timestamp",
    "entry_price",
    "exit_price",
    "individual_pnl",
    "pnl",
}


@dataclass(frozen=True, slots=True)
class AggregateResult:
    candidate_id: str
    window: str
    label: str
    execution_status: str
    trade_count: int
    gross_expectancy_r: float
    net_expectancy_r: float
    day_cluster_ci: tuple[float, float] | None
    profit_factor: float | None
    sharpe: float | None
    probabilistic_sharpe: float | None
    deflated_sharpe: float | None
    max_drawdown_r: float | None
    cost_drag_r: float | None
    stress_1_5x_net_expectancy_r: float | None
    stress_2_0x_net_expectancy_r: float | None
    risk_0_25_pct_return: float | None
    risk_0_50_pct_return: float | None
    matched_benchmark_alpha: float | None
    unadjusted_p_value: float | None
    holm_adjusted_p_value: float | None
    reason: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def blocked_aggregate_result(candidate_id: str, window: str) -> AggregateResult:
    return AggregateResult(
        candidate_id=candidate_id,
        window=window,
        label="EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY",
        execution_status="NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
        trade_count=0,
        gross_expectancy_r=0.0,
        net_expectancy_r=0.0,
        day_cluster_ci=None,
        profit_factor=None,
        sharpe=None,
        probabilistic_sharpe=None,
        deflated_sharpe=None,
        max_drawdown_r=None,
        cost_drag_r=None,
        stress_1_5x_net_expectancy_r=None,
        stress_2_0x_net_expectancy_r=None,
        risk_0_25_pct_return=None,
        risk_0_50_pct_return=None,
        matched_benchmark_alpha=None,
        unadjusted_p_value=None,
        holm_adjusted_p_value=None,
        reason="Candidate lacks full permitted historical bid/ask coverage certification.",
    )


def contains_forbidden_row_level_keys(payload: Any) -> bool:
    if isinstance(payload, dict):
        keys = {str(key).lower() for key in payload}
        if keys & ROW_LEVEL_FORBIDDEN_KEYS:
            return True
        return any(contains_forbidden_row_level_keys(value) for value in payload.values())
    if isinstance(payload, list):
        return any(contains_forbidden_row_level_keys(item) for item in payload)
    return False


def aggregate_schema_hash(payload: Any) -> str:
    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): shape(child) for key, child in sorted(value.items())}
        if isinstance(value, list):
            return [shape(value[0])] if value else []
        return type(value).__name__

    return canonical_json_sha256(shape(payload))


def aggregate_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return canonical_json_sha256(json.loads(encoded))


def cluster_bootstrap_mean_ci(
    values: np.ndarray,
    clusters: np.ndarray,
    *,
    seed: int = 1729,
    iterations: int = 5_000,
) -> tuple[float, float]:
    """Bootstrap a mean while preserving sampled-cluster multiplicity."""
    if len(values) == 0:
        return (0.0, 0.0)
    labels = np.unique(clusters)
    grouped = [values[clusters == label] for label in labels]
    rng = np.random.default_rng(seed)
    estimates = np.empty(iterations, dtype=np.float64)
    for idx in range(iterations):
        sampled = rng.integers(0, len(grouped), size=len(grouped))
        total = sum(float(np.sum(grouped[item])) for item in sampled)
        count = sum(len(grouped[item]) for item in sampled)
        estimates[idx] = total / count if count else 0.0
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return float(lower), float(upper)


def paired_cluster_signflip_p(
    differences: np.ndarray,
    clusters: np.ndarray,
    *,
    seed: int = 1729,
    iterations: int = 5_000,
) -> float:
    """One-sided paired cluster sign-flip test for positive mean alpha."""
    if len(differences) == 0:
        return 1.0
    labels = np.unique(clusters)
    grouped = [differences[clusters == label] for label in labels]
    observed = float(np.mean(differences))
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=len(grouped))
        total = sum(
            float(sign * np.sum(group))
            for sign, group in zip(signs, grouped, strict=True)
        )
        statistic = total / len(differences)
        exceed += int(statistic >= observed)
    return float((exceed + 1) / (iterations + 1))


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _profit_factor(values: np.ndarray) -> float:
    gains = float(np.sum(values[values > 0]))
    losses = abs(float(np.sum(values[values < 0])))
    return gains / losses if losses > 0 else float("inf")


def _drawdown(values: np.ndarray) -> float:
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    peaks = np.maximum.accumulate(cumulative)
    return abs(float(np.min(cumulative - peaks)))


def _risk_simulation(values: np.ndarray, risk_fraction: float) -> tuple[float, float]:
    equity = np.cumprod(1.0 + np.clip(values * risk_fraction, -0.999, None))
    if len(equity) == 0:
        return 0.0, 0.0
    path = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(path)
    drawdown = (peaks - path) / peaks
    return float(path[-1] - 1.0), float(np.max(drawdown))


def performance_metrics(
    frame: pd.DataFrame,
    *,
    n_trials: int = 4,
    seed: int = 1729,
) -> dict[str, Any]:
    """Compute the complete frozen aggregate metric set from a trade ledger."""
    if frame.empty:
        return {"trade_count": 0, "status": "INSUFFICIENT_SAMPLE"}
    ordered = frame.sort_values(["entry_time", "instrument", "position_id"])
    net = ordered["net_r"].to_numpy(dtype=np.float64)
    gross = ordered["gross_r"].to_numpy(dtype=np.float64)
    stress_1_5 = ordered["stress_1_5x_net_r"].to_numpy(dtype=np.float64)
    stress_2 = ordered["stress_2_0x_net_r"].to_numpy(dtype=np.float64)
    entry = pd.to_datetime(ordered["entry_time"], utc=True)
    days = entry.dt.strftime("%Y-%m-%d").to_numpy()
    weeks = entry.dt.strftime("%G-W%V").to_numpy()
    daily = pd.Series(net).groupby(days).sum().to_numpy(dtype=np.float64)
    daily_std = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0
    daily_mean = float(np.mean(daily))
    sharpe = daily_mean / daily_std * np.sqrt(252.0) if daily_std > 0 else 0.0
    downside = daily[daily < 0]
    downside_dev = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    sortino = daily_mean / downside_dev * np.sqrt(252.0) if downside_dev > 0 else 0.0
    daily_sr = daily_mean / daily_std if daily_std > 0 else 0.0
    skew = float(stats.skew(daily)) if len(daily) > 2 else 0.0
    kurtosis = float(stats.kurtosis(daily, fisher=False)) if len(daily) > 3 else 3.0
    psr = probabilistic_sharpe_ratio(daily_sr, 0.0, len(daily), skew, kurtosis)
    dsr = deflated_sharpe_ratio(daily_sr, len(daily), n_trials, skew, kurtosis)
    max_drawdown_r = _drawdown(net)
    elapsed_years = max(
        1.0 / 365.25,
        (entry.max() - entry.min()).total_seconds() / (365.25 * 86_400),
    )
    calmar = (float(np.sum(net)) / elapsed_years / max_drawdown_r) if max_drawdown_r else 0.0
    _, cvar_95 = (
        float(np.quantile(net, 0.05)),
        float(np.mean(net[net <= np.quantile(net, 0.05)])),
    )
    return_025, drawdown_025 = _risk_simulation(net, 0.0025)
    return_050, drawdown_050 = _risk_simulation(net, 0.0050)
    positive = ordered.loc[ordered["net_r"] > 0, ["net_r", "entry_time"]].copy()
    positive_total = float(positive["net_r"].sum())
    best_trade_share = float(positive["net_r"].max() / positive_total) if positive_total else 0.0
    best_5_share = (
        float(positive["net_r"].nlargest(5).sum() / positive_total)
        if positive_total else 0.0
    )
    positive["month"] = pd.to_datetime(positive["entry_time"]).dt.to_period("M")
    positive["year"] = pd.to_datetime(positive["entry_time"]).dt.year
    best_month_share = (
        float(positive.groupby("month")["net_r"].sum().max() / positive_total)
        if positive_total else 0.0
    )
    best_year_share = (
        float(positive.groupby("year")["net_r"].sum().max() / positive_total)
        if positive_total else 0.0
    )
    years = entry.dt.year.to_numpy()
    yearly_counts = {
        str(int(year)): int(np.sum(years == year)) for year in np.unique(years)
    }
    yearly_means = {
        str(int(year)): float(np.mean(net[years == year])) for year in np.unique(years)
    }
    leave_one_year_out = {
        str(int(year)): float(np.mean(net[years != year]))
        for year in np.unique(years)
        if np.any(years != year)
    }
    return {
        "trade_count": int(len(ordered)),
        "gross_r": float(np.sum(gross)),
        "net_r": float(np.sum(net)),
        "mean_net_r": float(np.mean(net)),
        "median_net_r": float(np.median(net)),
        "win_rate": float(np.mean(net > 0)),
        "average_win_r": _finite(float(np.mean(net[net > 0]))) if np.any(net > 0) else None,
        "average_loss_r": _finite(float(np.mean(net[net < 0]))) if np.any(net < 0) else None,
        "profit_factor": _finite(_profit_factor(net)),
        "sharpe": float(sharpe),
        "probabilistic_sharpe": float(psr),
        "deflated_sharpe": float(dsr),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "maximum_drawdown_r": float(max_drawdown_r),
        "maximum_drawdown_pct_at_0_50pct_risk": float(drawdown_050),
        "cvar_95_r": float(cvar_95),
        "cost_drag_r": float(np.sum(gross - net)),
        "mean_stress_1_5x_net_r": float(np.mean(stress_1_5)),
        "mean_stress_2_0x_net_r": float(np.mean(stress_2)),
        "risk_0_25_pct_return": float(return_025),
        "risk_0_50_pct_return": float(return_050),
        "risk_0_25_pct_max_drawdown": float(drawdown_025),
        "risk_0_50_pct_max_drawdown": float(drawdown_050),
        "day_cluster_ci": cluster_bootstrap_mean_ci(net, days, seed=seed),
        "week_cluster_ci": cluster_bootstrap_mean_ci(net, weeks, seed=seed + 1),
        "best_trade_share": best_trade_share,
        "best_5_trade_share": best_5_share,
        "best_month_share": best_month_share,
        "best_year_share": best_year_share,
        "yearly_trade_counts": yearly_counts,
        "yearly_mean_net_r": yearly_means,
        "leave_one_year_out_mean_net_r": leave_one_year_out,
        "leave_one_year_out_positive": all(value > 0 for value in leave_one_year_out.values()),
        "years_with_20_or_more_trades": sum(value >= 20 for value in yearly_counts.values()),
        "status": "PASS",
    }


def adjudicate_frozen_tiers(
    combined_metrics: dict[str, dict[str, Any]],
    window_metrics: dict[str, dict[str, dict[str, Any]]],
    holm_p_values: dict[str, float],
    benchmark_alpha: dict[str, float],
) -> dict[str, Any]:
    """Apply the P0 Tier A/B rules mechanically without manual overrides."""
    rows = []
    for candidate_id, metrics in sorted(combined_metrics.items()):
        sample_ok = (
            metrics["trade_count"] >= 100
            and metrics["years_with_20_or_more_trades"] >= 3
        )
        positive_windows = sum(
            window_metrics[candidate_id][window].get("mean_net_r", 0.0) > 0
            for window in ("engineering", "historical_replay", "historical_stress")
        )
        tier_a = {
            "minimum_sample": sample_ok,
            "mean_net_r_gt_0": metrics["mean_net_r"] > 0,
            "day_cluster_ci_lower_gt_0": metrics["day_cluster_ci"][0] > 0,
            "profit_factor_gt_1_05": (metrics["profit_factor"] or 0) > 1.05,
            "base_and_1_5x_cost_positive": (
                metrics["mean_net_r"] > 0 and metrics["mean_stress_1_5x_net_r"] > 0
            ),
            "leave_one_year_out_positive": metrics["leave_one_year_out_positive"],
            "best_5_trades_lt_35pct": metrics["best_5_trade_share"] < 0.35,
            "best_year_lt_50pct": metrics["best_year_share"] < 0.50,
            "max_drawdown_lte_20r": metrics["maximum_drawdown_r"] <= 20.0,
            "holm_alpha_p_lt_0_05": holm_p_values[candidate_id] < 0.05,
        }
        tier_b = {
            "minimum_sample": sample_ok,
            "mean_net_r_gt_0": metrics["mean_net_r"] > 0,
            "day_cluster_ci_lower_gte_minus_0_05": metrics["day_cluster_ci"][0] >= -0.05,
            "profit_factor_gt_1_00": (metrics["profit_factor"] or 0) > 1.0,
            "base_positive_1_5x_nonnegative": (
                metrics["mean_net_r"] > 0 and metrics["mean_stress_1_5x_net_r"] >= 0
            ),
            "positive_2_of_3_windows": positive_windows >= 2,
            "best_year_lt_60pct": metrics["best_year_share"] < 0.60,
            "max_drawdown_lte_25r": metrics["maximum_drawdown_r"] <= 25.0,
            "benchmark_alpha_mean_gt_0": benchmark_alpha[candidate_id] > 0,
        }
        if all(tier_a.values()):
            tier = "TIER_A"
        elif all(tier_b.values()):
            tier = "TIER_B"
        elif not sample_ok:
            tier = "INSUFFICIENT_SAMPLE_RESEARCH_CANDIDATE"
        else:
            tier = "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST"
        rows.append({
            "candidate_id": candidate_id,
            "sample_eligibility": sample_ok,
            "positive_historical_windows": positive_windows,
            "tier_a_criteria": tier_a,
            "tier_b_criteria": tier_b,
            "final_tier": tier,
            "forward_test_eligibility": tier in {"TIER_A", "TIER_B"},
            "ranking_value_ci_lower": metrics["day_cluster_ci"][0],
            "manual_override": False,
        })
    eligible = sorted(
        (row for row in rows if row["forward_test_eligibility"]),
        key=lambda row: row["ranking_value_ci_lower"],
        reverse=True,
    )
    return {
        "adjudications": rows,
        "primary_candidate": eligible[0]["candidate_id"] if eligible else None,
        "secondary_candidate": eligible[1]["candidate_id"] if len(eligible) > 1 else None,
        "status": "PASS",
    }
