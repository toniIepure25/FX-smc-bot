"""Tests for strategy simplification and pruning analysis."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.simplification import (
    ComponentAnalysis,
    PruningVerdict,
    SimplificationReport,
    analyze_simplification,
    format_simplification_report,
)


def _sc(label: str, composite: float = 0.5, sharpe: float = 1.0,
        gate: str = "pass", families: int = 3, trades: int = 50,
        pnl: float = 1000.0, fragility: float = 0.1) -> CandidateScorecard:
    sc = CandidateScorecard(
        label=label, composite_score=composite, raw_sharpe=sharpe,
        stressed_sharpe=sharpe * 0.9, gate_verdict=gate,
        fragility_penalty=fragility, n_families=families,
        total_trades=trades, total_pnl=pnl, stability_score=0.5,
        robustness_score=0.5, simplicity_score=0.5, oos_score=0.5,
        diversification_score=0.4, profit_factor=1.5, max_drawdown_pct=0.05,
    )
    sc.rank = 1
    sc.recommendation = "test"
    return sc


class TestAnalyzeSimplification:
    def test_empty_scorecards(self) -> None:
        report = analyze_simplification([])
        assert "No candidates" in report.recommendation

    def test_finds_full_strategy(self) -> None:
        cards = [
            _sc("full_smc", families=3, sharpe=1.2),
            _sc("sweep_only", families=1, sharpe=0.9),
            _sc("bos_only", families=1, sharpe=0.3, trades=5),
        ]
        report = analyze_simplification(cards)
        assert report.full_strategy_sharpe == 1.2
        assert len(report.components) == 2

    def test_removes_low_trade_count(self) -> None:
        cards = [
            _sc("full", families=3, sharpe=1.0),
            _sc("weak", families=1, sharpe=0.5, trades=5),
        ]
        report = analyze_simplification(cards)
        weak = [c for c in report.components if c.name == "weak"]
        assert len(weak) == 1
        assert weak[0].verdict == PruningVerdict.REMOVE

    def test_removes_negative_sharpe(self) -> None:
        cards = [
            _sc("full", families=3, sharpe=1.0),
            _sc("bad", families=1, sharpe=-0.3, trades=50),
        ]
        report = analyze_simplification(cards)
        bad = [c for c in report.components if c.name == "bad"]
        assert bad[0].verdict == PruningVerdict.REMOVE

    def test_keeps_strong_solo(self) -> None:
        cards = [
            _sc("full", families=3, sharpe=1.0),
            _sc("strong", families=1, sharpe=0.8, trades=50),
        ]
        report = analyze_simplification(cards)
        strong = [c for c in report.components if c.name == "strong"]
        assert strong[0].verdict == PruningVerdict.KEEP

    def test_identifies_reduced_candidate(self) -> None:
        cards = [
            _sc("full", families=3, sharpe=1.0, composite=0.6),
            _sc("reduced", families=2, sharpe=0.95, composite=0.55),
            _sc("single", families=1, sharpe=0.5, composite=0.3),
        ]
        report = analyze_simplification(cards)
        assert report.reduced_candidate_label == "reduced"


class TestFormatSimplificationReport:
    def test_produces_markdown(self) -> None:
        report = SimplificationReport(
            full_strategy_sharpe=1.0,
            full_strategy_trades=50,
            components=[
                ComponentAnalysis(name="sweep", solo_sharpe=0.8, solo_trades=30,
                                  verdict=PruningVerdict.KEEP, reasons=["good"]),
            ],
            recommendation="test recommendation",
        )
        md = format_simplification_report(report)
        assert "Simplification Report" in md
        assert "sweep" in md
        assert "test recommendation" in md

    def test_includes_component_table(self) -> None:
        report = SimplificationReport(
            components=[
                ComponentAnalysis(name="a", verdict=PruningVerdict.REMOVE, reasons=["bad"]),
                ComponentAnalysis(name="b", verdict=PruningVerdict.KEEP, reasons=["good"]),
            ],
        )
        md = format_simplification_report(report)
        assert "| a |" in md
        assert "| b |" in md
