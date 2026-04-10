"""Tests for experiment campaign orchestration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from fx_smc_bot.config import AppConfig
from fx_smc_bot.research.campaigns import (
    CampaignReport,
    CampaignRunResult,
    run_baseline_vs_smc,
    run_config_sweep,
    run_walk_forward_campaign,
)
from tests.helpers import make_synthetic_data


class TestCampaignReport:
    def test_summary_table_format(self) -> None:
        report = CampaignReport(campaign_type="test")
        report.runs.append(CampaignRunResult(
            name="run_1",
            metrics={"sharpe_ratio": 0.5, "profit_factor": 1.2, "win_rate": 0.55, "total_pnl": 1000},
            trade_count=10,
        ))
        table = report.summary_table()
        assert "run_1" in table
        assert "test" in table

    def test_save_and_load(self, tmp_path: Path) -> None:
        report = CampaignReport(campaign_type="test", timestamp="2024-01-01")
        report.runs.append(CampaignRunResult(name="x", trade_count=5))
        out = tmp_path / "report.json"
        report.save(out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["campaign_type"] == "test"


class TestConfigSweep:
    def test_sweep_runs_all_variants(self) -> None:
        config = AppConfig()
        data = make_synthetic_data()
        overrides = [
            {"risk.base_risk_per_trade": 0.003},
            {"risk.base_risk_per_trade": 0.005},
            {"risk.base_risk_per_trade": 0.01},
        ]
        report = run_config_sweep(config, data, overrides)
        assert len(report.runs) == 3
        assert report.campaign_type == "config_sweep"


class TestBaselineVsSmc:
    def test_baseline_vs_smc_runs(self) -> None:
        config = AppConfig()
        data = make_synthetic_data()
        report = run_baseline_vs_smc(config, data)
        assert report.campaign_type == "baseline_vs_smc"
        names = [r.name for r in report.runs]
        assert "full_smc" in names


class TestWalkForward:
    def test_walk_forward_campaign(self) -> None:
        config = AppConfig()
        data = make_synthetic_data(n_bars=500)
        report = run_walk_forward_campaign(config, data, n_splits=3)
        assert report.campaign_type == "walk_forward"
        assert len(report.runs) >= 1
