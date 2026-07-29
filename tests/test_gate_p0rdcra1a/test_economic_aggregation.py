from __future__ import annotations

import numpy as np
import pandas as pd

from fx_smc_bot.research.strategy_alpha_aggregation import (
    adjudicate_frozen_tiers,
    cluster_bootstrap_mean_ci,
    paired_cluster_signflip_p,
    performance_metrics,
)


def _trades(values: list[float]) -> pd.DataFrame:
    count = len(values)
    return pd.DataFrame({
        "candidate_id": ["candidate"] * count,
        "position_id": [f"p{idx}" for idx in range(count)],
        "instrument": ["EURUSD"] * count,
        "entry_time": pd.date_range("2019-01-01", periods=count, freq="D"),
        "net_r": values,
        "gross_r": [value + 0.02 for value in values],
        "stress_1_5x_net_r": [value - 0.01 for value in values],
        "stress_2_0x_net_r": [value - 0.02 for value in values],
    })


def test_cluster_bootstrap_is_deterministic_and_preserves_cluster_sampling() -> None:
    values = np.asarray([1.0, 1.0, -1.0])
    clusters = np.asarray(["a", "a", "b"])
    first = cluster_bootstrap_mean_ci(values, clusters, seed=1729, iterations=500)
    second = cluster_bootstrap_mean_ci(values, clusters, seed=1729, iterations=500)
    assert first == second
    assert first[0] <= float(np.mean(values)) <= first[1]


def test_paired_cluster_test_distinguishes_consistent_positive_alpha() -> None:
    differences = np.full(40, 0.2)
    clusters = np.asarray([f"d{idx // 2}" for idx in range(40)])
    assert paired_cluster_signflip_p(
        differences, clusters, seed=1729, iterations=1_000,
    ) < 0.05


def test_performance_metrics_cover_frozen_outputs() -> None:
    metrics = performance_metrics(_trades([0.5, -0.2, 0.4, -0.1] * 30))
    assert metrics["trade_count"] == 120
    assert metrics["mean_net_r"] > 0
    assert metrics["profit_factor"] > 1
    assert len(metrics["day_cluster_ci"]) == 2
    assert metrics["risk_0_50_pct_max_drawdown"] >= 0


def test_tier_adjudication_is_mechanical_and_ranks_ci_lower_bound() -> None:
    base = {
        "trade_count": 200,
        "years_with_20_or_more_trades": 4,
        "mean_net_r": 0.2,
        "day_cluster_ci": (0.05, 0.3),
        "profit_factor": 1.2,
        "mean_stress_1_5x_net_r": 0.1,
        "leave_one_year_out_positive": True,
        "best_5_trade_share": 0.2,
        "best_year_share": 0.3,
        "maximum_drawdown_r": 10.0,
    }
    combined = {"A": dict(base), "B": {**base, "day_cluster_ci": (0.08, 0.3)}}
    windows = {
        candidate: {
            "engineering": {"mean_net_r": 0.1},
            "historical_replay": {"mean_net_r": 0.1},
            "historical_stress": {"mean_net_r": 0.1},
        }
        for candidate in combined
    }
    result = adjudicate_frozen_tiers(
        combined,
        windows,
        {"A": 0.01, "B": 0.01},
        {"A": 0.1, "B": 0.1},
    )
    assert all(row["final_tier"] == "TIER_A" for row in result["adjudications"])
    assert result["primary_candidate"] == "B"
    assert result["secondary_candidate"] == "A"
