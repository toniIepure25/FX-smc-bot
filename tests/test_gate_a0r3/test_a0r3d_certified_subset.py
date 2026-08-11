from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fx_smc_bot.research.a0r3d_certified_subset import (
    HoldoutReadGuard,
    Paths,
    certify_trial,
    compact_execution_window,
    simulate_state_machine,
    stationary_bootstrap_indices,
)


def _frame(times: list[str]) -> pd.DataFrame:
    rows = []
    for i, text in enumerate(times):
        mid = 1.1000 + i * 0.0010
        rows.append(
            {
                "timestamp": pd.Timestamp(text, tz="UTC"),
                "bid_open": mid - 0.0001,
                "bid_high": mid + 0.0004,
                "bid_low": mid - 0.0004,
                "bid_close": mid - 0.0001,
                "ask_open": mid + 0.0001,
                "ask_high": mid + 0.0004,
                "ask_low": mid - 0.0004,
                "ask_close": mid + 0.0001,
            }
        )
    return pd.DataFrame(rows)


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "holding_horizon": 1,
        "exit_rule": "time_exit",
        "stop_rule": "none",
        "target_bps": 0.0,
        "stop_bps": 0.0,
    }
    config.update(overrides)
    return config


def test_long_uses_ask_entry_bid_exit_after_one_completed_m1_latency() -> None:
    frame = _frame(["2017-01-03T14:00:00", "2017-01-03T14:01:00", "2017-01-03T14:02:00"])
    signal = pd.Series([1, 0, 0])

    daily, trades = simulate_state_machine(frame, signal, _config(), cost_multiplier=1.0)

    assert len(trades) == 1
    expected_gross = (frame.loc[2, "bid_open"] - frame.loc[1, "ask_open"]) / frame.loc[
        1, "ask_open"
    ] * 10_000.0
    assert trades[0]["side"] == "long"
    assert trades[0]["exit_reason"] == "horizon"
    assert trades[0]["gross_bps"] == pytest.approx(expected_gross)
    assert daily["net_bps"].sum() < daily["gross_bps"].sum()


def test_short_uses_bid_entry_ask_exit() -> None:
    frame = _frame(["2017-01-03T14:00:00", "2017-01-03T14:01:00", "2017-01-03T14:02:00"])
    signal = pd.Series([-1, 0, 0])

    _, trades = simulate_state_machine(frame, signal, _config(), cost_multiplier=1.0)

    expected_gross = (frame.loc[1, "bid_open"] - frame.loc[2, "ask_open"]) / frame.loc[
        1, "bid_open"
    ] * 10_000.0
    assert trades[0]["side"] == "short"
    assert trades[0]["gross_bps"] == pytest.approx(expected_gross)


def test_opposite_signal_flip_exits_and_reenters_on_next_bar() -> None:
    frame = _frame(
        [
            "2017-01-03T14:00:00",
            "2017-01-03T14:01:00",
            "2017-01-03T14:02:00",
            "2017-01-03T14:03:00",
        ]
    )
    signal = pd.Series([1, -1, 0, 0])

    _, trades = simulate_state_machine(
        frame, signal, _config(exit_rule="opposite_signal", holding_horizon=99), cost_multiplier=1.0
    )

    assert trades[0]["exit_reason"] == "opposite_signal"
    assert trades[1]["side"] == "short"


def test_rollover_mandatory_flat_closes_position_and_blocks_new_entries() -> None:
    frame = _frame(["2017-01-03T21:28:00", "2017-01-03T21:29:00", "2017-01-03T21:45:00"])
    signal = pd.Series([1, 1, 1])

    _, trades = simulate_state_machine(
        frame, signal, _config(holding_horizon=99), cost_multiplier=1.0
    )

    assert trades[0]["exit_reason"] == "mandatory_flat"
    assert len(trades) == 1


def test_same_bar_stop_and_target_uses_adverse_first() -> None:
    frame = _frame(["2017-01-03T14:00:00", "2017-01-03T14:01:00", "2017-01-03T14:02:00"])
    frame.loc[2, "bid_high"] = frame.loc[1, "ask_open"] * 1.002
    frame.loc[2, "bid_low"] = frame.loc[1, "ask_open"] * 0.998
    signal = pd.Series([1, 0, 0])

    _, trades = simulate_state_machine(
        frame,
        signal,
        _config(stop_rule="one_atr_adverse", target_bps=5.0, stop_bps=5.0),
        cost_multiplier=1.0,
    )

    assert trades[0]["exit_reason"] == "same_bar_adverse_stop"


def test_cost_stress_increases_cost_without_changing_gross() -> None:
    frame = _frame(["2017-01-03T14:00:00", "2017-01-03T14:01:00", "2017-01-03T14:02:00"])
    signal = pd.Series([1, 0, 0])

    _, base = simulate_state_machine(frame, signal, _config(), cost_multiplier=1.0)
    _, stress = simulate_state_machine(frame, signal, _config(), cost_multiplier=2.0)

    assert stress[0]["gross_bps"] == base[0]["gross_bps"]
    assert stress[0]["cost_bps"] > base[0]["cost_bps"]
    assert stress[0]["net_bps"] < base[0]["net_bps"]


