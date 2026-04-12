"""Tests for champion bundle generation and validity checks."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from fx_smc_bot.config import AppConfig
from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.champion_bundle import (
    ChampionBundle,
    ExecutionProfile,
    InvalidationCriteria,
    build_champion_bundle,
    check_champion_validity,
    compare_challenger,
    format_champion_manifest,
    save_champion_bundle,
)
from fx_smc_bot.research.frozen_config import freeze_config
from fx_smc_bot.research.validation import CandidateRun, ValidationStage


def _make_run() -> CandidateRun:
    fc = freeze_config(AppConfig(), label="test_champion")
    run = CandidateRun(candidate=fc, stage=ValidationStage.FROZEN_EVAL)
    run.metrics = MagicMock()
    run.metrics.sharpe_ratio = 1.5
    run.metrics.profit_factor = 2.0
    run.metrics.win_rate = 0.55
    run.metrics.total_pnl = 5000.0
    run.metrics.total_trades = 80
    run.metrics.max_drawdown_pct = 0.05
    run.gate_result = MagicMock()
    run.gate_result.to_dict.return_value = {"verdict": "pass"}
    run.stress_report = MagicMock()
    run.stress_report.to_dict.return_value = {"scenarios": []}
    return run


def _make_scorecard() -> CandidateScorecard:
    return CandidateScorecard(
        label="test_champion", rank=1, composite_score=0.7,
        raw_sharpe=1.5, stressed_sharpe=1.2, gate_verdict="pass",
        fragility_penalty=0.2, simplicity_score=0.6,
    )


class TestBuildChampionBundle:
    def test_creates_bundle(self) -> None:
        run = _make_run()
        sc = _make_scorecard()
        bundle = build_champion_bundle(run.candidate, run, sc)
        assert bundle.champion_label == "test_champion"
        assert len(bundle.bundle_hash) == 16
        assert bundle.config_hash == run.candidate.config_hash

    def test_rejects_invalid_hash(self) -> None:
        run = _make_run()
        run.candidate.config.alpha.min_signal_score = 0.999
        sc = _make_scorecard()
        with pytest.raises(ValueError, match="config hash invalid"):
            build_champion_bundle(run.candidate, run, sc)

    def test_includes_execution_profile(self) -> None:
        run = _make_run()
        sc = _make_scorecard()
        prof = ExecutionProfile(fill_policy="conservative")
        bundle = build_champion_bundle(run.candidate, run, sc, execution_profile=prof)
        assert bundle.execution_profile["fill_policy"] == "conservative"


class TestCheckChampionValidity:
    def test_valid_champion(self) -> None:
        bundle = ChampionBundle(invalidation_criteria=InvalidationCriteria().to_dict())
        valid, issues = check_champion_validity(bundle, current_sharpe=0.5)
        assert valid
        assert issues == []

    def test_invalid_low_sharpe(self) -> None:
        bundle = ChampionBundle(invalidation_criteria=InvalidationCriteria().to_dict())
        valid, issues = check_champion_validity(bundle, current_sharpe=0.1)
        assert not valid
        assert any("Sharpe" in i for i in issues)

    def test_invalid_stale(self) -> None:
        bundle = ChampionBundle(invalidation_criteria=InvalidationCriteria().to_dict())
        valid, issues = check_champion_validity(bundle, days_since_frozen=100)
        assert not valid
        assert any("days old" in i for i in issues)


class TestCompareChallenger:
    def test_rejects_failing_gate(self) -> None:
        bundle = ChampionBundle(scorecard={"composite": 0.5})
        challenger = CandidateScorecard(label="ch", gate_verdict="fail", composite_score=0.8)
        replace, reason = compare_challenger(bundle, challenger)
        assert not replace
        assert "fails gate" in reason

    def test_rejects_insufficient_improvement(self) -> None:
        bundle = ChampionBundle(scorecard={"composite": 0.5})
        challenger = CandidateScorecard(label="ch", gate_verdict="pass", composite_score=0.52)
        replace, reason = compare_challenger(bundle, challenger)
        assert not replace

    def test_accepts_strong_challenger(self) -> None:
        bundle = ChampionBundle(scorecard={"composite": 0.5})
        challenger = CandidateScorecard(label="ch", gate_verdict="pass",
                                        composite_score=0.65, fragility_penalty=0.1)
        replace, reason = compare_challenger(bundle, challenger)
        assert replace
        assert "improves" in reason


class TestSaveAndFormat:
    def test_save_creates_files(self, tmp_path) -> None:
        run = _make_run()
        sc = _make_scorecard()
        bundle = build_champion_bundle(run.candidate, run, sc)
        out = save_champion_bundle(bundle, tmp_path)
        assert (out / "champion.json").exists()
        assert (out / "MANIFEST.md").exists()

    def test_manifest_markdown(self) -> None:
        bundle = ChampionBundle(
            champion_label="test", config_hash="abc123",
            bundle_hash="def456", metrics={"sharpe_ratio": 1.5},
            gate_result={"verdict": "pass", "recommendation": "ok"},
            execution_profile={"fill_policy": "pessimistic"},
            invalidation_criteria={"staleness_days": 90},
        )
        md = format_champion_manifest(bundle)
        assert "Champion Strategy Manifest" in md
        assert "test" in md
