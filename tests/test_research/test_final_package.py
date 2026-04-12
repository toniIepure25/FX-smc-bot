"""Tests for final research package and continuation recommendation."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.champion_bundle import ChampionBundle
from fx_smc_bot.research.decision_memo import DecisionType, ResearchDecision
from fx_smc_bot.research.final_package import (
    ContinuationOutcome,
    ContinuationRecommendation,
    format_candidate_comparison,
    format_final_decision,
    generate_continuation_recommendation,
    save_final_package,
)
from fx_smc_bot.research.simplification import (
    ComponentAnalysis,
    PruningVerdict,
    SimplificationReport,
)


def _decision(dtype: str = "promote", label: str = "test") -> ResearchDecision:
    return ResearchDecision(
        decision=DecisionType(dtype),
        champion_label=label,
        confidence="medium",
    )


def _simplification(score: float = 0.2, reduced: str = "") -> SimplificationReport:
    return SimplificationReport(
        simplification_score=score,
        reduced_candidate_label=reduced,
        reduced_candidate_sharpe=0.8 if reduced else 0.0,
        components=[
            ComponentAnalysis(name="sweep", verdict=PruningVerdict.KEEP),
            ComponentAnalysis(name="bos", verdict=PruningVerdict.REMOVE),
        ],
    )


def _sc(label: str = "test", composite: float = 0.6, fragility: float = 0.15,
        gate: str = "pass") -> CandidateScorecard:
    return CandidateScorecard(
        label=label, composite_score=composite, fragility_penalty=fragility,
        gate_verdict=gate, raw_sharpe=1.2, stressed_sharpe=1.0,
    )


class TestContinuationRecommendation:
    def test_no_go_when_no_champion(self) -> None:
        decision = _decision("reject", "(none)")
        simp = _simplification()
        rec = generate_continuation_recommendation(decision, simp)
        assert rec.outcome == ContinuationOutcome.NO_GO_CURRENT_APPROACH

    def test_simplify_when_rejected_but_reduced_viable(self) -> None:
        decision = _decision("reject", "full_smc")
        simp = _simplification(score=0.5, reduced="sweep_only")
        sc = _sc("full_smc")
        rec = generate_continuation_recommendation(decision, simp, sc)
        assert rec.outcome == ContinuationOutcome.CONTINUE_WITH_SIMPLIFICATION

    def test_rework_when_no_reduced(self) -> None:
        decision = _decision("reject", "full_smc")
        simp = _simplification(score=0.2)
        sc = _sc("full_smc")
        rec = generate_continuation_recommendation(decision, simp, sc)
        assert rec.outcome == ContinuationOutcome.REWORK_STRATEGY

    def test_hold_when_no_holdout(self) -> None:
        decision = _decision("promote", "champ")
        simp = _simplification(score=0.1)
        sc = _sc("champ")
        rec = generate_continuation_recommendation(decision, simp, sc, holdout_passed=False)
        assert rec.outcome == ContinuationOutcome.HOLD_FOR_MORE_VALIDATION

    def test_continue_paper_when_all_pass(self) -> None:
        decision = _decision("promote", "champ")
        simp = _simplification(score=0.1)
        sc = _sc("champ")
        rec = generate_continuation_recommendation(decision, simp, sc, holdout_passed=True)
        assert rec.outcome == ContinuationOutcome.CONTINUE_PAPER_TRADING

    def test_simplify_when_needed(self) -> None:
        decision = _decision("promote", "champ")
        simp = _simplification(score=0.5, reduced="sweep_only")
        sc = _sc("champ")
        rec = generate_continuation_recommendation(decision, simp, sc, holdout_passed=True)
        assert rec.outcome == ContinuationOutcome.CONTINUE_WITH_SIMPLIFICATION


class TestSaveFinalPackage:
    def test_creates_files(self, tmp_path) -> None:
        rec = ContinuationRecommendation(
            outcome=ContinuationOutcome.CONTINUE_PAPER_TRADING, confidence="high",
        )
        decision = _decision()
        simp = _simplification()
        cards = [_sc("a"), _sc("b")]
        out = save_final_package(tmp_path, rec, decision, simp, scorecards=cards)
        assert (out / "continuation_recommendation.json").exists()
        assert (out / "research_decision.json").exists()
        assert (out / "final_research_decision.md").exists()
        assert (out / "final_candidate_comparison.md").exists()
        assert (out / "simplification_report.md").exists()


class TestFormatFinalDecision:
    def test_markdown_output(self) -> None:
        rec = ContinuationRecommendation(
            outcome=ContinuationOutcome.CONTINUE_PAPER_TRADING,
            confidence="high", champion_label="test",
            reasons=["Strong candidate"], next_actions=["Paper trade"],
        )
        decision = _decision()
        simp = _simplification()
        md = format_final_decision(rec, decision, simp)
        assert "Final Research Decision" in md
        assert "CONTINUE PAPER TRADING" in md

    def test_includes_simplification_section(self) -> None:
        rec = ContinuationRecommendation(
            outcome=ContinuationOutcome.CONTINUE_WITH_SIMPLIFICATION,
            confidence="medium", simplification_needed=True,
            components_to_remove=["bos"],
        )
        decision = _decision()
        simp = _simplification(score=0.5)
        md = format_final_decision(rec, decision, simp)
        assert "Simplification Required" in md


class TestFormatCandidateComparison:
    def test_comparison_table(self) -> None:
        cards = [_sc("a"), _sc("b", gate="fail")]
        md = format_candidate_comparison(cards)
        assert "Final Candidate Comparison" in md
        assert "Gate pass/conditional**: 1" in md
