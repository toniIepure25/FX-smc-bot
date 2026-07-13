"""Tests for placebo/baseline generators and ablation matrix."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.research.placebos import (
    AblationSpec,
    CANONICAL_ABLATIONS,
    generate_ablation_matrix,
    random_direction_matched,
    random_time_matched,
    signal_inversion,
    simple_momentum_baseline,
)


def _make_data(n: int = 200, seed: int = 42):
    rng = np.random.default_rng(seed)
    close = np.cumsum(rng.normal(0, 0.001, n)) + 1.1
    timestamps = np.array([
        np.datetime64("2024-01-02T00:00") + np.timedelta64(i * 5, "m")
        for i in range(n)
    ])
    return close, timestamps


class TestRandomDirectionMatched:

    def test_produces_trades(self):
        close, ts = _make_data()
        signal_bars = [20, 50, 80, 110]
        trades = random_direction_matched(ts, signal_bars, close, holding_bars=10)
        assert len(trades) == 4

    def test_directions_randomized(self):
        close, ts = _make_data()
        signal_bars = list(range(10, 150, 10))
        trades = random_direction_matched(ts, signal_bars, close)
        directions = {t.direction for t in trades}
        assert len(directions) == 2  # both directions should appear

    def test_entry_after_signal(self):
        close, ts = _make_data()
        signal_bars = [30]
        trades = random_direction_matched(ts, signal_bars, close, holding_bars=5)
        assert trades[0].entry_bar == 31  # entry on bar after signal


class TestRandomTimeMatched:

    def test_produces_trades(self):
        close, ts = _make_data()
        trades = random_time_matched(close, ts, n_trades=10, holding_bars=10)
        assert len(trades) == 10

    def test_session_mask(self):
        close, ts = _make_data()
        mask = np.zeros(len(close), dtype=bool)
        mask[50:100] = True
        trades = random_time_matched(close, ts, n_trades=5, holding_bars=10, session_mask=mask)
        for t in trades:
            assert 50 <= t.entry_bar - 1 < 100


class TestSignalInversion:

    def test_inverts_direction(self):
        close, ts = _make_data()
        signal_bars = [20, 50]
        signal_dirs = ["long", "short"]
        trades = signal_inversion(signal_bars, signal_dirs, close, ts, holding_bars=10)
        assert trades[0].direction == "short"
        assert trades[1].direction == "long"

    def test_monotonic_worsening_under_costs(self):
        """Inverted strategy should be the mirror of the original."""
        close, ts = _make_data()
        signal_bars = [20, 50, 80]
        orig_dirs = ["long", "long", "long"]

        orig_trades = signal_inversion(signal_bars, ["short"] * 3, close, ts, holding_bars=10)
        inv_trades = signal_inversion(signal_bars, orig_dirs, close, ts, holding_bars=10)

        for o, i in zip(orig_trades, inv_trades):
            assert abs(o.pnl + i.pnl) < 1e-10


class TestMomentumBaseline:

    def test_produces_trades(self):
        close, ts = _make_data()
        trades = simple_momentum_baseline(close, ts, lookback=20, holding_bars=10)
        assert len(trades) > 0


class TestAblationMatrix:

    def test_canonical_ablations_exist(self):
        assert len(CANONICAL_ABLATIONS) >= 10

    def test_matrix_size(self):
        matrix = generate_ablation_matrix(
            "sweep_reversal",
            pairs=["EURUSD", "GBPUSD"],
            sessions=["london", "new_york"],
        )
        expected = len(CANONICAL_ABLATIONS) * 2 * 2
        assert len(matrix) == expected

    def test_custom_ablations(self):
        custom = [AblationSpec("custom_test", "Test", {"x": 1})]
        matrix = generate_ablation_matrix(
            "sweep_reversal",
            pairs=["EURUSD"],
            sessions=["london"],
            custom_ablations=custom,
        )
        assert len(matrix) == len(CANONICAL_ABLATIONS) + 1
        assert any(m["ablation"] == "custom_test" for m in matrix)
