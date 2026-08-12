"""Golden execution tests for the unified V2 kernel (certified A0R3D engine)."""

from __future__ import annotations

import pandas as pd  # type: ignore[import-untyped]
import pytest

from fx_smc_bot.research.v2.kernel import simulate
from tests.test_gate_a0r4.conftest import BASE_TS, build_frame

CFG_TIME_EXIT = {"holding_horizon": 1, "exit_rule": "time_exit", "stop_rule": "none",
                 "stop_bps": 0.0, "target_bps": 0.0}


def _signal(values: list[int], index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index, dtype=int)


def test_long_entry_uses_ask_exit_uses_bid_with_one_bar_latency() -> None:
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1002},
        {"bid_open": 1.1000, "bid_high": 1.1000, "bid_low": 1.1000, "bid_close": 1.1000,
         "ask_open": 1.1002, "ask_high": 1.1002, "ask_low": 1.1002, "ask_close": 1.1002},
        {"bid_open": 1.1010, "bid_high": 1.1010, "bid_low": 1.1010, "bid_close": 1.1010,
         "ask_open": 1.1012, "ask_high": 1.1012, "ask_low": 1.1012, "ask_close": 1.1012},
    ])
    signal = _signal([1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["side"] == "long"
    # entry at bar1 ask_open (one-bar latency), exit at bar2 bid_open
    expected_gross = (1.1010 - 1.1002) / 1.1002 * 10_000.0
    assert trade["gross_bps"] == pytest.approx(expected_gross, abs=1e-6)
    # entry timestamp is bar index 1, not the signal bar 0 (no same-bar fill)
    assert trade["entry_timestamp"] == (BASE_TS + pd.Timedelta(minutes=1)).isoformat()


def test_short_entry_uses_bid_exit_uses_ask() -> None:
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1002},
        {"bid": 1.1000, "ask": 1.1002},
        {"bid": 1.0990, "ask": 1.0992},
    ])
    signal = _signal([-1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    assert len(trades) == 1 and trades[0]["side"] == "short"
    # short entry at bar1 bid_open=1.1000, exit at bar2 ask_open=1.0992
    expected_gross = (1.1000 - 1.0992) / 1.1000 * 10_000.0
    assert trades[0]["gross_bps"] == pytest.approx(expected_gross, abs=1e-6)


def test_jpy_scaling_is_relative_and_positive() -> None:
    frame = build_frame([
        {"bid": 110.00, "ask": 110.02},
        {"bid": 110.00, "ask": 110.02},
        {"bid": 110.20, "ask": 110.22},
    ])
    signal = _signal([1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    expected_gross = (110.20 - 110.02) / 110.02 * 10_000.0
    assert trades[0]["gross_bps"] == pytest.approx(expected_gross, abs=1e-6)


def test_same_bar_stop_and_target_resolves_adverse_first() -> None:
    cfg = {"holding_horizon": 10, "exit_rule": "time_exit", "stop_rule": "fixed_bps",
           "stop_bps": 20.0, "target_bps": 20.0}
    # long entered at bar1 ask_open=1.1002; bar2 spans both target (>=1.10240) and
    # stop (<=1.09800), so both are hit on the same bar.
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1002},
        {"bid": 1.1000, "ask": 1.1002},
        {"bid_open": 1.1005, "bid_high": 1.1030, "bid_low": 1.0970, "bid_close": 1.1005,
         "ask_open": 1.1007, "ask_high": 1.1032, "ask_low": 1.0972, "ask_close": 1.1007},
    ])
    signal = _signal([1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, cfg, cost_multiplier=1.0)
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "same_bar_adverse_stop"
    # adverse-first: exit at the stop price (long stop uses bid_low)
    expected_gross = (1.0970 - 1.1002) / 1.1002 * 10_000.0
    assert trades[0]["gross_bps"] == pytest.approx(expected_gross, abs=1e-6)


def test_mandatory_flat_forces_exit_in_flat_window() -> None:
    # Entry at NY 16:25 (before the 16:30 no-entry window); exit forced at NY 16:50
    # (20:50 UTC EDT), inside the 16:45-17:30 mandatory-flat window.
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1002, "timestamp": pd.Timestamp("2016-06-15 20:20", tz="UTC")},
        {"bid": 1.1000, "ask": 1.1002, "timestamp": pd.Timestamp("2016-06-15 20:25", tz="UTC")},
        {"bid": 1.1010, "ask": 1.1012, "timestamp": pd.Timestamp("2016-06-15 20:50", tz="UTC")},
    ])
    signal = _signal([1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    assert len(trades) == 1 and trades[0]["exit_reason"] == "mandatory_flat"


def test_no_entry_during_rollover_window() -> None:
    # NY 16:35 (20:35 UTC EDT) is inside the 16:30-17:30 no-entry window.
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1002, "timestamp": pd.Timestamp("2016-06-15 20:34", tz="UTC")},
        {"bid": 1.1000, "ask": 1.1002, "timestamp": pd.Timestamp("2016-06-15 20:35", tz="UTC")},
        {"bid": 1.1010, "ask": 1.1012, "timestamp": pd.Timestamp("2016-06-15 20:36", tz="UTC")},
    ])
    signal = _signal([1, 0, 0], frame.index)
    _daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    assert trades == []


def test_zero_signal_creates_no_synthetic_fill() -> None:
    frame = build_frame([{"bid": 1.10, "ask": 1.1002}] * 5)
    signal = _signal([0, 0, 0, 0, 0], frame.index)
    daily, trades = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=1.0)
    assert trades == []
    assert float(daily["net_bps"].sum()) == 0.0


def test_cost_stress_monotonically_reduces_net() -> None:
    frame = build_frame([
        {"bid": 1.1000, "ask": 1.1004},
        {"bid": 1.1000, "ask": 1.1004},
        {"bid": 1.1010, "ask": 1.1014},
    ])
    signal = _signal([1, 0, 0], frame.index)
    nets = []
    for mult in (1.0, 1.5, 2.0):
        daily, _ = simulate(frame, signal, CFG_TIME_EXIT, cost_multiplier=mult)
        nets.append(float(daily["net_bps"].sum()))
    assert nets[0] > nets[1] > nets[2]
