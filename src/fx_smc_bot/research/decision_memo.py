"""Research decision memo generation.

Produces structured go/no-go decisions with supporting evidence,
automated reasoning about champion viability, fragility concerns,
simplification recommendations, and next-step guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.gating import DeploymentGateConfig, GateResult, GateVerdict

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun


class DecisionType(str, Enum):
    PROMOTE = "promote"
    CONDITIONAL_PROMOTE = "conditional_promote"
    REJECT = "reject"
    RETIRE = "retire"
    SIMPLIFY = "simplify"
    CONTINUE_RESEARCH = "continue_research"


@dataclass(slots=True)
class ResearchDecision:
    decision: DecisionType
    champion_label: str
    confidence: str  # high / medium / low
    reasons: list[str] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "champion_label": self.champion_label,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "unresolved_risks": self.unresolved_risks,
            "next_steps": self.next_steps,
            "blocking_issues": self.blocking_issues,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class EvidencePackage:
    candidate_runs: list[CandidateRun] = field(default_factory=list)
    scorecards: list[CandidateScorecard] = field(default_factory=list)
    holdout_results: list[CandidateRun] | None = None
    stress_degradation: dict[str, Any] = field(default_factory=dict)
    gate_results: list[GateResult] = field(default_factory=list)


def generate_decision_memo(
    evidence: EvidencePackage,
    gate_config: DeploymentGateConfig | None = None,
) -> ResearchDecision:
    """Automated decision logic based on gate results and candidate quality."""
    cfg = gate_config or DeploymentGateConfig()
    reasons: list[str] = []
    risks: list[str] = []
    next_steps: list[str] = []
    blockers: list[str] = []

    # Find champion scorecard (rank 1 with passing gate)
    champion = None
    for sc in evidence.scorecards:
        if sc.rank == 1 and sc.gate_verdict in ("pass", "conditional"):
            champion = sc
            break

    if not champion:
        return ResearchDecision(
            decision=DecisionType.REJECT,
            champion_label="(none)",
            confidence="high",
            reasons=["No candidate passed the deployment gate."],
            next_steps=["Review gate thresholds or improve strategy components."],
            blocking_issues=["No viable champion identified."],
            timestamp=datetime.utcnow().isoformat(),
        )

    # Assess fragility
    if champion.fragility_penalty > 0.5:
        risks.append(f"High fragility ({champion.fragility_penalty:.2f}): "
                      f"performance degrades significantly under cost stress.")
        blockers.append("Execution fragility exceeds 50% threshold.")

    if champion.fragility_penalty > 0.3:
        risks.append(f"Moderate fragility ({champion.fragility_penalty:.2f}): "
                      f"stressed Sharpe = {champion.stressed_sharpe:.3f}.")

    # Assess simplicity
    if champion.simplicity_score < 0.5:
        reasons.append("Complex strategy: simplicity score below 0.5. "
                       "Consider whether a simpler variant achieves comparable results.")
        next_steps.append("Run ablation to identify minimum viable component set.")

    # Check holdout results
    holdout_pass = True
    if evidence.holdout_results:
        for hr in evidence.holdout_results:
            if hr.candidate.label == champion.label and hr.gate_result:
                if hr.gate_result.verdict == GateVerdict.FAIL:
                    holdout_pass = False
                    blockers.append(f"Holdout evaluation FAILED: {hr.gate_result.recommendation}")
                elif hr.gate_result.verdict == GateVerdict.CONDITIONAL:
                    risks.append(f"Holdout conditional: {hr.gate_result.recommendation}")
    else:
        risks.append("No holdout evaluation performed yet.")

    # Count passing candidates for confidence
    passing = [sc for sc in evidence.scorecards if sc.gate_verdict in ("pass", "conditional")]
    n_pass = len(passing)

    # Determine decision type and confidence
    if blockers:
        decision_type = DecisionType.REJECT if champion.fragility_penalty > 0.5 else DecisionType.CONDITIONAL_PROMOTE
        confidence = "low"
        next_steps.append("Address blocking issues before paper trading.")
    elif not holdout_pass:
        decision_type = DecisionType.REJECT
        confidence = "medium"
        reasons.append("Champion fails holdout gate -- likely overfit to training data.")
    elif champion.composite_score >= 0.5 and champion.gate_verdict == "pass":
        decision_type = DecisionType.PROMOTE
        confidence = "high" if champion.fragility_penalty < 0.2 else "medium"
        reasons.append(f"Champion {champion.label} passes all gates with composite {champion.composite_score:.3f}.")
        next_steps.append("Proceed to paper trading campaign.")
    elif champion.gate_verdict == "conditional":
        decision_type = DecisionType.CONDITIONAL_PROMOTE
        confidence = "medium"
        reasons.append(f"Champion passes blocking gates but has warnings.")
        next_steps.append("Review warnings and run paper trading with caution.")
    else:
        decision_type = DecisionType.CONTINUE_RESEARCH
        confidence = "low"
        reasons.append("Insufficient evidence for promotion.")
        next_steps.append("Explore alternative strategies or improve data quality.")

    # Simplification recommendation
    simpler_alternatives = [sc for sc in evidence.scorecards
                            if sc.simplicity_score > champion.simplicity_score
                            and sc.gate_verdict in ("pass", "conditional")
                            and sc.composite_score > champion.composite_score * 0.85]
    if simpler_alternatives:
        best_simple = simpler_alternatives[0]
        reasons.append(
            f"Simpler alternative {best_simple.label} achieves {best_simple.composite_score:.3f} "
            f"composite (vs {champion.composite_score:.3f}) with better simplicity "
            f"({best_simple.simplicity_score:.2f} vs {champion.simplicity_score:.2f})."
        )
        next_steps.append(f"Consider {best_simple.label} as a simpler champion.")

    return ResearchDecision(
        decision=decision_type,
        champion_label=champion.label,
        confidence=confidence,
        reasons=reasons,
        unresolved_risks=risks,
        next_steps=next_steps,
        blocking_issues=blockers,
        timestamp=datetime.utcnow().isoformat(),
    )


def format_decision_memo(
    decision: ResearchDecision,
    evidence: EvidencePackage,
) -> str:
    """Generate a full markdown decision memo."""
    lines = [
        "# Research Decision Memo",
        "",
        f"**Date**: {decision.timestamp or datetime.utcnow().isoformat()}",
        f"**Decision**: {decision.decision.value.upper()}",
        f"**Champion**: {decision.champion_label}",
        f"**Confidence**: {decision.confidence}",
        "",
        "## Executive Summary",
        "",
    ]

    for reason in decision.reasons:
        lines.append(f"- {reason}")

    lines.append("")
    lines.append("## What Works")
    lines.append("")
    passing = [sc for sc in evidence.scorecards if sc.gate_verdict in ("pass", "conditional")]
    if passing:
        for sc in passing:
            lines.append(f"- **{sc.label}**: Sharpe={sc.raw_sharpe:.3f}, "
                         f"composite={sc.composite_score:.3f}")
    else:
        lines.append("- No candidates passed the deployment gate.")

    lines.append("")
    lines.append("## What Is Fragile")
    lines.append("")
    fragile = [sc for sc in evidence.scorecards if sc.fragility_penalty > 0.3]
    if fragile:
        for sc in fragile:
            lines.append(f"- **{sc.label}**: fragility={sc.fragility_penalty:.2f}, "
                         f"stressed Sharpe={sc.stressed_sharpe:.3f}")
    else:
        lines.append("- No significant fragility concerns.")

    lines.append("")
    lines.append("## Simplification Recommendations")
    lines.append("")
    simple = sorted(evidence.scorecards, key=lambda s: s.simplicity_score, reverse=True)[:3]
    for sc in simple:
        lines.append(f"- {sc.label}: simplicity={sc.simplicity_score:.2f}, "
                     f"composite={sc.composite_score:.3f}")

    if decision.unresolved_risks:
        lines.append("")
        lines.append("## Unresolved Risks")
        lines.append("")
        for risk in decision.unresolved_risks:
            lines.append(f"- {risk}")

    if decision.blocking_issues:
        lines.append("")
        lines.append("## Blocking Issues")
        lines.append("")
        for issue in decision.blocking_issues:
            lines.append(f"- {issue}")

    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in decision.next_steps:
        lines.append(f"1. {step}")

    return "\n".join(lines)
