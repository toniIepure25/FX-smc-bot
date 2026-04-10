"""Tests for deployment gating and promotion state machine."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from fx_smc_bot.research.gating import (
    DeploymentGateConfig,
    GateResult,
    GateSeverity,
    GateVerdict,
    PromotionState,
    StrategyCandidate,
    StrategyRegistry,
    evaluate_deployment_gate,
)


class TestEvaluateDeploymentGate:
    def test_passes_all_criteria(self) -> None:
        metrics = {
            "sharpe_ratio": 1.5, "profit_factor": 2.0,
            "max_drawdown_pct": 0.10, "total_trades": 100,
            "win_rate": 0.55,
        }
        result = evaluate_deployment_gate(metrics)
        assert result.verdict == GateVerdict.PASS
        assert not result.blocking_failures

    def test_fails_on_low_sharpe(self) -> None:
        metrics = {
            "sharpe_ratio": 0.1, "profit_factor": 2.0,
            "max_drawdown_pct": 0.10, "total_trades": 100,
            "win_rate": 0.55,
        }
        result = evaluate_deployment_gate(metrics)
        assert result.verdict == GateVerdict.FAIL
        assert "sharpe_ratio" in result.blocking_failures

    def test_fails_on_high_drawdown(self) -> None:
        metrics = {
            "sharpe_ratio": 1.0, "profit_factor": 1.5,
            "max_drawdown_pct": 0.35, "total_trades": 100,
            "win_rate": 0.55,
        }
        result = evaluate_deployment_gate(metrics)
        assert result.verdict == GateVerdict.FAIL
        assert "max_drawdown_pct" in result.blocking_failures

    def test_conditional_on_warning_scores(self) -> None:
        metrics = {
            "sharpe_ratio": 0.5, "profit_factor": 1.2,
            "max_drawdown_pct": 0.15, "total_trades": 50,
            "win_rate": 0.45,
        }
        scores = {"stability": 0.1, "robustness": 0.8}
        result = evaluate_deployment_gate(metrics, scores=scores)
        assert result.verdict == GateVerdict.CONDITIONAL
        assert "stability" in result.warnings

    def test_custom_gate_config(self) -> None:
        cfg = DeploymentGateConfig(min_sharpe=2.0)
        metrics = {
            "sharpe_ratio": 1.5, "profit_factor": 2.0,
            "max_drawdown_pct": 0.10, "total_trades": 100,
            "win_rate": 0.55,
        }
        result = evaluate_deployment_gate(metrics, gate_config=cfg)
        assert result.verdict == GateVerdict.FAIL

    def test_recommendation_string(self) -> None:
        metrics = {
            "sharpe_ratio": 1.0, "profit_factor": 1.5,
            "max_drawdown_pct": 0.10, "total_trades": 50,
            "win_rate": 0.50,
        }
        result = evaluate_deployment_gate(metrics)
        assert len(result.recommendation) > 0


class TestPromotionStateMachine:
    def test_valid_promotion_research_to_candidate(self) -> None:
        cand = StrategyCandidate(config_hash="abc")
        assert cand.promote(PromotionState.CANDIDATE)
        assert cand.state == PromotionState.CANDIDATE

    def test_valid_promotion_candidate_to_paper(self) -> None:
        cand = StrategyCandidate(config_hash="abc", state=PromotionState.CANDIDATE)
        assert cand.promote(PromotionState.PAPER_TESTING)
        assert cand.state == PromotionState.PAPER_TESTING

    def test_valid_promotion_paper_to_approved(self) -> None:
        cand = StrategyCandidate(config_hash="abc", state=PromotionState.PAPER_TESTING)
        assert cand.promote(PromotionState.APPROVED)
        assert cand.state == PromotionState.APPROVED

    def test_invalid_promotion_blocked(self) -> None:
        cand = StrategyCandidate(config_hash="abc")
        assert not cand.promote(PromotionState.APPROVED)
        assert cand.state == PromotionState.RESEARCH

    def test_rejected_can_return_to_research(self) -> None:
        cand = StrategyCandidate(config_hash="abc", state=PromotionState.REJECTED)
        assert cand.promote(PromotionState.RESEARCH)
        assert cand.state == PromotionState.RESEARCH

    def test_retired_is_terminal(self) -> None:
        cand = StrategyCandidate(config_hash="abc", state=PromotionState.RETIRED)
        assert not cand.promote(PromotionState.RESEARCH)


class TestStrategyRegistry:
    def test_register_and_retrieve(self, tmp_path: Path) -> None:
        reg = StrategyRegistry(tmp_path / "registry.json")
        cand = reg.register("hash1", label="test", run_id="run_001")
        assert cand.config_hash == "hash1"
        assert "run_001" in cand.run_ids

    def test_duplicate_register_appends_run(self, tmp_path: Path) -> None:
        reg = StrategyRegistry(tmp_path / "registry.json")
        reg.register("hash1", run_id="run_001")
        reg.register("hash1", run_id="run_002")
        cand = reg.get("hash1")
        assert cand is not None
        assert "run_002" in cand.run_ids

    def test_promote_via_registry(self, tmp_path: Path) -> None:
        reg = StrategyRegistry(tmp_path / "registry.json")
        reg.register("hash1")
        assert reg.promote("hash1", PromotionState.CANDIDATE)
        cand = reg.get("hash1")
        assert cand is not None
        assert cand.state == PromotionState.CANDIDATE

    def test_set_champion(self, tmp_path: Path) -> None:
        reg = StrategyRegistry(tmp_path / "registry.json")
        reg.register("a")
        reg.register("b")
        reg.set_champion("a")
        assert reg.get_champion() is not None
        assert reg.get_champion().config_hash == "a"

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.json"
        reg = StrategyRegistry(path)
        reg.register("hash1", label="persisted")
        reg.promote("hash1", PromotionState.CANDIDATE)

        reg2 = StrategyRegistry(path)
        cand = reg2.get("hash1")
        assert cand is not None
        assert cand.state == PromotionState.CANDIDATE

    def test_list_by_state(self, tmp_path: Path) -> None:
        reg = StrategyRegistry(tmp_path / "registry.json")
        reg.register("a")
        reg.register("b")
        reg.promote("a", PromotionState.CANDIDATE)
        candidates = reg.list_candidates(PromotionState.CANDIDATE)
        assert len(candidates) == 1
