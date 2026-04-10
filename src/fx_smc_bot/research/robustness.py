"""Robustness diagnostics: parameter sensitivity, Monte Carlo, and cost sweeps.

These tools help distinguish genuine alpha from overfitting and assess
strategy sensitivity to execution assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from fx_smc_bot.backtesting.metrics import PerformanceSummary


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    parameter_name: str
    values_tested: list[Any]
    sharpe_ratios: list[float]
    profit_factors: list[float]
    trade_counts: list[int]


def parameter_sensitivity(
    run_fn: Callable[[Any], PerformanceSummary],
    parameter_name: str,
    values: list[Any],
) -> SensitivityResult:
    """Test strategy performance across a range of parameter values.

    `run_fn` takes a single parameter value and returns a PerformanceSummary.
    """
    sharpes: list[float] = []
    pfs: list[float] = []
    counts: list[int] = []

    for val in values:
        metrics = run_fn(val)
        sharpes.append(metrics.sharpe_ratio)
        pfs.append(metrics.profit_factor)
        counts.append(metrics.total_trades)

    return SensitivityResult(
        parameter_name=parameter_name,
        values_tested=values,
        sharpe_ratios=sharpes,
        profit_factors=pfs,
        trade_counts=counts,
    )


def monte_carlo_pnl_shuffle(
    pnls: list[float],
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, float]:
    """Shuffle trade PnLs to estimate the distribution of outcomes under randomness.

    Returns percentile statistics of the resulting equity curves.
    """
    rng = np.random.default_rng(seed)
    arr = np.array(pnls)
    final_equities: list[float] = []

    for _ in range(n_simulations):
        shuffled = rng.permutation(arr)
        cumulative = np.cumsum(shuffled)
        final_equities.append(float(cumulative[-1]) if len(cumulative) > 0 else 0.0)

    return {
        "mean": float(np.mean(final_equities)),
        "std": float(np.std(final_equities)),
        "p5": float(np.percentile(final_equities, 5)),
        "p25": float(np.percentile(final_equities, 25)),
        "p50": float(np.percentile(final_equities, 50)),
        "p75": float(np.percentile(final_equities, 75)),
        "p95": float(np.percentile(final_equities, 95)),
    }


@dataclass(frozen=True, slots=True)
class CostSweepPoint:
    """Result of running the strategy at a particular cost multiplier."""
    spread_multiplier: float
    sharpe_ratio: float
    profit_factor: float
    total_pnl: float
    total_trades: int


def cost_sensitivity_sweep(
    run_fn: Callable[[float], PerformanceSummary],
    multipliers: list[float] | None = None,
) -> list[CostSweepPoint]:
    """Run the strategy across different spread/slippage multipliers.

    `run_fn` accepts a cost multiplier (1.0 = baseline) and returns metrics.
    This tests whether the strategy survives realistic cost variation
    (e.g., 0.5x to 3x baseline spread).
    """
    if multipliers is None:
        multipliers = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]

    results: list[CostSweepPoint] = []
    for mult in multipliers:
        metrics = run_fn(mult)
        results.append(CostSweepPoint(
            spread_multiplier=mult,
            sharpe_ratio=metrics.sharpe_ratio,
            profit_factor=metrics.profit_factor,
            total_pnl=metrics.total_pnl,
            total_trades=metrics.total_trades,
        ))

    return results


def format_cost_sweep(points: list[CostSweepPoint]) -> str:
    """Format cost sweep results as a readable table."""
    lines = [
        f"{'Spread Mult':>12s}  {'Sharpe':>8s}  {'PF':>8s}  "
        f"{'Total PnL':>12s}  {'Trades':>7s}",
        "-" * 52,
    ]
    for p in points:
        lines.append(
            f"{p.spread_multiplier:>12.2f}  {p.sharpe_ratio:>8.3f}  "
            f"{p.profit_factor:>8.2f}  {p.total_pnl:>12,.2f}  {p.total_trades:>7d}"
        )
    return "\n".join(lines)
