"""Tests for campaign aggregation and leaderboard generation."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.campaign_aggregator import (
    CampaignArtifactIndex,
    LeaderboardEntry,
    build_leaderboard,
    format_fragility_leaderboard,
    format_leaderboard,
    format_stability_leaderboard,
    generate_executive_summary,
)


def _sc(label: str, composite: float = 0.5, sharpe: float = 1.0,
        gate: str = "pass", fragility: float = 0.1, families: int = 3,
        trades: int = 50, pnl: float = 1000.0) -> CandidateScorecard:
    sc = CandidateScorecard(
        label=label, composite_score=composite, raw_sharpe=sharpe,
        stressed_sharpe=sharpe * 0.9, gate_verdict=gate,
        fragility_penalty=fragility, stability_score=0.6,
        robustness_score=0.5, total_trades=trades, total_pnl=pnl,
        n_families=families, simplicity_score=0.5, oos_score=0.5,
        diversification_score=0.4, profit_factor=1.5, max_drawdown_pct=0.05,
    )
    sc.rank = 1
    sc.recommendation = "PROMOTE"
    return sc


class TestBuildLeaderboard:
    def test_returns_entries(self) -> None:
        cards = [_sc("a"), _sc("b", composite=0.3)]
        lb = build_leaderboard(cards)
        assert len(lb) == 2
        assert lb[0].label == "a"

    def test_entry_fields(self) -> None:
        cards = [_sc("x", sharpe=1.5, trades=100)]
        lb = build_leaderboard(cards)
        assert lb[0].sharpe == 1.5
        assert lb[0].trades == 100


class TestFormatLeaderboard:
    def test_markdown_table(self) -> None:
        cards = [_sc("a"), _sc("b")]
        lb = build_leaderboard(cards)
        md = format_leaderboard(lb)
        assert "# Candidate Leaderboard" in md
        assert "| a |" in md

    def test_fragility_leaderboard(self) -> None:
        cards = [_sc("fragile", fragility=0.8), _sc("robust", fragility=0.1)]
        md = format_fragility_leaderboard(cards)
        assert "Fragility Leaderboard" in md
        lines = md.split("\n")
        data_lines = [l for l in lines if l.startswith("| ") and "Rank" not in l and "---" not in l]
        assert "robust" in data_lines[0]

    def test_stability_leaderboard(self) -> None:
        cards = [_sc("stable"), _sc("unstable")]
        md = format_stability_leaderboard(cards)
        assert "Stability Leaderboard" in md


class TestExecutiveSummary:
    def test_summary_content(self) -> None:
        cards = [_sc("a", gate="pass"), _sc("b", gate="fail")]
        md = generate_executive_summary(cards, [])
        assert "Executive Summary" in md
        assert "Gate pass/conditional**: 1" in md
        assert "Gate fail**: 1" in md

    def test_with_no_cards(self) -> None:
        md = generate_executive_summary([], [])
        assert "Candidates evaluated**: 0" in md


class TestArtifactIndex:
    def test_to_dict(self) -> None:
        idx = CampaignArtifactIndex(campaign_id="test", timestamp="now")
        d = idx.to_dict()
        assert d["campaign_id"] == "test"
