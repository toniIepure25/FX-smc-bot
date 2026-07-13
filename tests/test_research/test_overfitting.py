"""Tests for multiple-testing correction and overfitting controls."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.research.overfitting import (
    benjamini_hochberg,
    cscv_pbo,
    holm_bonferroni,
    whites_reality_check,
)


class TestHolmBonferroni:

    def test_single_significant(self):
        result = holm_bonferroni([0.01], alpha=0.05)
        assert result.rejected[0]

    def test_single_not_significant(self):
        result = holm_bonferroni([0.10], alpha=0.05)
        assert not result.rejected[0]

    def test_multiple_correction(self):
        p_values = [0.01, 0.04, 0.03]
        result = holm_bonferroni(p_values, alpha=0.05)
        assert result.corrected[0] <= result.corrected[1]
        assert all(c <= 1.0 for c in result.corrected)

    def test_empty(self):
        result = holm_bonferroni([])
        assert result.corrected == []

    def test_more_conservative_than_raw(self):
        p_values = [0.01, 0.04, 0.03, 0.02]
        result = holm_bonferroni(p_values, alpha=0.05)
        for orig, corr in zip(p_values, result.corrected):
            assert corr >= orig


class TestBenjaminiHochberg:

    def test_single_significant(self):
        result = benjamini_hochberg([0.01], alpha=0.05)
        assert result.rejected[0]

    def test_controls_fdr(self):
        p_values = [0.001, 0.02, 0.03, 0.20, 0.50]
        result = benjamini_hochberg(p_values, alpha=0.05)
        assert result.rejected[0]  # most significant
        assert not result.rejected[4]  # least significant

    def test_less_conservative_than_holm(self):
        rng = np.random.default_rng(42)
        p_values = sorted(rng.uniform(0, 0.1, 10).tolist())
        holm = holm_bonferroni(p_values, alpha=0.05)
        bh = benjamini_hochberg(p_values, alpha=0.05)
        assert sum(bh.rejected) >= sum(holm.rejected)


class TestWhitesRealityCheck:

    def test_null_strategies(self):
        """Under the null (no alpha), p-value should be high."""
        rng = np.random.default_rng(42)
        benchmark = rng.normal(0, 0.01, 200)
        strategies = [rng.normal(0, 0.01, 200) for _ in range(5)]
        p = whites_reality_check(benchmark, strategies, n_bootstrap=500)
        assert p > 0.05

    def test_strong_strategy(self):
        """A strategy with clear alpha should have low p-value."""
        rng = np.random.default_rng(42)
        benchmark = rng.normal(0, 0.01, 200)
        strong = benchmark + 0.005  # clear alpha
        strategies = [
            rng.normal(0, 0.01, 200),
            strong,
            rng.normal(0, 0.01, 200),
        ]
        p = whites_reality_check(benchmark, strategies, n_bootstrap=500)
        assert p < 0.05


class TestCSCVPBO:

    def test_random_strategies_high_pbo(self):
        """Random strategies should show high PBO (likely overfitted)."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (200, 20))
        pbo = cscv_pbo(returns, n_splits=8)
        assert 0 <= pbo <= 1

    def test_insufficient_data(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (10, 3))
        pbo = cscv_pbo(returns, n_splits=8)
        assert pbo == 0.5  # default for insufficient data
