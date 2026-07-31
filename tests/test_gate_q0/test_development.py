import pandas as pd

from fx_smc_bot.research.quant_polarity_development import (
    CANDIDATE_IDS,
    TRADE_COLUMNS,
    _candidate_trade_frames,
    adjudicate_development,
)


def _passing_metrics() -> dict:
    return {
        "trade_count": 200,
        "mean_net_r": 0.1,
        "profit_factor": 1.2,
        "mean_stress_1_5x_net_r": 0.05,
        "day_cluster_ci": [0.01, 0.2],
        "yearly_mean_net_r": {str(year): 0.1 for year in range(2015, 2020)},
        "maximum_drawdown_r": 5.0,
    }


def test_shortlist_is_mechanical_and_capped_at_two() -> None:
    results = {
        "candidate_results": {candidate_id: _passing_metrics() for candidate_id in CANDIDATE_IDS},
        "benchmark_results": {
            candidate_id: {"matched_random_alpha": 0.05} for candidate_id in CANDIDATE_IDS
        },
        "overfitting": {"pbo": 0.2},
    }
    adjudication = adjudicate_development(results)
    assert adjudication["status"] == "PASS"
    assert len(adjudication["selected_candidates"]) == 2
    assert adjudication["manual_override"] is False


def test_failed_cost_stress_cannot_enter_shortlist() -> None:
    metrics = {candidate_id: _passing_metrics() for candidate_id in CANDIDATE_IDS}
    metrics[CANDIDATE_IDS[0]]["mean_stress_1_5x_net_r"] = -0.01
    results = {
        "candidate_results": metrics,
        "benchmark_results": {
            candidate_id: {"matched_random_alpha": 0.05} for candidate_id in CANDIDATE_IDS
        },
        "overfitting": {"pbo": 0.2},
    }
    adjudication = adjudicate_development(results)
    first = next(
        row for row in adjudication["candidates"] if row["candidate_id"] == CANDIDATE_IDS[0]
    )
    assert first["eligible"] is False
    assert first["checks"]["stress_1_5x_mean_net_r_gte"] is False


def test_empty_candidate_ledgers_preserve_the_frozen_trade_schema() -> None:
    signals = pd.DataFrame(columns=("source_candidate_id",))
    predictions = pd.DataFrame(columns=("signal_id", "action"))
    frames = _candidate_trade_frames(signals, predictions)
    assert set(frames) == set(CANDIDATE_IDS)
    assert all(tuple(frame.columns) == TRADE_COLUMNS for frame in frames.values())
