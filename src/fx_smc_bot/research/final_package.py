"""Final research package: produces the culmination of a validation wave.

Generates a continuation recommendation, final reports, and a structured
decision-ready package that answers whether to continue, simplify, or
abandon the current strategy approach.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.champion_bundle import ChampionBundle
from fx_smc_bot.research.decision_memo import ResearchDecision
from fx_smc_bot.research.simplification import SimplificationReport

logger = logging.getLogger(__name__)


class ContinuationOutcome(str, Enum):
    CONTINUE_PAPER_TRADING = "continue_paper_trading"
    CONTINUE_WITH_SIMPLIFICATION = "continue_with_simplification"
    HOLD_FOR_MORE_VALIDATION = "hold_for_more_validation"
    REWORK_STRATEGY = "rework_strategy"
    NO_GO_CURRENT_APPROACH = "no_go_current_approach"


@dataclass(slots=True)
class ContinuationRecommendation:
    """Final actionable recommendation."""
    outcome: ContinuationOutcome = ContinuationOutcome.HOLD_FOR_MORE_VALIDATION
    confidence: str = "low"
    champion_label: str = ""
    challenger_label: str = ""
    reasons: list[str] = field(default_factory=list)
    simplification_needed: bool = False
    components_to_remove: list[str] = field(default_factory=list)
    components_to_keep: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "confidence": self.confidence,
            "champion_label": self.champion_label,
            "challenger_label": self.challenger_label,
            "reasons": self.reasons,
            "simplification_needed": self.simplification_needed,
            "components_to_remove": self.components_to_remove,
            "components_to_keep": self.components_to_keep,
            "open_questions": self.open_questions,
            "next_actions": self.next_actions,
            "timestamp": self.timestamp,
        }


def generate_continuation_recommendation(
    decision: ResearchDecision,
    simplification: SimplificationReport,
    champion_scorecard: CandidateScorecard | None = None,
    challenger_scorecard: CandidateScorecard | None = None,
    holdout_passed: bool = False,
    paper_stage_passed: bool | None = None,
) -> ContinuationRecommendation:
    """Synthesize all evidence into a single continuation recommendation."""
    rec = ContinuationRecommendation(timestamp=datetime.utcnow().isoformat())

    if champion_scorecard:
        rec.champion_label = champion_scorecard.label
    if challenger_scorecard:
        rec.challenger_label = challenger_scorecard.label

    # Collect components to keep/remove from simplification
    for comp in simplification.components:
        if comp.verdict.value == "remove":
            rec.components_to_remove.append(comp.name)
        elif comp.verdict.value in ("keep",):
            rec.components_to_keep.append(comp.name)

    rec.simplification_needed = simplification.simplification_score > 0.3

    # Decision tree
    if decision.decision.value == "reject" and not champion_scorecard:
        rec.outcome = ContinuationOutcome.NO_GO_CURRENT_APPROACH
        rec.confidence = "high"
        rec.reasons.append("No candidate passed deployment gates.")
        rec.reasons.append("Current strategy approach does not produce viable candidates.")
        rec.next_actions.append("Consider fundamental strategy redesign.")
        rec.next_actions.append("Review data quality and market regime coverage.")
        return rec

    if decision.decision.value == "reject" and champion_scorecard:
        if rec.simplification_needed and simplification.reduced_candidate_sharpe > 0:
            rec.outcome = ContinuationOutcome.CONTINUE_WITH_SIMPLIFICATION
            rec.confidence = "medium"
            rec.reasons.append(f"Champion rejected, but reduced variant "
                               f"{simplification.reduced_candidate_label} shows promise.")
            rec.next_actions.append(f"Promote {simplification.reduced_candidate_label} as new candidate.")
            rec.next_actions.append(f"Remove: {', '.join(rec.components_to_remove) or 'none'}.")
            return rec
        else:
            rec.outcome = ContinuationOutcome.REWORK_STRATEGY
            rec.confidence = "medium"
            rec.reasons.append("Champion rejected and no viable reduced variant found.")
            rec.next_actions.append("Investigate failure modes and revise strategy logic.")
            return rec

    if not holdout_passed:
        rec.outcome = ContinuationOutcome.HOLD_FOR_MORE_VALIDATION
        rec.confidence = "low"
        rec.reasons.append("Holdout validation not yet passed or not yet run.")
        rec.open_questions.append("Does the champion survive on unseen data?")
        rec.next_actions.append("Run holdout evaluation before further promotion.")
        return rec

    if paper_stage_passed is False:
        rec.outcome = ContinuationOutcome.HOLD_FOR_MORE_VALIDATION
        rec.confidence = "low"
        rec.reasons.append("Paper trading stage failed or showed excessive discrepancy.")
        rec.next_actions.append("Investigate paper-vs-backtest divergence.")
        rec.next_actions.append("Re-run paper campaign after fixes.")
        return rec

    # Champion passed gates and holdout
    if rec.simplification_needed:
        rec.outcome = ContinuationOutcome.CONTINUE_WITH_SIMPLIFICATION
        rec.confidence = "medium" if champion_scorecard and champion_scorecard.fragility_penalty < 0.3 else "low"
        rec.reasons.append(f"Champion viable but carries unnecessary complexity "
                           f"(simplification score: {simplification.simplification_score:.2f}).")
        rec.next_actions.append(f"Remove: {', '.join(rec.components_to_remove) or 'none'}.")
        rec.next_actions.append("Re-validate reduced champion before paper trading.")
    else:
        rec.outcome = ContinuationOutcome.CONTINUE_PAPER_TRADING
        if champion_scorecard:
            rec.confidence = "high" if champion_scorecard.fragility_penalty < 0.2 else "medium"
        else:
            rec.confidence = "medium"
        rec.reasons.append("Champion passes all gates, holdout, and justifies its complexity.")
        rec.next_actions.append("Proceed to structured paper trading campaign.")
        rec.next_actions.append("Monitor with weekly review checkpoints.")

    if champion_scorecard and champion_scorecard.fragility_penalty > 0.3:
        rec.open_questions.append(
            f"Execution fragility ({champion_scorecard.fragility_penalty:.2f}) is elevated. "
            f"Paper trading should confirm viability under real execution."
        )

    return rec


def save_final_package(
    output_dir: Path | str,
    recommendation: ContinuationRecommendation,
    decision: ResearchDecision,
    simplification: SimplificationReport,
    champion_bundle: ChampionBundle | None = None,
    challenger_bundle: ChampionBundle | None = None,
    scorecards: list[CandidateScorecard] | None = None,
) -> Path:
    """Save the complete final research package to disk."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Continuation recommendation
    rec_path = out / "continuation_recommendation.json"
    with open(rec_path, "w") as f:
        json.dump(recommendation.to_dict(), f, indent=2)

    # Decision memo
    dec_path = out / "research_decision.json"
    with open(dec_path, "w") as f:
        json.dump(decision.to_dict(), f, indent=2)

    # Simplification report
    simp_path = out / "simplification_report.json"
    with open(simp_path, "w") as f:
        json.dump(simplification.to_dict(), f, indent=2)

    # Champion bundle
    if champion_bundle:
        champ_dir = out / "champion_bundle"
        champ_dir.mkdir(exist_ok=True)
        with open(champ_dir / "champion.json", "w") as f:
            json.dump(champion_bundle.to_dict(), f, indent=2, default=str)

    # Challenger bundle
    if challenger_bundle:
        chall_dir = out / "challenger_bundle"
        chall_dir.mkdir(exist_ok=True)
        with open(chall_dir / "challenger.json", "w") as f:
            json.dump(challenger_bundle.to_dict(), f, indent=2, default=str)

    # Markdown reports
    (out / "final_research_decision.md").write_text(
        format_final_decision(recommendation, decision, simplification)
    )

    if scorecards:
        (out / "final_candidate_comparison.md").write_text(
            format_candidate_comparison(scorecards)
        )

    from fx_smc_bot.research.simplification import format_simplification_report
    (out / "simplification_report.md").write_text(
        format_simplification_report(simplification)
    )

    logger.info("Final research package saved to %s", out)
    return out


