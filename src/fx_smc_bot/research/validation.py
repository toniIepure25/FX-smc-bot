"""Full validation campaign orchestrator.

Runs a disciplined multi-stage evaluation of frozen strategy candidates:
  1. Backtest each candidate on the training split
  2. Compute metrics, research scores, and deployment gate
  3. Run execution stress scenarios
  4. Evaluate shortlisted candidates on the holdout split
  5. Produce ranking and selection artifacts
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.execution.stress import StressReport, run_execution_stress
from fx_smc_bot.research.evaluation import EvaluationReport, evaluate
from fx_smc_bot.research.frozen_config import (
    FrozenCandidate,
    OverfittingGuard,
    split_data,
    validate_frozen,
)
from fx_smc_bot.research.gating import (
    DeploymentGateConfig,
    GateResult,
    GateVerdict,
    evaluate_deployment_gate,
)
from fx_smc_bot.research.scores import ResearchScores, compute_research_scores

logger = logging.getLogger(__name__)


class ValidationStage(str, Enum):
    EXPLORATORY = "exploratory"
    FILTERED = "filtered"
    FROZEN_EVAL = "frozen_eval"
    HOLDOUT = "holdout"
    PAPER_CANDIDATE = "paper_candidate"
    PAPER_REVIEW = "paper_review"
    DECIDED = "decided"


@dataclass(slots=True)
class CandidateRun:
    candidate: FrozenCandidate
    stage: ValidationStage
    metrics: PerformanceSummary | None = None
    stress_report: StressReport | None = None
    gate_result: GateResult | None = None
    scores: ResearchScores | None = None
    attribution: EvaluationReport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.candidate.label,
            "config_hash": self.candidate.config_hash,
            "stage": self.stage.value,
        }
        if self.metrics:
            d["metrics"] = {
                "sharpe_ratio": self.metrics.sharpe_ratio,
                "profit_factor": self.metrics.profit_factor,
                "win_rate": self.metrics.win_rate,
                "total_pnl": self.metrics.total_pnl,
                "total_trades": self.metrics.total_trades,
                "max_drawdown_pct": self.metrics.max_drawdown_pct,
            }
        if self.gate_result:
            d["gate"] = self.gate_result.to_dict()
        if self.scores:
            d["scores"] = {
                "stability": self.scores.stability,
                "robustness": self.scores.robustness,
                "simplicity": self.scores.simplicity,
                "oos_consistency": self.scores.oos_consistency,
                "diversification": self.scores.diversification,
                "deployment_readiness": self.scores.deployment_readiness,
            }
        if self.stress_report:
            d["stress"] = self.stress_report.to_dict()
        d.update(self.metadata)
        return d


class ValidationCampaign:
    """Orchestrates a full candidate evaluation pipeline."""

    def __init__(
        self,
        candidates: list[FrozenCandidate],
        data: dict[TradingPair, BarSeries],
        htf_data: dict[TradingPair, BarSeries] | None = None,
        gate_config: DeploymentGateConfig | None = None,
    ) -> None:
        self._candidates = candidates
        self._data = data
        self._htf_data = htf_data
        self._gate_config = gate_config or DeploymentGateConfig()
        self._overfit_guard = OverfittingGuard()

    def run_full_evaluation(self) -> list[CandidateRun]:
        """Evaluate all candidates on training data with stress testing."""
        results: list[CandidateRun] = []

        for i, candidate in enumerate(self._candidates):
            if not validate_frozen(candidate):
                logger.warning("Config hash mismatch for %s -- skipping", candidate.label)
                continue

            logger.info("Evaluating %d/%d: %s", i + 1, len(self._candidates), candidate.label)

            train_data, val_data, _ = split_data(self._data, candidate.data_split)
            run = self._run_single(candidate, train_data, ValidationStage.FROZEN_EVAL)

            # Run stress on training data
            try:
                stress = run_execution_stress(candidate.config, train_data, htf_data=self._htf_data)
                run.stress_report = stress
            except Exception as e:
                logger.warning("Stress test failed for %s: %s", candidate.label, e)

            # Compute cost degradation for gating
            scores_dict: dict[str, float] = {}
            if run.scores:
                scores_dict = {
                    "stability": run.scores.stability,
                    "robustness": run.scores.robustness,
                    "oos_consistency": run.scores.oos_consistency,
                    "diversification": run.scores.diversification,
                }
            if run.stress_report and run.metrics and run.metrics.total_pnl != 0:
                base = run.stress_report.baseline
                if base and base.total_pnl != 0:
                    conservative = [r for r in run.stress_report.results if r.scenario_name == "conservative"]
                    if conservative:
                        degradation = 1.0 - (conservative[0].total_pnl / base.total_pnl)
                        scores_dict["cost_degradation_pct"] = max(0.0, degradation)

            # Gate evaluation
            if run.metrics:
                metrics_dict = {
                    "sharpe_ratio": run.metrics.sharpe_ratio,
                    "profit_factor": run.metrics.profit_factor,
                    "max_drawdown_pct": run.metrics.max_drawdown_pct,
                    "total_trades": run.metrics.total_trades,
                    "win_rate": run.metrics.win_rate,
                }
                run.gate_result = evaluate_deployment_gate(
                    metrics_dict, self._gate_config, scores_dict,
                )

            results.append(run)

        # Overfitting check
        total_trades = sum(r.metrics.total_trades for r in results if r.metrics)
        n_pairs = len(self._data)
        warnings = self._overfit_guard.warn_if_overfitting(
            len(results), total_trades, n_pairs,
        )
        for w in warnings:
            logger.warning(w)

        return results

    def run_holdout_evaluation(
        self,
        shortlist: list[FrozenCandidate],
    ) -> list[CandidateRun]:
        """Final locked evaluation on holdout data only."""
        results: list[CandidateRun] = []

        for candidate in shortlist:
            if not validate_frozen(candidate):
                logger.warning("Config hash mismatch for %s in holdout -- skipping", candidate.label)
                continue

            _, _, holdout_data = split_data(self._data, candidate.data_split)

            has_data = any(len(s) > 50 for s in holdout_data.values())
            if not has_data:
                logger.warning("Insufficient holdout data for %s", candidate.label)
                continue

            run = self._run_single(candidate, holdout_data, ValidationStage.HOLDOUT)

            if run.metrics:
                metrics_dict = {
                    "sharpe_ratio": run.metrics.sharpe_ratio,
                    "profit_factor": run.metrics.profit_factor,
                    "max_drawdown_pct": run.metrics.max_drawdown_pct,
                    "total_trades": run.metrics.total_trades,
                    "win_rate": run.metrics.win_rate,
                }
                run.gate_result = evaluate_deployment_gate(metrics_dict, self._gate_config)

            results.append(run)

        return results

    def _run_single(
        self,
        candidate: FrozenCandidate,
        data_slice: dict[TradingPair, BarSeries],
        stage: ValidationStage,
    ) -> CandidateRun:
        """Run a single backtest and compute all derived metrics."""
        run = CandidateRun(candidate=candidate, stage=stage)

        try:
            engine = BacktestEngine(candidate.config)
            result = engine.run(data_slice, self._htf_data)
            metrics = engine.metrics(result)
            run.metrics = metrics

            if result.trades:
                run.attribution = evaluate(result, metrics)

                stressed_sharpes: list[float] = []
                if run.stress_report:
                    stressed_sharpes = [r.sharpe_ratio for r in run.stress_report.results]

                monthly_pnls: list[float] | None = None
                yearly_pnls: list[float] | None = None
                if run.attribution:
                    if run.attribution.by_month:
                        monthly_pnls = [s.total_pnl for s in run.attribution.by_month]
                    if run.attribution.by_year:
                        yearly_pnls = [s.total_pnl for s in run.attribution.by_year]

                n_families = len(candidate.config.alpha.enabled_families)
                best_component_sharpe = 0.0

                run.scores = compute_research_scores(
                    metrics, result.trades,
                    monthly_pnls=monthly_pnls,
                    yearly_sharpes=yearly_pnls,
                    stressed_sharpes=stressed_sharpes,
                    component_count=max(1, n_families),
                    best_component_sharpe=best_component_sharpe,
                )

        except Exception as e:
            logger.warning("Backtest failed for %s: %s", candidate.label, e)
            run.metadata["error"] = str(e)

        return run

    def save_campaign(
        self,
        runs: list[CandidateRun],
        output_dir: Path | str,
        holdout_runs: list[CandidateRun] | None = None,
    ) -> Path:
        """Save all campaign artifacts to a directory."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        campaign_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "n_candidates": len(runs),
            "runs": [r.to_dict() for r in runs],
        }
        if holdout_runs:
            campaign_data["holdout"] = [r.to_dict() for r in holdout_runs]

        with open(out / "campaign.json", "w") as f:
            json.dump(campaign_data, f, indent=2, default=str)

        return out
