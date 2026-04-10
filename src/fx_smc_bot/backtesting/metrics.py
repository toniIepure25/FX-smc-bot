"""Performance metrics computed from the trade ledger.

Includes: Sharpe, Sortino, Calmar, max drawdown, expectancy, profit factor,
win rate, avg reward/risk, turnover, and rolling variants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from fx_smc_bot.domain import ClosedTrade, EquityPoint


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_pnl: float
    avg_winner: float
    avg_loser: float
    profit_factor: float
    expectancy: float
    expectancy_pips: float
    avg_rr_ratio: float
    total_pnl: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    annualized_return: float
    total_days: float


def compute_metrics(
    trades: list[ClosedTrade],
    equity_curve: list[EquityPoint],
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.0,
) -> PerformanceSummary:
    """Compute comprehensive performance metrics."""
    n = len(trades)
    if n == 0:
        return _empty_summary()

    pnls = np.array([t.pnl for t in trades])
    pnl_pips = np.array([t.pnl_pips for t in trades])
    winners = pnls[pnls > 0]
    losers = pnls[pnls < 0]

    total_pnl = float(np.sum(pnls))
    win_rate = len(winners) / n if n > 0 else 0.0
    avg_pnl = float(np.mean(pnls))
    avg_winner = float(np.mean(winners)) if len(winners) > 0 else 0.0
    avg_loser = float(np.mean(losers)) if len(losers) > 0 else 0.0

    gross_profit = float(np.sum(winners)) if len(winners) > 0 else 0.0
    gross_loss = abs(float(np.sum(losers))) if len(losers) > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    expectancy = avg_pnl
    expectancy_pips = float(np.mean(pnl_pips))

    rr_ratios = [t.reward_risk_ratio for t in trades]
    avg_rr = float(np.mean(rr_ratios)) if rr_ratios else 0.0

    # Drawdown from equity curve
    max_dd, max_dd_pct = _max_drawdown(equity_curve)

    # Annualized return and risk metrics from equity curve
    ann_ret, sharpe, sortino, calmar, total_days = _risk_metrics(
        equity_curve, initial_capital, max_dd_pct, risk_free_rate,
    )

    return PerformanceSummary(
        total_trades=n,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        avg_winner=avg_winner,
        avg_loser=avg_loser,
        profit_factor=profit_factor,
        expectancy=expectancy,
        expectancy_pips=expectancy_pips,
        avg_rr_ratio=avg_rr,
        total_pnl=total_pnl,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        annualized_return=ann_ret,
        total_days=total_days,
    )


def _max_drawdown(equity_curve: list[EquityPoint]) -> tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0
    equities = [ep.equity for ep in equity_curve]
    peak = equities[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    return max_dd, max_dd_pct


def _risk_metrics(
    equity_curve: list[EquityPoint],
    initial_capital: float,
    max_dd_pct: float,
    risk_free_rate: float,
) -> tuple[float, float, float, float, float]:
    """Compute annualized return, Sharpe, Sortino, Calmar."""
    if len(equity_curve) < 2:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    equities = np.array([ep.equity for ep in equity_curve])
    returns = np.diff(equities) / equities[:-1]

    total_days = (equity_curve[-1].timestamp - equity_curve[0].timestamp).total_seconds() / 86400
    if total_days <= 0:
        total_days = 1.0

    total_return = (equities[-1] / initial_capital) - 1.0
    ann_factor = 252.0 / total_days if total_days > 0 else 1.0
    ann_ret = total_return * ann_factor

    daily_rf = risk_free_rate / 252.0
    excess = returns - daily_rf

    std = float(np.std(excess, ddof=1)) if len(excess) > 1 else 1.0
    sharpe = float(np.mean(excess)) / std * np.sqrt(252) if std > 0 else 0.0

    downside = excess[excess < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 1.0
    sortino = float(np.mean(excess)) / downside_std * np.sqrt(252) if downside_std > 0 else 0.0

    calmar = ann_ret / max_dd_pct if max_dd_pct > 0 else 0.0

    return ann_ret, sharpe, sortino, calmar, total_days


def _empty_summary() -> PerformanceSummary:
    return PerformanceSummary(
        total_trades=0, winning_trades=0, losing_trades=0, win_rate=0.0,
        avg_pnl=0.0, avg_winner=0.0, avg_loser=0.0, profit_factor=0.0,
        expectancy=0.0, expectancy_pips=0.0, avg_rr_ratio=0.0,
        total_pnl=0.0, max_drawdown=0.0, max_drawdown_pct=0.0,
        sharpe_ratio=0.0, sortino_ratio=0.0, calmar_ratio=0.0,
        annualized_return=0.0, total_days=0.0,
    )
