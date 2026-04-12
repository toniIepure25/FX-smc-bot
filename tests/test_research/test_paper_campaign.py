"""Tests for paper campaign orchestration."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from fx_smc_bot.config import AppConfig, TradingPair, Timeframe
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.frozen_config import (
    DataSplitPolicy,
    freeze_config,
)
from fx_smc_bot.research.paper_campaign import (
    PaperCampaignConfig,
    PaperCampaignResult,
    format_paper_report,
    run_paper_campaign,
)


def _make_series(n: int = 500) -> dict[TradingPair, BarSeries]:
    ts = np.arange(
        np.datetime64("2023-01-01"), np.datetime64("2023-01-01") + np.timedelta64(n, "h"),
        np.timedelta64(1, "h"),
    )[:n]
    prices = np.cumsum(np.random.default_rng(42).standard_normal(n) * 0.001) + 1.1
    series = BarSeries(
        pair=TradingPair.EURUSD, timeframe=Timeframe.H1,
        timestamps=ts,
        open=prices, high=prices + 0.001, low=prices - 0.001, close=prices,
    )
    return {TradingPair.EURUSD: series}


class TestPaperCampaignConfig:
    def test_defaults(self) -> None:
        fc = freeze_config(AppConfig(), label="test")
        cfg = PaperCampaignConfig(candidate=fc)
        assert cfg.data_slice == "holdout"
        assert cfg.max_discrepancy_pct == 5.0
        assert cfg.daily_summary is True


class TestPaperCampaignResult:
    def test_to_dict(self) -> None:
        result = PaperCampaignResult(
            run_id="test_123",
            candidate_label="test",
            final_equity=10500.0,
            total_trades=30,
            go_no_go="go",
        )
        d = result.to_dict()
        assert d["run_id"] == "test_123"
        assert d["final_equity"] == 10500.0
        assert d["go_no_go"] == "go"


class TestRunPaperCampaign:
    def test_aborts_on_invalid_hash(self, tmp_path) -> None:
        fc = freeze_config(AppConfig(), label="test")
        fc.config.alpha.min_signal_score = 0.999  # Break hash
        cfg = PaperCampaignConfig(candidate=fc)
        result = run_paper_campaign(cfg, _make_series(), output_dir=tmp_path)
        assert "ABORT" in result.notes[0]
        assert "hash mismatch" in result.notes[0]

    def test_aborts_on_insufficient_data(self, tmp_path) -> None:
        data = _make_series(n=50)
        fc = freeze_config(
            AppConfig(), label="test",
            data_split=DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.99),
        )
        cfg = PaperCampaignConfig(candidate=fc, data_slice="holdout")
        result = run_paper_campaign(cfg, data, output_dir=tmp_path)
        assert any("insufficient" in n.lower() or "ABORT" in n for n in result.notes)


class TestFormatPaperReport:
    def test_produces_markdown(self) -> None:
        result = PaperCampaignResult(
            run_id="test_123",
            candidate_label="my_strategy",
            final_equity=10500.0,
            total_trades=30,
            go_no_go="go",
            notes=["PnL discrepancy 2.1% within 5.0% threshold"],
        )
        md = format_paper_report(result)
        assert "# Paper Campaign Report" in md
        assert "my_strategy" in md
        assert "GO" in md

    def test_includes_notes(self) -> None:
        result = PaperCampaignResult(
            notes=["note1", "note2"],
        )
        md = format_paper_report(result)
        assert "note1" in md
        assert "note2" in md