def test_delayed_valid_exit_at_dataset_end_is_recorded() -> None:
    frame = _frame(["2017-01-03T14:00:00", "2017-01-03T14:01:00"])
    signal = pd.Series([1, 0])

    _, trades = simulate_state_machine(
        frame, signal, _config(holding_horizon=10), cost_multiplier=1.0
    )

    assert trades[0]["exit_reason"] == "delayed_valid_exit_at_dataset_end"


def test_holdout_guard_rejects_2018_plus_before_opening_file(tmp_path: Path) -> None:
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path,
        results=tmp_path,
        docs=tmp_path,
        trials=tmp_path / "trials.jsonl",
        eligibility=tmp_path / "eligibility.json",
        pass_freeze=tmp_path / "freeze.json",
        a0_execution=tmp_path / "a0.json",
        a0r1_execution=tmp_path / "a0r1.json",
    )

    with pytest.raises(ValueError, match="2018_PLUS"):
        HoldoutReadGuard().read_side(paths, "EURUSD", "bid", 2018, 1)


def test_stationary_bootstrap_is_deterministic() -> None:
    first = stationary_bootstrap_indices(20, block_length=5, iterations=4, seed=123)
    second = stationary_bootstrap_indices(20, block_length=5, iterations=4, seed=123)

    assert (first == second).all()


def test_compact_execution_window_zeroes_gap_boundary_signal() -> None:
    frame = _frame(
        [
            "2017-01-03T14:00:00",
            "2017-01-03T14:01:00",
            "2017-01-03T14:02:00",
            "2017-01-03T15:00:00",
            "2017-01-03T15:01:00",
            "2017-01-03T15:02:00",
        ]
    )
    signal = pd.Series([1, 0, 1, 0, 1, 0])

    compact, compact_signal = compact_execution_window(frame, signal, horizon=1)

    assert len(compact) == 6
    assert compact_signal.iloc[2] == 1
    assert compact_signal.iloc[-1] == 0


def test_compact_execution_window_prevents_false_entry_after_gap() -> None:
    frame = _frame(
        [
            "2017-01-03T14:00:00",
            "2017-01-03T14:01:00",
            "2017-01-03T14:02:00",
            "2017-01-03T15:00:00",
            "2017-01-03T15:01:00",
            "2017-01-03T15:02:00",
        ]
    )
    signal = pd.Series([1, 0, 0, 0, 1, 0])

    compact, compact_signal = compact_execution_window(frame, signal, horizon=1)

    assert len(compact) == 5
    assert compact_signal.iloc[2] == 0


def test_certification_blocks_atr_stop_and_certifies_simple_f01() -> None:
    base = {
        "trial_id": "T1",
        "family_id": "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
        "configuration_sha256": "abc",
        "full_configuration": {
            "execution_contract": {
                "entry_latency": "one_completed_M1_bar",
                "long_entry": "ask",
                "long_exit": "bid",
                "mandatory_flat": "16:45 America/New_York",
                "new_entries_resume": "17:30 America/New_York",
                "rollover_exclusion": "16:30 America/New_York",
                "same_bar_ambiguity": "adverse_first",
                "short_entry": "bid",
                "short_exit": "ask",
            },
            "cost_contract": {
                "commission": "frozen_A0_base",
                "slippage": "frozen_A0_base",
                "spread": "side_correct_bid_ask",
                "stress_1": "frozen_A0_stress_1",
                "stress_2": "frozen_A0_stress_2",
            },
            "model_class": "none",
            "model_hyperparameters": {},
            "frozen_categories": {
                "lookbacks": 15,
                "holding_periods": 15,
                "variants": "continuation",
                "anchors": "London open",
            },
            "lookback": 15,
            "entry_threshold": 0.3,
            "variant": "continuation",
            "session_anchor": "London open",
            "holding_horizon": 15,
            "exit_rule": "time_exit",
            "stop_rule": "none",
            "target_horizon": 5,
            "abstention_threshold": None,
            "cross_pair_edge": None,
            "neutrality_constraint": None,
            "regime_component_count": None,
            "regime_model": None,
            "spread_forecaster": None,
            "triangle": None,
            "training_window": "expanding",
            "normalization_rule": "train_only_expanding_or_rolling_as_configured",
            "purging_rule": "drop_overlapping_label_windows",
            "embargo": "frozen_A0_embargo",
            "walk_forward_folds": "purged_expanding_2011_2014",
            "random_seed": 1,
            "position_sizing": "fixed_fraction_vol_scaled_10bp_risk_cap",
        },
    }

    status, blockers, _ = certify_trial(base)
    assert status == "CERTIFIED_EXECUTABLE"
    assert blockers == []

    blocked = {
        **base,
        "full_configuration": {**base["full_configuration"], "stop_rule": "one_atr_adverse"},
    }
    status, blockers, _ = certify_trial(blocked)
    assert status == "IMPLEMENTATION_BLOCKED"
    assert any("ATR stop" in blocker for blocker in blockers)
