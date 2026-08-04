"""Synthetic-only A0R2 discovery engine certification tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fx_smc_bot.research.a0r2_adjudication import (
    TrialResult,
    adjudicate_shortlist,
    transition_trial_status,
)
from fx_smc_bot.research.a0r2_execution import ExecutionCosts, execute_side_correct
from fx_smc_bot.research.a0r2_features import (
    filtered_regime_states,
    strictly_lagged_cross_pair_features,
    train_only_standardize,
)
from fx_smc_bot.research.a0r2_folds import purged_expanding_folds
from fx_smc_bot.research.a0r2_models import fit_train_only_linear_scores
from fx_smc_bot.research.a0r2_signals import threshold_signal
from fx_smc_bot.research.a0r2_statistics import (
    benjamini_hochberg_fdr,
    deflated_sharpe_ratio,
    holm_adjust,
    probability_of_backtest_overfitting,
)


def test_purged_expanding_folds_include_embargo() -> None:
    folds = purged_expanding_folds(30, min_train_size=10, test_size=5, embargo=2)
    assert folds[0].train_indices.max() == 9
    assert folds[0].test_indices.min() == 12
    assert folds[0].embargo_start_index == 10
    assert folds[0].embargo_end_index == 12


def test_train_only_standardization_ignores_future_perturbation() -> None:
    train = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    test = pd.DataFrame({"x": [4.0, 5.0]})
    _, normalized = train_only_standardize(train, test, ["x"])
    perturbed_test = pd.DataFrame({"x": [4.0, 5000.0]})
    _, perturbed = train_only_standardize(train, perturbed_test, ["x"])
    assert normalized.loc[0, "x"] == perturbed.loc[0, "x"]


def test_strictly_lagged_cross_pair_features_do_not_use_current_bar() -> None:
    frame = pd.DataFrame({"leader": [10.0, 20.0, 30.0], "target": [1.0, 2.0, 3.0]})
    out = strictly_lagged_cross_pair_features(frame, ["leader"], lag=1)
    assert np.isnan(out.loc[0, "leader_lag1"])
    assert out.loc[2, "leader_lag1"] == 20.0


def test_filtered_regime_states_are_past_only() -> None:
    values = pd.Series([1.0, 2.0, 100.0, 3.0])
    states = filtered_regime_states(values, 3)
    perturbed = filtered_regime_states(pd.Series([1.0, 2.0, 10000.0, 3.0]), 3)
    assert states.iloc[1] == perturbed.iloc[1]


def test_synthetic_execution_is_side_correct_and_one_bar_delayed() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.date_range("2010-01-04 14:00", periods=3, freq="min", tz="UTC"),
            "bid_close": [1.00, 1.01, 1.02],
            "ask_close": [1.01, 1.02, 1.03],
        }
    )
    signal = pd.Series([1, 1, 0])
    out = execute_side_correct(bars, signal, costs=ExecutionCosts())
    assert out.loc[0, "position"] == 0
    assert out.loc[1, "position"] == 1
    assert out.loc[1, "entry_price"] == out.loc[1, "ask_close"]


def test_synthetic_positions_flatten_before_rollover() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2010-01-04 21:28:00Z",
                    "2010-01-04 21:29:00Z",
                    "2010-01-04 21:30:00Z",
                ]
            ),
            "bid_close": [1.00, 1.01, 1.02],
            "ask_close": [1.01, 1.02, 1.03],
        }
    )
    out = execute_side_correct(bars, pd.Series([1, 1, 1]), costs=ExecutionCosts())
    assert out.loc[2, "mandatory_rollover_flat"]
    assert out.loc[2, "position"] == 0


def test_signal_abstention_and_train_only_model_are_deterministic() -> None:
    train_x = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    train_y = pd.Series([1.0, 2.0, 3.0])
    test_x = pd.DataFrame({"x": [4.0, 5.0]})
    scores = fit_train_only_linear_scores(train_x, train_y, test_x)
    signal = threshold_signal(scores, entry_threshold=0.5, abstain_below=0.1)
    assert signal.tolist() == [1, 1]


def test_multiple_testing_and_shortlist_interfaces() -> None:
    p_values = [0.01, 0.2, 0.03]
    assert len(holm_adjust(p_values)) == 3
    assert len(benjamini_hochberg_fdr(p_values)) == 3
    assert 0.0 <= deflated_sharpe_ratio(1.0, trial_count=1200) <= 1.0
    assert probability_of_backtest_overfitting(0.8, 0.2) == 0.6000000000000001
    status = transition_trial_status("REGISTERED", "COMPLETED")
    shortlist = adjudicate_shortlist(
        [TrialResult("A0R1-01-0001", status, net_score=1.0, adjusted_p_value=0.01)],
        alpha=0.05,
    )
    assert shortlist == ["A0R1-01-0001"]
