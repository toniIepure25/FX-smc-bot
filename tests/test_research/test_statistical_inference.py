"""Tests for statistical inference module."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.research.statistical_inference import (
    block_bootstrap,
    build_inference_report,
    deflated_sharpe_ratio,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    sortino_ratio,
    stationary_bootstrap,
    var_cvar,
)


class TestSharpe:

    def test_positive_returns(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_returns(self):
        returns = np.zeros(100)
        assert sharpe_ratio(returns) == 0.0

    def test_empty(self):
        assert sharpe_ratio(np.array([])) == 0.0


class TestSortino:

    def test_positive_returns_high(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.002, 0.01, 252)
        sort_r = sortino_ratio(returns)
        assert sort_r > 0

    def test_all_positive(self):
        returns = np.full(100, 0.001)
        sort_r = sortino_ratio(returns)
        assert sort_r == float("inf")


class TestPSR:

    def test_high_sr_high_psr(self):
        psr = probabilistic_sharpe_ratio(2.0, 0.0, 252)
        assert psr > 0.95

    def test_zero_sr_near_half(self):
        psr = probabilistic_sharpe_ratio(0.0, 0.0, 252)
        assert abs(psr - 0.5) < 0.01

    def test_small_sample_cautious(self):
        psr = probabilistic_sharpe_ratio(0.5, 0.0, 10)
        assert psr < 0.95


class TestDSR:

    def test_more_trials_lower_dsr(self):
        dsr_1 = deflated_sharpe_ratio(1.0, 252, 1)
        dsr_100 = deflated_sharpe_ratio(1.0, 252, 100)
        assert dsr_100 < dsr_1

    def test_single_trial_matches_psr(self):
        dsr = deflated_sharpe_ratio(1.0, 252, 1)
        psr = probabilistic_sharpe_ratio(1.0, 0.0, 252)
        assert abs(dsr - psr) < 0.1


class TestMTRL:

    def test_high_sr_low_mtrl(self):
        mtrl = minimum_track_record_length(2.0, 0.0)
        assert 1 < mtrl < 50

    def test_low_sr_high_mtrl(self):
        mtrl = minimum_track_record_length(0.1, 0.0)
        assert mtrl > 100


class TestVaRCVaR:

    def test_basic(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, 1000)
        var, cvar = var_cvar(returns, alpha=0.05)
        assert var < 0
        assert cvar <= var

    def test_empty(self):
        var, cvar = var_cvar(np.array([]))
        assert var == 0.0


class TestStationaryBootstrap:

    def test_ci_contains_point_estimate(self):
        rng = np.random.default_rng(42)
        data = rng.normal(0.001, 0.01, 200)
        ci = stationary_bootstrap(data, np.mean, n_bootstrap=1000)
        assert ci.lower <= ci.point_estimate <= ci.upper

    def test_wider_ci_with_higher_confidence(self):
        rng = np.random.default_rng(42)
        data = rng.normal(0.001, 0.01, 200)
        ci_90 = stationary_bootstrap(data, np.mean, confidence=0.90, n_bootstrap=1000)
        ci_99 = stationary_bootstrap(data, np.mean, confidence=0.99, n_bootstrap=1000)
        assert (ci_99.upper - ci_99.lower) >= (ci_90.upper - ci_90.lower) * 0.9


class TestBlockBootstrap:

    def test_basic(self):
        rng = np.random.default_rng(42)
        data = rng.normal(0.001, 0.01, 200)
        ci = block_bootstrap(data, np.mean, block_size=5, n_bootstrap=1000)
        assert ci.lower <= ci.point_estimate <= ci.upper


class TestInferenceReport:

    def test_positive_returns_report(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        report = build_inference_report(returns, n_bootstrap=500)

        assert report.n_observations == 252
        assert report.sharpe > 0
        assert report.psr > 0.5
        assert report.sharpe_ci is not None
        assert report.profit_factor_ci is not None
        assert report.win_rate_ci is not None

    def test_insufficient_data(self):
        report = build_inference_report(np.array([0.01, 0.02]))
        assert report.n_observations == 2
        assert report.sharpe == 0.0
