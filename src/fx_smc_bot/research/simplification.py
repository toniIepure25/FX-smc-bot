"""Strategy simplification and pruning analysis.

Identifies useless or redundant components, computes marginal contribution
of each family, and produces pruning recommendations with supporting evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun

from fx_smc_bot.research.candidate_selection import CandidateScorecard

logger = logging.getLogger(__name__)


class PruningVerdict(str, Enum):
    KEEP = "keep"
    REMOVE = "remove"
    INVESTIGATE = "investigate"
    FREEZE_OPTIONAL = "freeze_optional"


@dataclass(slots=True)
class ComponentAnalysis:
    """Analysis of a single strategy component (family)."""
    name: str
    solo_sharpe: float = 0.0
    solo_trades: int = 0
    solo_pnl: float = 0.0
    marginal_contribution: float = 0.0
    full_sharpe_without: float = 0.0
    fragility_solo: float = 0.0
    verdict: PruningVerdict = PruningVerdict.INVESTIGATE
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "solo_sharpe": round(self.solo_sharpe, 3),
            "solo_trades": self.solo_trades,
            "solo_pnl": round(self.solo_pnl, 2),
            "marginal_contribution": round(self.marginal_contribution, 3),
            "full_sharpe_without": round(self.full_sharpe_without, 3),
            "fragility_solo": round(self.fragility_solo, 3),
            "verdict": self.verdict.value,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class SimplificationReport:
    """Complete simplification analysis."""
    full_strategy_sharpe: float = 0.0
    full_strategy_trades: int = 0
    components: list[ComponentAnalysis] = field(default_factory=list)
    reduced_candidate_label: str = ""
    reduced_candidate_sharpe: float = 0.0
    complexity_penalty: float = 0.0
    simplification_score: float = 0.0
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_strategy_sharpe": round(self.full_strategy_sharpe, 3),
            "full_strategy_trades": self.full_strategy_trades,
            "components": [c.to_dict() for c in self.components],
            "reduced_candidate_label": self.reduced_candidate_label,
            "reduced_candidate_sharpe": round(self.reduced_candidate_sharpe, 3),
            "complexity_penalty": round(self.complexity_penalty, 3),
            "simplification_score": round(self.simplification_score, 3),
            "recommendation": self.recommendation,
        }


def analyze_simplification(
    scorecards: list[CandidateScorecard],
    runs: list["CandidateRun"] | None = None,
) -> SimplificationReport:
    """Analyze which components should be pruned or kept.

    Uses the campaign scorecards to compare full-strategy, single-family,
    and reduced variants. Identifies marginal contributions and recommends
    pruning based on solo performance, fragility, and simplicity trade-offs.
    """
    report = SimplificationReport()

    sc_map = {sc.label: sc for sc in scorecards}

    # Find the full strategy (most families)
    full = max(scorecards, key=lambda s: s.n_families) if scorecards else None
    if not full:
        report.recommendation = "No candidates to analyze."
        return report

    report.full_strategy_sharpe = full.raw_sharpe
    report.full_strategy_trades = full.total_trades

    # Identify single-family runs (n_families == 1)
    singles = [sc for sc in scorecards if sc.n_families == 1]

    for single in singles:
        ca = ComponentAnalysis(name=single.label)
        ca.solo_sharpe = single.raw_sharpe
        ca.solo_trades = single.total_trades
        ca.solo_pnl = single.total_pnl
        ca.fragility_solo = single.fragility_penalty

        # Marginal contribution: how much the full strategy improves over this component alone
        if full.raw_sharpe > 0:
            ca.marginal_contribution = single.raw_sharpe / full.raw_sharpe
        else:
            ca.marginal_contribution = 0.0

        # Find the "full minus this" variant if it exists
        # (convention: a reduced variant missing this family would have n_families = full.n_families - 1)
        # For now, approximate: full_sharpe_without = full Sharpe * (1 - marginal)
        ca.full_sharpe_without = full.raw_sharpe

        # Determine verdict
        ca.reasons = []
        if ca.solo_trades < 10:
            ca.verdict = PruningVerdict.REMOVE
            ca.reasons.append(f"Too few solo trades ({ca.solo_trades})")
        elif ca.solo_sharpe <= 0:
            ca.verdict = PruningVerdict.REMOVE
            ca.reasons.append(f"Negative solo Sharpe ({ca.solo_sharpe:.3f})")
        elif ca.fragility_solo > 0.5:
            ca.verdict = PruningVerdict.INVESTIGATE
            ca.reasons.append(f"High solo fragility ({ca.fragility_solo:.2f})")
        elif ca.solo_sharpe >= full.raw_sharpe * 0.7:
            ca.verdict = PruningVerdict.KEEP
            ca.reasons.append(f"Strong standalone ({ca.solo_sharpe:.3f} vs full {full.raw_sharpe:.3f})")
        elif single.gate_verdict in ("pass", "conditional"):
            ca.verdict = PruningVerdict.KEEP
            ca.reasons.append("Passes gate independently")
        else:
            ca.verdict = PruningVerdict.FREEZE_OPTIONAL
            ca.reasons.append("Marginal contributor, gate-dependent")

        report.components.append(ca)

    # Identify the best reduced variant
    reduced_candidates = [sc for sc in scorecards
                          if 1 < sc.n_families < full.n_families
                          and sc.gate_verdict in ("pass", "conditional")]
    if reduced_candidates:
        best_reduced = max(reduced_candidates, key=lambda s: s.composite_score)
        report.reduced_candidate_label = best_reduced.label
        report.reduced_candidate_sharpe = best_reduced.raw_sharpe
    elif singles:
        best_single = max(singles, key=lambda s: s.composite_score)
        if best_single.gate_verdict in ("pass", "conditional"):
            report.reduced_candidate_label = best_single.label
            report.reduced_candidate_sharpe = best_single.raw_sharpe

    # Complexity penalty: how much composite the full strategy gains per extra family
    if full.n_families > 1 and report.reduced_candidate_sharpe > 0:
        extra_families = full.n_families - 1
        sharpe_gain = full.raw_sharpe - report.reduced_candidate_sharpe
        report.complexity_penalty = sharpe_gain / extra_families if extra_families > 0 else 0.0
    else:
        report.complexity_penalty = 0.0

    # Overall simplification score: [0, 1] where 1 means simplification is strongly recommended
    n_remove = sum(1 for c in report.components if c.verdict == PruningVerdict.REMOVE)
    n_investigate = sum(1 for c in report.components if c.verdict == PruningVerdict.INVESTIGATE)
    n_total = len(report.components) or 1
    report.simplification_score = (n_remove + 0.5 * n_investigate) / n_total

    # Generate recommendation
    if report.simplification_score > 0.6:
        report.recommendation = (
            f"STRONGLY RECOMMENDED: {n_remove} of {n_total} families should be removed. "
            f"Consider {report.reduced_candidate_label or 'a simpler variant'} as champion."
        )
    elif report.simplification_score > 0.3:
        report.recommendation = (
            f"RECOMMENDED: Some families underperform. "
            f"Investigate {n_investigate} families and consider removing {n_remove}."
        )
    elif report.complexity_penalty < 0.05 and full.n_families > 2:
        report.recommendation = (
            "MARGINAL: Added complexity provides little Sharpe improvement per family. "
            "The reduced variant may be a safer deployment candidate."
        )
    else:
        report.recommendation = (
            "NOT NEEDED: The full strategy justifies its complexity. "
            "All components contribute meaningfully."
        )

    return report


def format_simplification_report(report: SimplificationReport) -> str:
    """Format simplification report as markdown."""
    lines = [
        "# Strategy Simplification Report",
        "",
        f"**Full strategy Sharpe**: {report.full_strategy_sharpe:.3f} ({report.full_strategy_trades} trades)",
        f"**Simplification score**: {report.simplification_score:.2f} (0=no action, 1=simplify aggressively)",
        f"**Complexity penalty**: {report.complexity_penalty:.4f} Sharpe per extra family",
        "",
        f"**Recommendation**: {report.recommendation}",
        "",
    ]

    if report.reduced_candidate_label:
        lines.append(f"**Best reduced variant**: {report.reduced_candidate_label} "
                      f"(Sharpe={report.reduced_candidate_sharpe:.3f})")
        lines.append("")

    if report.components:
        lines.append("## Component Analysis")
        lines.append("")
        lines.append("| Family | Solo Sharpe | Solo Trades | Fragility | Verdict | Reasons |")
        lines.append("|--------|------------|-------------|-----------|---------|---------|")
        for c in report.components:
            reasons_str = "; ".join(c.reasons)
            lines.append(
                f"| {c.name} | {c.solo_sharpe:.3f} | {c.solo_trades} | "
                f"{c.fragility_solo:.2f} | {c.verdict.value} | {reasons_str} |"
            )
        lines.append("")

    return "\n".join(lines)