def format_final_decision(
    recommendation: ContinuationRecommendation,
    decision: ResearchDecision,
    simplification: SimplificationReport,
) -> str:
    """Format the final research decision as markdown."""
    lines = [
        "# Final Research Decision",
        "",
        f"**Date**: {recommendation.timestamp}",
        f"**Outcome**: {recommendation.outcome.value.upper().replace('_', ' ')}",
        f"**Confidence**: {recommendation.confidence}",
        f"**Champion**: {recommendation.champion_label or '(none)'}",
        "",
        "## Recommendation",
        "",
    ]

    for reason in recommendation.reasons:
        lines.append(f"- {reason}")

    if recommendation.simplification_needed:
        lines.append("")
        lines.append("## Simplification Required")
        lines.append("")
        if recommendation.components_to_remove:
            lines.append(f"**Remove**: {', '.join(recommendation.components_to_remove)}")
        if recommendation.components_to_keep:
            lines.append(f"**Keep**: {', '.join(recommendation.components_to_keep)}")

    if recommendation.open_questions:
        lines.append("")
        lines.append("## Open Questions")
        lines.append("")
        for q in recommendation.open_questions:
            lines.append(f"- {q}")

    lines.append("")
    lines.append("## Next Actions")
    lines.append("")
    for i, action in enumerate(recommendation.next_actions, 1):
        lines.append(f"{i}. {action}")

    lines.append("")
    lines.append("## Research Decision Details")
    lines.append("")
    lines.append(f"- Decision type: {decision.decision.value}")
    lines.append(f"- Champion: {decision.champion_label}")
    lines.append(f"- Confidence: {decision.confidence}")
    if decision.blocking_issues:
        lines.append(f"- Blocking issues: {', '.join(decision.blocking_issues)}")

    return "\n".join(lines)


def format_candidate_comparison(scorecards: list[CandidateScorecard]) -> str:
    """Format final side-by-side candidate comparison."""
    lines = [
        "# Final Candidate Comparison",
        "",
        "| Rank | Label | Composite | Sharpe | PF | Trades | Fragility | Families | Gate |",
        "|------|-------|-----------|--------|----|--------|-----------|----------|------|",
    ]
    for sc in scorecards:
        lines.append(
            f"| {sc.rank} | {sc.label} | {sc.composite_score:.3f} | "
            f"{sc.raw_sharpe:.3f} | {sc.profit_factor:.2f} | "
            f"{sc.total_trades} | {sc.fragility_penalty:.2f} | "
            f"{sc.n_families} | {sc.gate_verdict} |"
        )

    lines.append("")

    # Summary
    n_pass = sum(1 for sc in scorecards if sc.gate_verdict in ("pass", "conditional"))
    lines.append(f"**Total candidates**: {len(scorecards)}")
    lines.append(f"**Gate pass/conditional**: {n_pass}")
    lines.append(f"**Gate fail**: {len(scorecards) - n_pass}")

    return "\n".join(lines)
