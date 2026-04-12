"""Tests for candidate selection and ranking logic."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.candidate_selection import (
    CandidateScorecard,
    ScorecardWeights,
    format_ranking_table,
    format_selection_report,
    rank_candidates,
    select_champion,
)


def _make_scorecard(
    label: str = "test",
    composite: float = 0.5,
    gate: str = "pass",
    fragility: float = 0.1,
    raw_sharpe: float = 1.0,
) -> CandidateScorecard:
    return CandidateScorecard(
        label=label,
        raw_sharpe=raw_sharpe,
        stressed_sharpe=raw_sharpe * (1 - fragility),
        composite_score=composite,
        gate_verdict=gate,
        fragility_penalty=fragility,
        simplicity_score=0.6,
        oos_score=0.5,
        diversification_score=0.4,
        stability_score=0.5,
        robustness_score=0.5,
    )


class TestSelectChampion:
    def test_champion_is_first_passing(self) -> None:
        cards = [
            _make_scorecard("best", composite=0.8, gate="pass"),
            _make_scorecard("mid", composite=0.6, gate="pass"),
            _make_scorecard("worst", composite=0.3, gate="fail"),
        ]
        champ, challengers = select_champion(cards)
        assert champ is not None
        assert champ.label == "best"
        assert len(challengers) == 1
        assert challengers[0].label == "mid"

    def test_no_champion_when_all_fail(self) -> None:
        cards = [
            _make_scorecard("a", composite=0.8, gate="fail"),
            _make_scorecard("b", composite=0.6, gate="fail"),
        ]
        champ, challengers = select_champion(cards)
        assert champ is None
        assert challengers == []

    def test_conditional_can_be_champion(self) -> None:
        cards = [
            _make_scorecard("cond", composite=0.7, gate="conditional"),
        ]
        champ, _ = select_champion(cards)
        assert champ is not None
        assert champ.label == "cond"

    def test_empty_scorecards(self) -> None:
        champ, challengers = select_champion([])
        assert champ is None
        assert challengers == []


class TestFormatRankingTable:
    def test_produces_markdown(self) -> None:
        cards = [_make_scorecard("a", composite=0.5)]
        cards[0].rank = 1
        cards[0].recommendation = "PROMOTE"
        md = format_ranking_table(cards)
        assert "| Rank |" in md
        assert "| 1 |" in md

    def test_multiple_rows(self) -> None:
        cards = [
            _make_scorecard("a", composite=0.8),
            _make_scorecard("b", composite=0.4),
        ]
        for i, c in enumerate(cards):
            c.rank = i + 1
            c.recommendation = "test"
        md = format_ranking_table(cards)
        assert md.count("| a |") == 1
        assert md.count("| b |") == 1


class TestFormatSelectionReport:
    def test_with_champion(self) -> None:
        champ = _make_scorecard("champion", composite=0.8, gate="pass")
        rejected = [_make_scorecard("bad", composite=0.2, gate="fail")]
        rejected[0].recommendation = "REJECT: fails gate"
        md = format_selection_report(champ, [], rejected)
        assert "## Champion" in md
        assert "champion" in md
        assert "## Rejected" in md

    def test_without_champion(self) -> None:
        md = format_selection_report(None, [], [])
        assert "No Champion Selected" in md

    def test_with_challengers(self) -> None:
        champ = _make_scorecard("c", composite=0.8, gate="pass")
        challengers = [_make_scorecard("ch1", composite=0.6, gate="pass")]
        md = format_selection_report(champ, challengers, [])
        assert "## Challengers" in md
        assert "ch1" in md
