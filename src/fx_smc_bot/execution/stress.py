"""Execution stress harness: run backtests under multiple execution assumptions.

Defines named ExecutionScenario profiles that modify spread, slippage,
and fill policy. The stress runner executes the same strategy config
under each scenario and compares degradation across them.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from fx_smc_bot.config import AppConfig, FillPolicy, TradingPair
from fx_smc_bot.data.models import BarSeries


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    name: str
    spread_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    fill_policy: FillPolicy = FillPolicy.CONSERVATIVE
    latency_bars: int = 0


OPTIMISTIC = ExecutionScenario(
    name="optimistic",
    spread_multiplier=0.5,
    slippage_multiplier=0.5,
    fill_policy=FillPolicy.OPTIMISTIC,
)

NEUTRAL = ExecutionScenario(
    name="neutral",
    spread_multiplier=1.0,
    slippage_multiplier=1.0,
    fill_policy=FillPolicy.CONSERVATIVE,
)

CONSERVATIVE = ExecutionScenario(
    name="conservative",
    spread_multiplier=1.5,
    slippage_multiplier=1.5,
    fill_policy=FillPolicy.CONSERVATIVE,
)

STRESSED = ExecutionScenario(
    name="stressed",
    spread_multiplier=2.5,
    slippage_multiplier=2.5,
    fill_policy=FillPolicy.CONSERVATIVE,
)

DEFAULT_SCENARIOS = [OPTIMISTIC, NEUTRAL, CONSERVATIVE, STRESSED]


@dataclass(slots=True)
class ScenarioResult:
    scenario_name: str
    total_trades: int = 0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0


@dataclass(slots=True)
class StressReport:
    results: list[ScenarioResult] = field(default_factory=list)
    baseline_name: str = "neutral"

    @property
    def baseline(self) -> ScenarioResult | None:
        for r in self.results:
            if r.scenario_name == self.baseline_name:
                return r
        return self.results[0] if self.results else None

    def degradation_summary(self) -> dict[str, dict[str, float]]:
        base = self.baseline
        if base is None or base.total_pnl == 0:
            return {}
        out: dict[str, dict[str, float]] = {}
        for r in self.results:
            if r.scenario_name == base.scenario_name:
                continue
            pnl_change = (r.total_pnl - base.total_pnl) / abs(base.total_pnl) if base.total_pnl else 0.0
            sharpe_change = r.sharpe_ratio - base.sharpe_ratio
            out[r.scenario_name] = {
                "pnl_change_pct": round(pnl_change * 100, 2),
                "sharpe_change": round(sharpe_change, 3),
                "wr_change_pct": round((r.win_rate - base.win_rate) * 100, 2),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios": [
                {
                    "name": r.scenario_name, "trades": r.total_trades,
                    "pnl": round(r.total_pnl, 2), "sharpe": round(r.sharpe_ratio, 3),
                    "max_dd_pct": round(r.max_drawdown_pct, 4), "win_rate": round(r.win_rate, 3),
                    "profit_factor": round(r.profit_factor, 3),
                }
                for r in self.results
            ],
            "degradation": self.degradation_summary(),
        }


def _apply_scenario(config: AppConfig, scenario: ExecutionScenario) -> AppConfig:
    """Return a modified copy of config with scenario-adjusted execution params."""
    cfg = config.model_copy(deep=True)
    exec_cfg = cfg.execution.model_copy(deep=True)
    exec_cfg.default_spread_pips *= scenario.spread_multiplier
    exec_cfg.slippage_pips *= scenario.slippage_multiplier
    exec_cfg.volatility_spread_factor *= scenario.spread_multiplier
    exec_cfg.volatility_slippage_factor *= scenario.slippage_multiplier
    exec_cfg.fill_policy = scenario.fill_policy
    cfg.execution = exec_cfg
    return cfg


def run_execution_stress(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    scenarios: list[ExecutionScenario] | None = None,
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> StressReport:
    """Run the backtest under multiple execution scenarios and return a stress report."""
    from fx_smc_bot.backtesting.engine import BacktestEngine
    from fx_smc_bot.backtesting.metrics import compute_metrics

    scenarios = scenarios or DEFAULT_SCENARIOS
    report = StressReport()

    for scenario in scenarios:
        scenario_cfg = _apply_scenario(config, scenario)
        engine = BacktestEngine(scenario_cfg)
        result = engine.run(data, htf_data)
        metrics = compute_metrics(result.trades, result.equity_curve, result.initial_capital)

        report.results.append(ScenarioResult(
            scenario_name=scenario.name,
            total_trades=metrics.total_trades,
            total_pnl=metrics.total_pnl,
            sharpe_ratio=metrics.sharpe_ratio,
            max_drawdown_pct=metrics.max_drawdown_pct,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
        ))

    return report
