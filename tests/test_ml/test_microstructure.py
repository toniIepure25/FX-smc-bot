"""Tests for OHLC-derived microstructure proxy computation."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.ml.microstructure import (
    bar_efficiency,
    compute_all_proxies,
    directional_persistence,
    relative_spread_stress,
    volatility_compression,
    wick_asymmetry,
)


@pytest.fixture
def sample_ohlc() -> tuple:
    n = 100
    np.random.seed(42)
    close = np.cumsum(np.random.randn(n) * 0.001) + 1.1
    open_ = close + np.random.randn(n) * 0.0003
    high = np.maximum(open_, close) + np.abs(np.random.randn(n) * 0.0005)
    low = np.minimum(open_, close) - np.abs(np.random.randn(n) * 0.0005)
    return open_, high, low, close


class TestBarEfficiency:
    def test_output_range(self, sample_ohlc: tuple) -> None:
        open_, high, low, close = sample_ohlc
        eff = bar_efficiency(open_, high, low, close)
        assert eff.shape == close.shape
        assert np.all(eff >= 0.0)
        assert np.all(eff <= 1.0)

    def test_trend_bar_high_efficiency(self) -> None:
        open_ = np.array([1.0])
        high = np.array([1.01])
        low = np.array([1.0])
        close = np.array([1.01])
        eff = bar_efficiency(open_, high, low, close)
        assert eff[0] == pytest.approx(1.0)


class TestWickAsymmetry:
    def test_output_range(self, sample_ohlc: tuple) -> None:
        open_, high, low, close = sample_ohlc
        asym = wick_asymmetry(open_, high, low, close)
        assert np.all(asym >= -1.0)
        assert np.all(asym <= 1.0)


class TestSpreadStress:
    def test_synthetic_spread(self, sample_ohlc: tuple) -> None:
        _, high, low, close = sample_ohlc
        stress = relative_spread_stress(high, low, close)
        assert stress.shape == close.shape
        assert np.all(stress >= 0.0)


class TestVolatilityCompression:
    def test_output_shape(self, sample_ohlc: tuple) -> None:
        _, high, low, _ = sample_ohlc
        comp = volatility_compression(high, low)
        assert comp.shape == high.shape


class TestDirectionalPersistence:
    def test_trending_market_high_persistence(self) -> None:
        close = np.linspace(1.0, 1.1, 50)
        dp = directional_persistence(close, period=10)
        assert dp[-1] > 0.8

    def test_choppy_market_low_persistence(self) -> None:
        close = np.array([1.0, 1.01, 1.0, 1.01, 1.0] * 10)
        dp = directional_persistence(close, period=10)
        assert dp[-1] < 0.3


class TestComputeAllProxies:
    def test_returns_all_keys(self, sample_ohlc: tuple) -> None:
        open_, high, low, close = sample_ohlc
        proxies = compute_all_proxies(open_, high, low, close)
        expected_keys = {"bar_efficiency", "wick_asymmetry", "spread_stress",
                         "vol_compression", "dir_persistence"}
        assert set(proxies.keys()) == expected_keys
        for v in proxies.values():
            assert v.shape == close.shape
