"""Tests for execution stress scenarios."""

from __future__ import annotations

import pytest

from fx_smc_bot.config import FillPolicy
from fx_smc_bot.execution.stress import (
    CONSERVATIVE,
    DEFAULT_SCENARIOS,
    ExecutionScenario,
    NEUTRAL,
    OPTIMISTIC,
    STRESSED,
    ScenarioResult,
    StressReport,
    _apply_scenario,
)
from fx_smc_bot.config import AppConfig


class TestExecutionScenario:
    def test_predefined_scenarios_exist(self) -> None:
        assert len(DEFAULT_SCENARIOS) == 4
        names = {s.name for s in DEFAULT_SCENARIOS}
        assert names == {"optimistic", "neutral", "conservative", "stressed"}

    def test_optimistic_lower_costs(self) -> None:
        assert OPTIMISTIC.spread_multiplier < 1.0
        assert OPTIMISTIC.slippage_multiplier < 1.0
        assert OPTIMISTIC.fill_policy == FillPolicy.OPTIMISTIC

    def test_stressed_higher_costs(self) -> None:
        assert STRESSED.spread_multiplier > 2.0
        assert STRESSED.slippage_multiplier > 2.0


class TestApplyScenario:
    def test_applies_spread_multiplier(self) -> None:
        config = AppConfig()
        original_spread = config.execution.default_spread_pips
        modified = _apply_scenario(config, STRESSED)
        assert modified.execution.default_spread_pips == pytest.approx(
            original_spread * STRESSED.spread_multiplier
        )

    def test_applies_fill_policy(self) -> None:
        config = AppConfig()
        modified = _apply_scenario(config, OPTIMISTIC)
        assert modified.execution.fill_policy == FillPolicy.OPTIMISTIC

    def test_does_not_mutate_original(self) -> None:
        config = AppConfig()
        original_spread = config.execution.default_spread_pips
        _apply_scenario(config, STRESSED)
        assert config.execution.default_spread_pips == original_spread


class TestStressReport:
    def test_degradation_summary(self) -> None:
        report = StressReport(results=[
            ScenarioResult("neutral", total_pnl=10000, sharpe_ratio=1.0, win_rate=0.55),
            ScenarioResult("stressed", total_pnl=5000, sharpe_ratio=0.5, win_rate=0.45),
        ])
        deg = report.degradation_summary()
        assert "stressed" in deg
        assert deg["stressed"]["pnl_change_pct"] == pytest.approx(-50.0)

    def test_baseline_identification(self) -> None:
        report = StressReport(results=[
            ScenarioResult("neutral"),
            ScenarioResult("stressed"),
        ])
        assert report.baseline is not None
        assert report.baseline.scenario_name == "neutral"

    def test_to_dict_structure(self) -> None:
        report = StressReport(results=[
            ScenarioResult("neutral", total_pnl=1000, sharpe_ratio=0.5),
        ])
        d = report.to_dict()
        assert "scenarios" in d
        assert "degradation" in d
