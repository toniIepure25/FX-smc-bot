"""Tests for prop-account Monte Carlo simulation."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.research.prop_simulation import (
    PropAccountProfile,
    PropSimulationResult,
    simulate_prop_challenge,
)


class TestPropAccountProfile:

    def test_default_profile(self):
        p = PropAccountProfile()
        assert p.starting_balance == 100_000
        assert p.daily_max_loss == 0.05
        assert p.total_max_loss == 0.10

    def test_custom_profile(self):
        p = PropAccountProfile(
            name="Custom", starting_balance=50_000,
            phase1_profit_target=0.10,
            daily_max_loss=0.04,
            total_max_loss=0.08,
        )
        assert p.name == "Custom"
        assert p.phase1_profit_target == 0.10


class TestSimulatePropChallenge:

    def test_strongly_positive_strategy(self):
        """A strategy with consistent gains should have high pass rate."""
        daily_pnls = np.full(60, 0.003)  # +0.3% daily
        profile = PropAccountProfile()
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=100, seed=42,
        )
        assert result.n_paths == 100
        assert result.phase1_pass_rate > 0.5
        assert result.daily_breach_rate == 0.0

    def test_losing_strategy(self):
        """A consistently losing strategy should breach limits."""
        daily_pnls = np.full(60, -0.01)  # -1% daily
        profile = PropAccountProfile()
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=100, seed=42,
        )
        assert result.total_breach_rate > 0.5

    def test_volatile_strategy(self):
        """A strategy with high volatility should have mixed results."""
        rng = np.random.default_rng(42)
        daily_pnls = rng.normal(0.001, 0.02, 100)
        profile = PropAccountProfile()
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=200, seed=42,
        )
        assert 0 < result.phase1_pass_rate < 1
        assert result.mean_max_drawdown > 0

    def test_daily_breach_detection(self):
        """A strategy with extreme single-day loss should trigger daily breach."""
        daily_pnls = np.array([0.01, 0.01, -0.06, 0.01, 0.01] * 10)
        profile = PropAccountProfile(daily_max_loss=0.05)
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=50, seed=42,
        )
        assert result.daily_breach_rate > 0

    def test_consistency_rule(self):
        """With consistency rule, one huge day shouldn't count."""
        daily_pnls = np.array([0.001] * 30 + [0.08] + [0.001] * 29)
        profile = PropAccountProfile(
            consistency_rule=True,
            best_day_max_pct=0.30,
        )
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=50, seed=42,
        )
        assert result.payout_rate < 1.0

    def test_risk_grid(self):
        """Running simulation at different risk levels."""
        rng = np.random.default_rng(42)
        base_pnls = rng.normal(0.002, 0.008, 100)
        profile = PropAccountProfile()

        results = {}
        for risk_pct in [0.001, 0.003, 0.005]:
            scaled = base_pnls * (risk_pct / 0.005)
            res = simulate_prop_challenge(
                scaled, profile, n_paths=100,
                risk_per_trade=risk_pct, seed=42,
            )
            results[risk_pct] = res

        assert results[0.001].total_breach_rate <= results[0.005].total_breach_rate

    def test_insufficient_data(self):
        result = simulate_prop_challenge(
            np.array([0.01, 0.02]),
            PropAccountProfile(),
            n_paths=10,
        )
        assert result.n_paths == 0

    def test_result_statistics(self):
        rng = np.random.default_rng(42)
        daily_pnls = rng.normal(0.001, 0.01, 100)
        profile = PropAccountProfile()
        result = simulate_prop_challenge(
            daily_pnls, profile, n_paths=200, seed=42,
        )
        assert result.p10_max_drawdown <= result.mean_max_drawdown
        assert result.mean_max_drawdown <= result.p90_max_drawdown
        assert len(result.outcomes) == 200
