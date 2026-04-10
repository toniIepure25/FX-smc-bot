"""Structured evaluation: slice backtest results along multiple dimensions.

Provides year-by-year, pair-by-pair, session-by-session, and regime-by-regime
performance breakdowns, plus cost sensitivity analysis.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fx_smc_bot.backtesting.attribution import AttributionSlice, _group_by, by_interaction
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.domain import BacktestResult, ClosedTrade, EquityPoint


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    overall: PerformanceSummary
    by_year: list[AttributionSlice]
    by_month: list[AttributionSlice]
    by_pair: list[AttributionSlice]
    by_session: list[AttributionSlice]
    by_direction: list[AttributionSlice]
    by_family: list[AttributionSlice]
    by_regime: list[AttributionSlice] = field(default_factory=list)
    pair_x_regime: list[AttributionSlice] = field(default_factory=list)
    family_x_regime: list[AttributionSlice] = field(default_factory=list)


def evaluate(
    result: BacktestResult,
    metrics: PerformanceSummary,
) -> EvaluationReport:
    """Run full structured evaluation on a backtest result."""
    trades = result.trades

    by_year = _group_by(trades, key=lambda t: str(t.opened_at.year))
    by_month = _group_by(trades, key=lambda t: t.opened_at.strftime("%Y-%m"))
    by_pair = _group_by(trades, key=lambda t: t.pair.value)
    by_session = _group_by(
        trades,
        key=lambda t: t.session.value if t.session else "unknown",
    )
    by_direction = _group_by(trades, key=lambda t: t.direction.value)
    by_family = _group_by(trades, key=lambda t: t.family.value)

    regime_key = lambda t: t.regime if t.regime else "unknown"
    by_regime = _group_by(trades, key=regime_key)

    pair_x_regime = by_interaction(
        trades, key_a=lambda t: t.pair.value, key_b=regime_key,
    )
    family_x_regime = by_interaction(
        trades, key_a=lambda t: t.family.value, key_b=regime_key,
    )

    return EvaluationReport(
        overall=metrics,
        by_year=by_year,
        by_month=by_month,
        by_pair=by_pair,
        by_session=by_session,
        by_direction=by_direction,
        by_family=by_family,
        by_regime=by_regime,
        pair_x_regime=pair_x_regime,
        family_x_regime=family_x_regime,
    )


@dataclass(frozen=True, slots=True)
class CostSensitivityPoint:
    cost_multiplier: float
    sharpe_ratio: float
    profit_factor: float
    total_pnl: float
    win_rate: float


def cost_sensitivity(
    trades: list[ClosedTrade],
    equity_curve: list[EquityPoint],
    initial_capital: float,
    multipliers: list[float] | None = None,
) -> list[CostSensitivityPoint]:
    """Test how performance degrades as execution costs scale.

    Adjusts trade PnLs by simulating different cost environments.
    Multiplier 1.0 = baseline, 2.0 = double costs, 0.5 = half costs.
    """
    if multipliers is None:
        multipliers = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

    baseline_metrics = compute_metrics(trades, equity_curve, initial_capital)
    if not trades:
        return []

    baseline_pnls = np.array([t.pnl for t in trades])
    # Estimate execution cost per trade: proportional to units
    avg_cost_per_trade = sum(
        (t.position.entry_fill.spread_cost + t.position.entry_fill.slippage) * t.units
        for t in trades
        if t.position.entry_fill is not None
    ) / len(trades) if trades else 0.0

    results: list[CostSensitivityPoint] = []
    for mult in multipliers:
        cost_delta = avg_cost_per_trade * (mult - 1.0)
        adjusted_pnls = baseline_pnls - cost_delta
        total_pnl = float(np.sum(adjusted_pnls))
        wins = int(np.sum(adjusted_pnls > 0))
        win_rate = wins / len(adjusted_pnls) if len(adjusted_pnls) > 0 else 0.0
        gross_profit = float(np.sum(adjusted_pnls[adjusted_pnls > 0])) if wins > 0 else 0.0
        losses = adjusted_pnls[adjusted_pnls < 0]
        gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Approximate Sharpe scaling
        if baseline_metrics.sharpe_ratio != 0 and baseline_metrics.total_pnl != 0:
            pnl_ratio = total_pnl / baseline_metrics.total_pnl
            approx_sharpe = baseline_metrics.sharpe_ratio * pnl_ratio
        else:
            approx_sharpe = 0.0

        results.append(CostSensitivityPoint(
            cost_multiplier=mult,
            sharpe_ratio=round(approx_sharpe, 3),
            profit_factor=round(pf, 2),
            total_pnl=round(total_pnl, 2),
            win_rate=round(win_rate, 3),
        ))

    return results
