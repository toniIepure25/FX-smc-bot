"""Research quality scores: quantitative measures for strategy confidence.

Computes stability, robustness, simplicity, OOS consistency,
diversification, and deployment readiness scores from backtest
results and campaign data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.domain import BacktestResult, ClosedTrade
from fx_smc_bot.research.campaigns import CampaignReport


@dataclass(slots=True, frozen=True)
class ResearchScores:
    stability: float
    robustness: float
    simplicity: float
    oos_consistency: float
    diversification: float
    deployment_readiness: float
    details: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "Research Quality Scores:",
            f"  Stability:            {self.stability:.3f}",
            f"  Robustness:           {self.robustness:.3f}",
            f"  Simplicity:           {self.simplicity:.3f}",
            f"  OOS Consistency:      {self.oos_consistency:.3f}",
            f"  Diversification:      {self.diversification:.3f}",
            f"  Deployment Readiness: {self.deployment_readiness:.3f}",
        ]
        verdict = "GO" if self.deployment_readiness >= 0.5 else "NO-GO"
        lines.append(f"\n  Verdict: {verdict}")
        return "\n".join(lines)


def stability_score(
    yearly_sharpes: list[float] | None = None,
    monthly_pnls: list[float] | None = None,
) -> float:
    """Consistency of returns across time periods.

    1.0 = perfectly stable positive returns, 0.0 = wildly inconsistent.
    Based on fraction of profitable periods and Sharpe consistency.
    """
    scores = []

    if monthly_pnls:
        positive_months = sum(1 for p in monthly_pnls if p > 0)
        scores.append(positive_months / len(monthly_pnls))

    if yearly_sharpes:
        positive_years = sum(1 for s in yearly_sharpes if s > 0)
        scores.append(positive_years / len(yearly_sharpes))
        if len(yearly_sharpes) > 1:
            std = float(np.std(yearly_sharpes))
            mean = float(np.mean(yearly_sharpes))
            consistency = 1.0 / (1.0 + std / max(abs(mean), 0.01))
            scores.append(consistency)

    return float(np.mean(scores)) if scores else 0.0


def robustness_score(
    baseline_sharpe: float,
    stressed_sharpes: list[float],
) -> float:
    """How well performance holds under cost/fill stress.

    Measures the fraction of stressed scenarios that remain profitable
    and the average Sharpe retention.
    """
    if baseline_sharpe <= 0 or not stressed_sharpes:
        return 0.0

    profitable = sum(1 for s in stressed_sharpes if s > 0)
    survival_rate = profitable / len(stressed_sharpes)

    retentions = [s / baseline_sharpe for s in stressed_sharpes if baseline_sharpe > 0]
    avg_retention = float(np.mean(retentions)) if retentions else 0.0

    return min(1.0, 0.5 * survival_rate + 0.5 * max(0.0, avg_retention))


def simplicity_score(
    full_strategy_sharpe: float,
    component_count: int,
    best_single_component_sharpe: float,
) -> float:
    """Measures whether added complexity is justified.

    High score = the full strategy's improvement over the best single
    component is large relative to the number of components.
    """
    if component_count <= 1 or full_strategy_sharpe <= 0:
        return 1.0

    improvement = full_strategy_sharpe - best_single_component_sharpe
    marginal_value = improvement / (component_count - 1)

    if best_single_component_sharpe > 0:
        relative_improvement = improvement / best_single_component_sharpe
    else:
        relative_improvement = improvement

    return float(np.clip(0.5 + 0.5 * relative_improvement, 0.0, 1.0))


def oos_consistency_score(
    is_sharpe: float,
    oos_sharpe: float,
) -> float:
    """Ratio of out-of-sample to in-sample performance.

    1.0 = OOS matches IS, > 1.0 capped at 1.0, 0.0 = total degradation.
    """
    if is_sharpe <= 0:
        return 0.0
    ratio = oos_sharpe / is_sharpe
    return float(np.clip(ratio, 0.0, 1.0))


def diversification_score(trades: list[ClosedTrade]) -> float:
    """Measures balance across pairs, sessions, directions, and families.

    1.0 = perfectly balanced, 0.0 = all trades concentrated in one bucket.
    """
    if not trades:
        return 0.0

    dimensions: list[list[str]] = [
        [t.pair.value for t in trades],
        [t.direction.value for t in trades],
        [t.family.value for t in trades],
    ]

    entropies = []
    for dim in dimensions:
        from collections import Counter
        counts = Counter(dim)
        total = sum(counts.values())
        probs = [c / total for c in counts.values()]
        max_entropy = np.log(len(counts)) if len(counts) > 1 else 1.0
        entropy = -sum(p * np.log(p) for p in probs if p > 0)
        entropies.append(entropy / max_entropy if max_entropy > 0 else 0.0)

    return float(np.mean(entropies))


def compute_research_scores(
    metrics: PerformanceSummary,
    trades: list[ClosedTrade],
    monthly_pnls: list[float] | None = None,
    yearly_sharpes: list[float] | None = None,
    stressed_sharpes: list[float] | None = None,
    component_count: int = 3,
    best_component_sharpe: float = 0.0,
    is_sharpe: float | None = None,
    oos_sharpe: float | None = None,
) -> ResearchScores:
    """Compute all research quality scores from available data."""
    stab = stability_score(yearly_sharpes, monthly_pnls)
    rob = robustness_score(metrics.sharpe_ratio, stressed_sharpes or [])
    simp = simplicity_score(metrics.sharpe_ratio, component_count, best_component_sharpe)
    oos = oos_consistency_score(is_sharpe or metrics.sharpe_ratio, oos_sharpe or metrics.sharpe_ratio)
    div = diversification_score(trades)

    deployment = float(np.mean([stab, rob, simp, oos, div]))

    details = {
        "overall_sharpe": metrics.sharpe_ratio,
        "overall_pf": metrics.profit_factor,
        "trade_count": len(trades),
        "stab_inputs": {"yearly_sharpes": yearly_sharpes, "monthly_pnls_count": len(monthly_pnls or [])},
        "rob_inputs": {"stressed_sharpes": stressed_sharpes},
    }

    return ResearchScores(
        stability=round(stab, 3),
        robustness=round(rob, 3),
        simplicity=round(simp, 3),
        oos_consistency=round(oos, 3),
        diversification=round(div, 3),
        deployment_readiness=round(deployment, 3),
        details=details,
    )
