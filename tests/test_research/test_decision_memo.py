"""Tests for research decision memo generation."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.decision_memo import (
    DecisionType,
    EvidencePackage,
    ResearchDecision,
    format_decision_memo,
    generate_decision_memo,
)
from fx_smc_bot.research.gating import DeploymentGateConfig, GateResult, GateVerdict


def _make_scorecard(
    label: str = "test",
    rank: int = 1,
    composite: float = 0.6,
    gate: str = "pass",
    fragility: float = 0.1,
    simplicity: float = 0.6,
) -> CandidateScorecard:
    return CandidateScorecard(
        label=label,
        rank=rank,
        composite_score=composite,
        gate_verdict=gate,
        fragility_penalty=fragility,
        simplicity_score=simplicity,
        raw_sharpe=1.0,
        stressed_sharpe=0.9,
        oos_score=0.5,
        diversification_score=0.4,
        stability_score=0.5,
        robustness_score=0.5,
        recommendation="PROMOTE",
    )


class TestGenerateDecisionMemo:
    def test_reject_when_no_champion(self) -> None:
        evidence = EvidencePackage(
            scorecards=[_make_scorecard(gate="fail")],
        )
        decision = generate_decision_memo(evidence)
        assert decision.decision == DecisionType.REJECT
        assert decision.champion_label == "(none)"

    def test_promote_good_champion(self) -> None:
        evidence = EvidencePackage(
            scorecards=[_make_scorecard(composite=0.6, gate="pass", fragility=0.1)],
        )
        decision = generate_decision_memo(evidence)
        assert decision.decision == DecisionType.PROMOTE
        assert decision.confidence in ("high", "medium")

    def test_conditional_when_gate_conditional(self) -> None:
        evidence = EvidencePackage(
            scorecards=[_make_scorecard(composite=0.6, gate="conditional", fragility=0.1)],
        )
        decision = generate_decision_memo(evidence)
        assert decision.decision == DecisionType.CONDITIONAL_PROMOTE

    def test_high_fragility_adds_risk(self) -> None:
        evidence = EvidencePackage(
            scorecards=[_make_scorecard(composite=0.6, gate="pass", fragility=0.6)],
        )
        decision = generate_decision_memo(evidence)
        assert any("fragility" in r.lower() for r in decision.unresolved_risks)
        assert any("fragility" in b.lower() for b in decision.blocking_issues)

    def test_simplification_recommendation(self) -> None:
        complex_card = _make_scorecard("complex", rank=1, composite=0.5, simplicity=0.3)
        simple_card = _make_scorecard("simple", rank=2, composite=0.45, gate="pass", simplicity=0.9)
        evidence = EvidencePackage(
            scorecards=[complex_card, simple_card],
        )
        decision = generate_decision_memo(evidence)
        assert any("simpler" in r.lower() or "simple" in r.lower() for r in decision.reasons + decision.next_steps)

    def test_to_dict(self) -> None:
        decision = ResearchDecision(
            decision=DecisionType.PROMOTE,
            champion_label="test",
            confidence="high",
            reasons=["good"],
        )
        d = decision.to_dict()
        assert d["decision"] == "promote"
        assert d["champion_label"] == "test"


class TestFormatDecisionMemo:
    def test_produces_markdown(self) -> None:
        evidence = EvidencePackage(
            scorecards=[_make_scorecard()],
        )
        decision = generate_decision_memo(evidence)
        md = format_decision_memo(decision, evidence)
        assert "# Research Decision Memo" in md
        assert "## Executive Summary" in md
        assert "## What Works" in md
        assert "## Next Steps" in md

    def test_includes_fragility_section(self) -> None:
        card = _make_scorecard(fragility=0.5)
        evidence = EvidencePackage(scorecards=[card])
        decision = generate_decision_memo(evidence)
        md = format_decision_memo(decision, evidence)
        assert "What Is Fragile" in md

    def test_empty_scorecards(self) -> None:
        evidence = EvidencePackage(scorecards=[])
        decision = ResearchDecision(
            decision=DecisionType.REJECT,
            champion_label="(none)",
            confidence="high",
            reasons=["nothing"],
        )
        md = format_decision_memo(decision, evidence)
        assert "No candidates passed" in md
