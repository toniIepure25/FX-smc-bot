"""Tests for frozen config, data splits, and overfitting guard."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.config import AppConfig, TradingPair, Timeframe
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.frozen_config import (
    ConfigStatus,
    DataSplitPolicy,
    FrozenCandidate,
    OverfittingGuard,
    freeze_config,
    split_data,
    validate_frozen,
)


def _make_series(pair: TradingPair = TradingPair.EURUSD, n: int = 1000) -> BarSeries:
    ts = np.arange(
        np.datetime64("2023-01-01"), np.datetime64("2023-01-01") + np.timedelta64(n, "h"),
        np.timedelta64(1, "h"),
    )[:n]
    prices = np.cumsum(np.random.default_rng(42).standard_normal(n) * 0.001) + 1.1
    return BarSeries(
        pair=pair, timeframe=Timeframe.H1,
        timestamps=ts,
        open=prices, high=prices + 0.001, low=prices - 0.001, close=prices,
    )


class TestDataSplitPolicy:
    def test_valid_policy(self) -> None:
        p = DataSplitPolicy(train_end_pct=0.5, validation_end_pct=0.8, embargo_bars=5)
        assert p.train_end_pct == 0.5

    def test_invalid_policy_train_after_val(self) -> None:
        with pytest.raises(ValueError, match="Invalid split"):
            DataSplitPolicy(train_end_pct=0.9, validation_end_pct=0.8)

    def test_invalid_policy_zero(self) -> None:
        with pytest.raises(ValueError, match="Invalid split"):
            DataSplitPolicy(train_end_pct=0.0, validation_end_pct=0.8)


class TestFreezeConfig:
    def test_freeze_creates_hash(self) -> None:
        cfg = AppConfig()
        fc = freeze_config(cfg, label="test")
        assert len(fc.config_hash) == 16
        assert fc.status == ConfigStatus.LOCKED
        assert fc.label == "test"

    def test_freeze_preserves_config(self) -> None:
        cfg = AppConfig()
        fc = freeze_config(cfg, label="x")
        assert fc.config.alpha.enabled_families == cfg.alpha.enabled_families

    def test_frozen_is_deep_copy(self) -> None:
        cfg = AppConfig()
        fc = freeze_config(cfg, label="x")
        cfg.alpha.enabled_families = ["momentum"]
        assert fc.config.alpha.enabled_families != ["momentum"]

    def test_validate_frozen_passes(self) -> None:
        cfg = AppConfig()
        fc = freeze_config(cfg, label="x")
        assert validate_frozen(fc) is True

    def test_validate_frozen_detects_mutation(self) -> None:
        cfg = AppConfig()
        fc = freeze_config(cfg, label="x")
        fc.config.alpha.min_signal_score = 0.999
        assert validate_frozen(fc) is False

    def test_different_configs_different_hashes(self) -> None:
        cfg1 = AppConfig()
        cfg2 = AppConfig()
        cfg2.alpha.min_signal_score = 0.99
        fc1 = freeze_config(cfg1, label="a")
        fc2 = freeze_config(cfg2, label="b")
        assert fc1.config_hash != fc2.config_hash

    def test_to_dict(self) -> None:
        fc = freeze_config(AppConfig(), label="test")
        d = fc.to_dict()
        assert d["label"] == "test"
        assert "config_hash" in d


class TestSplitData:
    def test_split_sizes(self) -> None:
        series = _make_series(n=1000)
        data = {TradingPair.EURUSD: series}
        policy = DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.8, embargo_bars=10)
        train, val, holdout = split_data(data, policy)

        assert len(train[TradingPair.EURUSD]) == 600
        assert len(val[TradingPair.EURUSD]) == 190  # 800 - 610
        assert len(holdout[TradingPair.EURUSD]) == 190  # 1000 - 810

    def test_no_overlap(self) -> None:
        series = _make_series(n=500)
        data = {TradingPair.EURUSD: series}
        policy = DataSplitPolicy(embargo_bars=5)
        train, val, holdout = split_data(data, policy)
        total = len(train[TradingPair.EURUSD]) + len(val[TradingPair.EURUSD]) + len(holdout[TradingPair.EURUSD])
        assert total <= 500


class TestOverfittingGuard:
    def test_no_warning_when_evidence_sufficient(self) -> None:
        guard = OverfittingGuard()
        warnings = guard.warn_if_overfitting(3, 500, 5)
        assert warnings == []

    def test_warns_on_too_many_variants(self) -> None:
        guard = OverfittingGuard()
        warnings = guard.warn_if_overfitting(30, 100, 5)
        assert any("OVERFIT_RISK" in w for w in warnings)

    def test_warns_on_single_pair_overfit(self) -> None:
        guard = OverfittingGuard()
        warnings = guard.warn_if_overfitting(25, 500, 1)
        assert any("SINGLE_PAIR_OVERFIT" in w for w in warnings)

    def test_warns_on_insufficient_evidence(self) -> None:
        guard = OverfittingGuard()
        warnings = guard.warn_if_overfitting(2, 15, 1)
        assert any("INSUFFICIENT_EVIDENCE" in w for w in warnings)
