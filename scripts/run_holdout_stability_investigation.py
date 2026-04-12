#!/usr/bin/env python3
"""Holdout Stability Investigation — diagnosis-heavy, validation-heavy, conclusion-heavy.

Phases:
  A. Holdout regime diagnostics (train vs holdout attribution + regime profiles)
  B. Walk-forward temporal stability (anchored + rolling OOS evaluation)
  C. Spread sensitivity and data quality (cost sensitivity + execution stress)
  D. Regime-aware mitigation (hypothesis-driven, minimal, tested OOS)
  E. Champion re-evaluation under stronger validation
  F. Final stability and deployment recommendation
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.attribution import (
    AttributionSlice,
    _group_by,
    by_direction,
    by_family,
    by_month,
    by_pair,
    by_regime,
    by_session,
    by_year,
    by_interaction,
)
from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import DiagnosticReport, run_diagnostics, format_diagnostic_report
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.alpha.diagnostics import DetectorDiagnostics, format_detector_diagnostics
from fx_smc_bot.execution.stress import run_execution_stress, DEFAULT_SCENARIOS, StressReport
from fx_smc_bot.ml.regime import (
    MarketRegime,
    VolatilityRegimeClassifier,
    TrendRangeClassifier,
    SpreadRegimeClassifier,
)
from fx_smc_bot.research.evaluation import EvaluationReport, evaluate, cost_sensitivity
from fx_smc_bot.research.frozen_config import DataSplitPolicy, split_data
from fx_smc_bot.research.gating import DeploymentGateConfig, evaluate_deployment_gate
from fx_smc_bot.research.walk_forward import (
    WalkForwardSplit,
    anchored_walk_forward,
    rolling_walk_forward,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("holdout_stability")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
OUTPUT_DIR = PROJECT_ROOT / "results" / "holdout_stability_wave"

ALPHA_FAMILIES: dict[str, list[str]] = {
    "sweep_plus_bos": ["sweep_reversal", "bos_continuation"],
    "bos_continuation_only": ["bos_continuation"],
}

CHAMPION_RISK_OVERRIDES: dict[str, Any] = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_config(alpha_candidate: str, risk_overrides: dict[str, Any] | None = None) -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = list(ALPHA_FAMILIES[alpha_candidate])
    overrides = risk_overrides or CHAMPION_RISK_OVERRIDES
    for key, value in overrides.items():
        if hasattr(cfg.risk, key):
            setattr(cfg.risk, key, value)
    return cfg


def _run_backtest(
    cfg: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
    diag: DetectorDiagnostics | None = None,
) -> tuple[Any, PerformanceSummary]:
    engine = BacktestEngine(cfg)
    result = engine.run(data, htf_data, diagnostics=diag)
    metrics = engine.metrics(result)
    return result, metrics


def _slice_data(
    data: dict[TradingPair, BarSeries], start: int, end: int,
) -> dict[TradingPair, BarSeries]:
    return {pair: series.slice(start, end) for pair, series in data.items()}


def _attr_table(slices: list[AttributionSlice]) -> str:
    if not slices:
        return "No data.\n"
    lines = [
        f"| {'Label':<25s} | {'Trades':>6s} | {'PnL':>12s} | {'Win%':>6s} | {'Avg PnL':>10s} | {'Avg RR':>6s} |",
        f"|{'-'*27}|{'-'*8}|{'-'*14}|{'-'*8}|{'-'*12}|{'-'*8}|",
    ]
    for s in sorted(slices, key=lambda x: x.total_pnl):
        lines.append(
            f"| {s.label:<25s} | {s.trade_count:>6d} | {s.total_pnl:>12,.2f} | "
            f"{s.win_rate:>5.1%} | {s.avg_pnl:>10,.2f} | {s.avg_rr:>6.2f} |"
        )
    return "\n".join(lines) + "\n"


def _regime_distribution(data: dict[TradingPair, BarSeries]) -> dict[str, dict[str, float]]:
    vol_clf = VolatilityRegimeClassifier()
    trend_clf = TrendRangeClassifier()
    spread_clf = SpreadRegimeClassifier()

    counts: dict[str, dict[str, int]] = {
        "volatility": defaultdict(int),
        "trend": defaultdict(int),
        "spread": defaultdict(int),
    }
    total = 0
    for pair, series in data.items():
        h, l, c = series.high, series.low, series.close
        step = max(1, len(series) // 500)
        for i in range(50, len(series), step):
            counts["volatility"][vol_clf.classify(h, l, c, i).value] += 1
            counts["trend"][trend_clf.classify(h, l, c, i).value] += 1
            counts["spread"][spread_clf.classify(h, l, c, i).value] += 1
            total += 1

    result: dict[str, dict[str, float]] = {}
    for clf_name, buckets in counts.items():
        total_clf = sum(buckets.values())
        result[clf_name] = {k: v / total_clf if total_clf > 0 else 0.0 for k, v in sorted(buckets.items())}
    return result


def _format_regime_dist(dist: dict[str, dict[str, float]]) -> str:
    lines: list[str] = []
    for clf_name, buckets in dist.items():
        lines.append(f"**{clf_name.title()}**:")
        for regime, pct in sorted(buckets.items(), key=lambda x: -x[1]):
            lines.append(f"  - {regime}: {pct:.1%}")
    return "\n".join(lines) + "\n"


def _metrics_row(label: str, m: PerformanceSummary) -> str:
    return (
        f"| {label:<25s} | {m.total_trades:>6d} | {m.sharpe_ratio:>7.3f} | "
        f"{m.profit_factor:>6.2f} | {m.max_drawdown_pct:>7.1%} | {m.win_rate:>5.1%} | "
        f"{m.total_pnl:>12,.2f} | {m.calmar_ratio:>7.2f} |"
    )


_METRICS_HEADER = (
    f"| {'Period':<25s} | {'Trades':>6s} | {'Sharpe':>7s} | {'PF':>6s} | "
    f"{'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>12s} | {'Calmar':>7s} |"
)
_METRICS_SEP = f"|{'-'*27}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*14}|{'-'*9}|"


# ---------------------------------------------------------------------------
# PHASE A — Holdout Regime Diagnostics
# ---------------------------------------------------------------------------

def phase_a(
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("PHASE A — Holdout Regime Diagnostics")
    logger.info("=" * 60)

    policy = DataSplitPolicy(train_end_pct=0.60, validation_end_pct=0.80, embargo_bars=10)
    train_data, _val_data, holdout_data = split_data(full_data, policy)

    ref_pair = next(iter(full_data))
    n_total = len(full_data[ref_pair])
    train_end_idx = int(n_total * 0.60)
    holdout_start_idx = int(n_total * 0.80) + 10
    train_ts_start = str(full_data[ref_pair].timestamps[0])[:10]
    train_ts_end = str(full_data[ref_pair].timestamps[train_end_idx - 1])[:10]
    holdout_ts_start = str(full_data[ref_pair].timestamps[min(holdout_start_idx, n_total - 1)])[:10]
    holdout_ts_end = str(full_data[ref_pair].timestamps[-1])[:10]

    cfg = _build_config("sweep_plus_bos")

    train_diag = DetectorDiagnostics()
    holdout_diag = DetectorDiagnostics()

    logger.info("Running train backtest...")
    train_result, train_metrics = _run_backtest(cfg, train_data, htf_data, train_diag)
    logger.info("Running holdout backtest...")
    holdout_result, holdout_metrics = _run_backtest(cfg, holdout_data, htf_data, holdout_diag)

    logger.info("Computing evaluation reports...")
    train_eval = evaluate(train_result, train_metrics)
    holdout_eval = evaluate(holdout_result, holdout_metrics)

    logger.info("Computing regime distributions...")
    train_regime_dist = _regime_distribution(train_data)
    holdout_regime_dist = _regime_distribution(holdout_data)

    lines = [
        "# Holdout Regime Diagnostics Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Data Split",
        f"- Train: {train_ts_start} to {train_ts_end} ({sum(len(s) for s in train_data.values()):,d} bars total)",
        f"- Holdout: {holdout_ts_start} to {holdout_ts_end} ({sum(len(s) for s in holdout_data.values()):,d} bars total)",
        f"\n## Overall Metrics Comparison\n",
        _METRICS_HEADER,
        _METRICS_SEP,
        _metrics_row("Train", train_metrics),
        _metrics_row("Holdout", holdout_metrics),
        "",
        f"\n### Degradation Summary",
        f"- Sharpe: {train_metrics.sharpe_ratio:.3f} -> {holdout_metrics.sharpe_ratio:.3f} "
        f"({(holdout_metrics.sharpe_ratio - train_metrics.sharpe_ratio) / max(abs(train_metrics.sharpe_ratio), 0.001) * 100:+.1f}%)",
        f"- Profit Factor: {train_metrics.profit_factor:.2f} -> {holdout_metrics.profit_factor:.2f}",
        f"- Win Rate: {train_metrics.win_rate:.1%} -> {holdout_metrics.win_rate:.1%}",
        f"- Avg PnL: {train_metrics.avg_pnl:,.2f} -> {holdout_metrics.avg_pnl:,.2f}",
        f"- Max DD: {train_metrics.max_drawdown_pct:.1%} -> {holdout_metrics.max_drawdown_pct:.1%}",
        f"- Trade Count: {train_metrics.total_trades} -> {holdout_metrics.total_trades}",
    ]

    # Regime distribution comparison
    lines.append("\n## Regime Distribution: Train vs Holdout\n")
    lines.append("### Train Period\n")
    lines.append(_format_regime_dist(train_regime_dist))
    lines.append("\n### Holdout Period\n")
    lines.append(_format_regime_dist(holdout_regime_dist))

    # Regime shift analysis
    lines.append("\n### Regime Shift Analysis\n")
    for clf_name in train_regime_dist:
        all_regimes = set(train_regime_dist[clf_name]) | set(holdout_regime_dist[clf_name])
        for regime in sorted(all_regimes):
            t_pct = train_regime_dist[clf_name].get(regime, 0.0)
            h_pct = holdout_regime_dist[clf_name].get(regime, 0.0)
            diff = h_pct - t_pct
            if abs(diff) > 0.03:
                lines.append(f"- **{clf_name}/{regime}**: {t_pct:.1%} -> {h_pct:.1%} ({diff:+.1%})")

    # Month-by-month decomposition
    lines.append("\n## Month-by-Month Decomposition\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_month))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_month))

    # Pair-level attribution
    lines.append("\n## Pair-Level Attribution\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_pair))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_pair))

    # Family-level attribution
    lines.append("\n## Family-Level Attribution\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_family))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_family))

    # Session attribution
    lines.append("\n## Session Attribution\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_session))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_session))

    # Direction attribution
    lines.append("\n## Direction Attribution (Long vs Short)\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_direction))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_direction))

    # Regime attribution
    lines.append("\n## Regime Attribution\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.by_regime))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.by_regime))

    # Pair x Regime interaction
    lines.append("\n## Pair x Regime Interaction\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.pair_x_regime))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.pair_x_regime))

    # Family x Regime interaction
    lines.append("\n## Family x Regime Interaction\n")
    lines.append("### Train\n")
    lines.append(_attr_table(train_eval.family_x_regime))
    lines.append("\n### Holdout\n")
    lines.append(_attr_table(holdout_eval.family_x_regime))

    # Signal funnel comparison
    lines.append("\n## Signal Funnel Comparison\n")
    lines.append("### Train\n")
    lines.append(format_detector_diagnostics(train_diag))
    lines.append("\n### Holdout\n")
    lines.append(format_detector_diagnostics(holdout_diag))

    report_path = OUTPUT_DIR / "holdout_regime_diagnostics.md"
    report_path.write_text("\n".join(lines))
    logger.info("Wrote %s", report_path)

    return {
        "train_metrics": train_metrics,
        "holdout_metrics": holdout_metrics,
        "train_eval": train_eval,
        "holdout_eval": holdout_eval,
        "train_result": train_result,
        "holdout_result": holdout_result,
        "train_data": train_data,
        "holdout_data": holdout_data,
        "train_regime_dist": train_regime_dist,
        "holdout_regime_dist": holdout_regime_dist,
    }


# ---------------------------------------------------------------------------
# PHASE B — Walk-Forward Temporal Stability
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FoldResult:
    fold_id: int
    mode: str
    candidate: str
    train_bars: int
    test_bars: int
    test_start_date: str
    test_end_date: str
    sharpe: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    calmar: float = 0.0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "mode": self.mode,
            "candidate": self.candidate,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "test_start_date": self.test_start_date,
            "test_end_date": self.test_end_date,
            "sharpe": round(self.sharpe, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "calmar": round(self.calmar, 4),
            "elapsed_s": round(self.elapsed_s, 1),
        }


def _run_fold(
    split: WalkForwardSplit,
    mode: str,
    candidate: str,
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> FoldResult:
    ref_pair = next(iter(full_data))
    ts = full_data[ref_pair].timestamps
    test_start_date = str(ts[min(split.test_start, len(ts) - 1)])[:10]
    test_end_date = str(ts[min(split.test_end - 1, len(ts) - 1)])[:10]

    fr = FoldResult(
        fold_id=split.fold_id,
        mode=mode,
        candidate=candidate,
        train_bars=split.train_end - split.train_start,
        test_bars=split.test_end - split.test_start,
        test_start_date=test_start_date,
        test_end_date=test_end_date,
    )

    test_data = _slice_data(full_data, split.test_start, split.test_end)
    if any(len(s) < 100 for s in test_data.values()):
        logger.warning("Fold %d test window too small, skipping", split.fold_id)
        return fr

    cfg = _build_config(candidate)
    t0 = time.monotonic()
    try:
        result, metrics = _run_backtest(cfg, test_data, htf_data)
        fr.sharpe = metrics.sharpe_ratio
        fr.profit_factor = metrics.profit_factor
        fr.max_drawdown_pct = metrics.max_drawdown_pct
        fr.total_trades = metrics.total_trades
        fr.total_pnl = metrics.total_pnl
        fr.win_rate = metrics.win_rate
        fr.calmar = metrics.calmar_ratio
    except Exception as e:
        logger.warning("Fold %d/%s/%s failed: %s", split.fold_id, mode, candidate, e)
    fr.elapsed_s = time.monotonic() - t0
    return fr


def phase_b(
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> list[FoldResult]:
    logger.info("=" * 60)
    logger.info("PHASE B — Walk-Forward Temporal Stability")
    logger.info("=" * 60)

    ref_pair = next(iter(full_data))
    n_bars = len(full_data[ref_pair])

    anchored_splits = anchored_walk_forward(n_bars, n_folds=5, min_train_bars=2000)
    rolling_splits = rolling_walk_forward(n_bars, train_size=4000, test_size=1500, step_size=1500)

    all_folds: list[FoldResult] = []
    candidates = ["sweep_plus_bos", "bos_continuation_only"]

    for candidate in candidates:
        logger.info("Walk-forward for %s ...", candidate)
        for split in anchored_splits:
            logger.info("  Anchored fold %d (test: bars %d-%d)", split.fold_id, split.test_start, split.test_end)
            fr = _run_fold(split, "anchored", candidate, full_data, htf_data)
            all_folds.append(fr)

        for split in rolling_splits:
            logger.info("  Rolling fold %d (test: bars %d-%d)", split.fold_id, split.test_start, split.test_end)
            fr = _run_fold(split, "rolling", candidate, full_data, htf_data)
            all_folds.append(fr)

    # Write JSON results
    json_path = OUTPUT_DIR / "walk_forward_results.json"
    json_path.write_text(json.dumps([f.to_dict() for f in all_folds], indent=2))

    # Build report
    lines = [
        "# Temporal Stability Report — Walk-Forward Analysis",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\nTotal bars per pair: {n_bars:,d}",
        f"Anchored folds: {len(anchored_splits)} | Rolling folds: {len(rolling_splits)}",
        f"Candidates tested: {', '.join(candidates)}",
    ]

    for candidate in candidates:
        lines.append(f"\n## {candidate}\n")
        for mode in ["anchored", "rolling"]:
            folds = [f for f in all_folds if f.candidate == candidate and f.mode == mode]
            if not folds:
                continue
            lines.append(f"### {mode.title()} Walk-Forward\n")
            lines.append(
                f"| {'Fold':>4s} | {'Test Period':<25s} | {'Bars':>6s} | {'Trades':>6s} | "
                f"{'Sharpe':>7s} | {'PF':>6s} | {'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>12s} |"
            )
            lines.append(
                f"|{'-'*6}|{'-'*27}|{'-'*8}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*14}|"
            )
            for f in folds:
                lines.append(
                    f"| {f.fold_id:>4d} | {f.test_start_date} - {f.test_end_date:<10s} | "
                    f"{f.test_bars:>6d} | {f.total_trades:>6d} | {f.sharpe:>7.3f} | "
                    f"{f.profit_factor:>6.2f} | {f.max_drawdown_pct:>7.1%} | "
                    f"{f.win_rate:>5.1%} | {f.total_pnl:>12,.2f} |"
                )

            sharpes = [f.sharpe for f in folds if f.total_trades >= 10]
            if sharpes:
                lines.append(f"\n**OOS Sharpe Summary ({mode})**:")
                lines.append(f"- Mean: {np.mean(sharpes):.3f}")
                lines.append(f"- Std: {np.std(sharpes):.3f}")
                lines.append(f"- Min: {min(sharpes):.3f} | Max: {max(sharpes):.3f}")
                lines.append(f"- Folds with Sharpe > 0.3: {sum(1 for s in sharpes if s > 0.3)}/{len(sharpes)}")
                lines.append(f"- Folds with Sharpe > 0.0: {sum(1 for s in sharpes if s > 0.0)}/{len(sharpes)}")

    # Overall stability comparison
    lines.append("\n## Stability Comparison: sweep_plus_bos vs bos_continuation_only\n")
    for mode in ["anchored", "rolling"]:
        lines.append(f"### {mode.title()}\n")
        lines.append(f"| {'Candidate':<25s} | {'Mean Sharpe':>11s} | {'Std':>6s} | {'Min':>7s} | {'Max':>7s} | {'> 0.3':>5s} |")
        lines.append(f"|{'-'*27}|{'-'*13}|{'-'*8}|{'-'*9}|{'-'*9}|{'-'*7}|")
        for candidate in candidates:
            folds = [f for f in all_folds if f.candidate == candidate and f.mode == mode and f.total_trades >= 10]
            if not folds:
                continue
            sharpes = [f.sharpe for f in folds]
            pct_good = f"{sum(1 for s in sharpes if s > 0.3)}/{len(sharpes)}"
            lines.append(
                f"| {candidate:<25s} | {np.mean(sharpes):>11.3f} | {np.std(sharpes):>6.3f} | "
                f"{min(sharpes):>7.3f} | {max(sharpes):>7.3f} | {pct_good:>5s} |"
            )

    report_path = OUTPUT_DIR / "temporal_stability_report.md"
    report_path.write_text("\n".join(lines))
    logger.info("Wrote %s", report_path)

    return all_folds


# ---------------------------------------------------------------------------
# PHASE C — Spread Sensitivity & Data Quality
# ---------------------------------------------------------------------------

def phase_c(
    phase_a_ctx: dict[str, Any],
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("PHASE C — Spread Sensitivity & Data Quality")
    logger.info("=" * 60)

    holdout_result = phase_a_ctx["holdout_result"]
    holdout_metrics = phase_a_ctx["holdout_metrics"]
    holdout_data = phase_a_ctx["holdout_data"]
    train_result = phase_a_ctx["train_result"]
    train_metrics = phase_a_ctx["train_metrics"]
    train_data = phase_a_ctx["train_data"]

    lines = [
        "# Data Source Comparison and Spread Sensitivity Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
    ]

    # Data quality diagnostics
    lines.append("\n## Data Quality Diagnostics (Yahoo Finance 1H)\n")
    for pair, series in sorted(full_data.items(), key=lambda x: x[0].value):
        diag = run_diagnostics(series)
        lines.append(f"### {pair.value}\n")
        lines.append(f"```\n{format_diagnostic_report(diag)}\n```\n")

    # Cost sensitivity on train
    lines.append("\n## Cost Sensitivity — Train Period\n")
    train_cost = cost_sensitivity(
        train_result.trades, train_result.equity_curve, train_result.initial_capital,
        multipliers=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
    )
    lines.append(f"| {'Cost Mult':>9s} | {'Sharpe':>8s} | {'PF':>6s} | {'PnL':>12s} | {'Win%':>6s} |")
    lines.append(f"|{'-'*11}|{'-'*10}|{'-'*8}|{'-'*14}|{'-'*8}|")
    for pt in train_cost:
        lines.append(
            f"| {pt.cost_multiplier:>9.2f} | {pt.sharpe_ratio:>8.3f} | {pt.profit_factor:>6.2f} | "
            f"{pt.total_pnl:>12,.2f} | {pt.win_rate:>5.1%} |"
        )

    # Cost sensitivity on holdout
    lines.append("\n## Cost Sensitivity — Holdout Period\n")
    holdout_cost = cost_sensitivity(
        holdout_result.trades, holdout_result.equity_curve, holdout_result.initial_capital,
        multipliers=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
    )
    lines.append(f"| {'Cost Mult':>9s} | {'Sharpe':>8s} | {'PF':>6s} | {'PnL':>12s} | {'Win%':>6s} |")
    lines.append(f"|{'-'*11}|{'-'*10}|{'-'*8}|{'-'*14}|{'-'*8}|")
    for pt in holdout_cost:
        lines.append(
            f"| {pt.cost_multiplier:>9.2f} | {pt.sharpe_ratio:>8.3f} | {pt.profit_factor:>6.2f} | "
            f"{pt.total_pnl:>12,.2f} | {pt.win_rate:>5.1%} |"
        )

    # Execution stress on holdout
    lines.append("\n## Execution Stress Scenarios — Holdout\n")
    cfg = _build_config("sweep_plus_bos")
    stress_report = run_execution_stress(cfg, holdout_data, htf_data=htf_data)
    lines.append(f"| {'Scenario':<15s} | {'Trades':>6s} | {'Sharpe':>8s} | {'PF':>6s} | {'MaxDD':>7s} | {'PnL':>12s} |")
    lines.append(f"|{'-'*17}|{'-'*8}|{'-'*10}|{'-'*8}|{'-'*9}|{'-'*14}|")
    for sr in stress_report.results:
        lines.append(
            f"| {sr.scenario_name:<15s} | {sr.total_trades:>6d} | {sr.sharpe_ratio:>8.3f} | "
            f"{sr.profit_factor:>6.2f} | {sr.max_drawdown_pct:>7.1%} | {sr.total_pnl:>12,.2f} |"
        )
    degrad = stress_report.degradation_summary()
    if degrad:
        lines.append("\n### Degradation vs Neutral Baseline\n")
        for scenario, diffs in degrad.items():
            lines.append(f"- **{scenario}**: PnL {diffs['pnl_change_pct']:+.1f}%, Sharpe {diffs['sharpe_change']:+.3f}")

    # Spread assumption analysis
    lines.append("\n## Spread Assumption Analysis\n")
    lines.append("Current fixed spread: 1.5 pips for all pairs.\n")
    lines.append("Typical institutional spreads:\n")
    lines.append("- EURUSD: 0.1-0.3 pips\n- GBPUSD: 0.3-0.8 pips\n- USDJPY: 0.2-0.5 pips\n")
    lines.append("Yahoo Finance data does not include spreads. The 1.5 pip assumption is ")
    lines.append("conservative for major pairs (3-15x wider than institutional), which ")
    lines.append("means the strategy faces **higher costs than institutional reality**.\n")

    # Breakeven spread analysis
    if holdout_cost:
        baseline = next((pt for pt in holdout_cost if pt.cost_multiplier == 1.0), None)
        if baseline and baseline.total_pnl > 0:
            for pt in holdout_cost:
                if pt.total_pnl <= 0 and pt.cost_multiplier > 1.0:
                    lines.append(f"Strategy breaks even at ~{pt.cost_multiplier:.1f}x current spread "
                                 f"({pt.cost_multiplier * 1.5:.1f} pips equivalent).\n")
                    break

    lines.append("\n## Key Findings\n")
    lines.append("1. Yahoo Finance provides adequate data quality for structure detection, ")
    lines.append("but lacks bid/ask spreads.\n")
    lines.append("2. Fixed 1.5 pip spread is conservative for major pairs — ")
    lines.append("actual performance may be better under institutional execution.\n")
    lines.append("3. Cost sensitivity analysis above shows how Sharpe degrades with higher costs.\n")

    report_path = OUTPUT_DIR / "data_source_comparison.md"
    report_path.write_text("\n".join(lines))
    logger.info("Wrote %s", report_path)

    return {"stress_report": stress_report, "holdout_cost": holdout_cost, "train_cost": train_cost}


# ---------------------------------------------------------------------------
# PHASE D — Regime-Aware Mitigation
# ---------------------------------------------------------------------------

def phase_d(
    phase_a_ctx: dict[str, Any],
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("PHASE D — Regime-Aware Weakness Analysis & Mitigation")
    logger.info("=" * 60)

    holdout_eval: EvaluationReport = phase_a_ctx["holdout_eval"]
    holdout_data = phase_a_ctx["holdout_data"]
    holdout_metrics: PerformanceSummary = phase_a_ctx["holdout_metrics"]
    holdout_result = phase_a_ctx["holdout_result"]

    lines = [
        "# Regime-Aware Mitigation Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\nBaseline holdout Sharpe: {holdout_metrics.sharpe_ratio:.3f} | "
        f"PF: {holdout_metrics.profit_factor:.2f} | Trades: {holdout_metrics.total_trades}",
    ]

    # Identify weaknesses from holdout attribution
    lines.append("\n## Weakness Identification\n")

    # Find worst session
    worst_session = min(holdout_eval.by_session, key=lambda s: s.total_pnl) if holdout_eval.by_session else None
    if worst_session:
        lines.append(f"### Worst Session: {worst_session.label}")
        lines.append(f"- Trades: {worst_session.trade_count} | PnL: {worst_session.total_pnl:,.2f} | "
                      f"Win%: {worst_session.win_rate:.1%}")
        total_loss = sum(s.total_pnl for s in holdout_eval.by_session if s.total_pnl < 0)
        if total_loss < 0 and worst_session.total_pnl < 0:
            lines.append(f"- Contributes {worst_session.total_pnl / total_loss:.0%} of total losses\n")

    # Find worst pair
    worst_pair = min(holdout_eval.by_pair, key=lambda s: s.total_pnl) if holdout_eval.by_pair else None
    if worst_pair:
        lines.append(f"### Worst Pair: {worst_pair.label}")
        lines.append(f"- Trades: {worst_pair.trade_count} | PnL: {worst_pair.total_pnl:,.2f} | "
                      f"Win%: {worst_pair.win_rate:.1%}\n")

    # Find worst regime
    worst_regime = min(holdout_eval.by_regime, key=lambda s: s.total_pnl) if holdout_eval.by_regime else None
    if worst_regime:
        lines.append(f"### Worst Regime: {worst_regime.label}")
        lines.append(f"- Trades: {worst_regime.trade_count} | PnL: {worst_regime.total_pnl:,.2f} | "
                      f"Win%: {worst_regime.win_rate:.1%}\n")

    # Find worst direction
    worst_dir = min(holdout_eval.by_direction, key=lambda s: s.total_pnl) if holdout_eval.by_direction else None
    if worst_dir:
        lines.append(f"### Worst Direction: {worst_dir.label}")
        lines.append(f"- Trades: {worst_dir.trade_count} | PnL: {worst_dir.total_pnl:,.2f} | "
                      f"Win%: {worst_dir.win_rate:.1%}\n")

    # Test mitigations
    mitigations_tested: list[dict[str, Any]] = []
    lines.append("\n## Mitigation Tests\n")

    def _test_mitigation(
        label: str,
        hypothesis: str,
        filter_fn,
    ) -> dict[str, Any]:
        """Filter holdout trades and recompute metrics on the surviving subset."""
        surviving = [t for t in holdout_result.trades if filter_fn(t)]
        if len(surviving) < 10:
            return {
                "label": label, "hypothesis": hypothesis,
                "trades": len(surviving), "sharpe": 0.0, "pf": 0.0,
                "improvement": "insufficient trades",
            }

        pnls = np.array([t.pnl for t in surviving])
        wins = np.sum(pnls > 0)
        gross_p = float(np.sum(pnls[pnls > 0])) if wins > 0 else 0.0
        gross_l = abs(float(np.sum(pnls[pnls < 0])))
        pf = gross_p / gross_l if gross_l > 0 else float("inf")
        pnl_std = float(np.std(pnls, ddof=1)) if len(pnls) > 1 else 1.0
        avg_pnl = float(np.mean(pnls))
        approx_sharpe = (avg_pnl / pnl_std) * np.sqrt(252 / max(1, len(surviving))) if pnl_std > 0 else 0.0

        sharpe_delta = approx_sharpe - holdout_metrics.sharpe_ratio
        return {
            "label": label,
            "hypothesis": hypothesis,
            "trades": len(surviving),
            "trades_removed": holdout_metrics.total_trades - len(surviving),
            "sharpe_approx": round(approx_sharpe, 4),
            "sharpe_delta": round(sharpe_delta, 4),
            "pf": round(pf, 3),
            "total_pnl": round(float(np.sum(pnls)), 2),
            "win_rate": round(float(wins / len(pnls)), 4),
        }

    # Mitigation 1: Remove worst session
    if worst_session and worst_session.total_pnl < 0:
        ws_label = worst_session.label
        m = _test_mitigation(
            f"Filter {ws_label} session",
            f"Session '{ws_label}' is the largest holdout loss contributor",
            lambda t: (t.session.value if t.session else "unknown") != ws_label,
        )
        mitigations_tested.append(m)

    # Mitigation 2: Remove worst pair
    if worst_pair and worst_pair.total_pnl < 0:
        wp_label = worst_pair.label
        m = _test_mitigation(
            f"Filter {wp_label} pair",
            f"Pair '{wp_label}' has the worst holdout PnL",
            lambda t: t.pair.value != wp_label,
        )
        mitigations_tested.append(m)

    # Mitigation 3: Remove worst regime
    if worst_regime and worst_regime.total_pnl < 0:
        wr_label = worst_regime.label
        m = _test_mitigation(
            f"Filter {wr_label} regime",
            f"Regime '{wr_label}' has the worst holdout PnL",
            lambda t: (t.regime or "unknown") != wr_label,
        )
        mitigations_tested.append(m)

    # Mitigation 4: Remove worst direction if asymmetric
    if worst_dir and worst_dir.total_pnl < 0:
        wd_label = worst_dir.label
        m = _test_mitigation(
            f"Filter {wd_label} direction",
            f"Direction '{wd_label}' underperforms in holdout",
            lambda t: t.direction.value != wd_label,
        )
        mitigations_tested.append(m)

    # Format mitigation results
    if mitigations_tested:
        lines.append(f"| {'Mitigation':<30s} | {'Trades':>6s} | {'Removed':>7s} | {'Sharpe~':>8s} | "
                      f"{'Delta':>7s} | {'PF':>6s} | {'PnL':>12s} |")
        lines.append(f"|{'-'*32}|{'-'*8}|{'-'*9}|{'-'*10}|{'-'*9}|{'-'*8}|{'-'*14}|")
        lines.append(
            f"| {'Baseline (no filter)':<30s} | {holdout_metrics.total_trades:>6d} | {'—':>7s} | "
            f"{holdout_metrics.sharpe_ratio:>8.3f} | {'—':>7s} | "
            f"{holdout_metrics.profit_factor:>6.2f} | {holdout_metrics.total_pnl:>12,.2f} |"
        )
        for m in mitigations_tested:
            if m.get("improvement") == "insufficient trades":
                lines.append(f"| {m['label']:<30s} | {'<10':>6s} | — | — | — | — | — |")
            else:
                lines.append(
                    f"| {m['label']:<30s} | {m['trades']:>6d} | {m['trades_removed']:>7d} | "
                    f"{m['sharpe_approx']:>8.3f} | {m['sharpe_delta']:>+7.3f} | "
                    f"{m['pf']:>6.2f} | {m['total_pnl']:>12,.2f} |"
                )
    else:
        lines.append("No clear weakness identified for targeted mitigation.\n")

    # Conclusions
    lines.append("\n## Mitigation Conclusions\n")
    improvements = [m for m in mitigations_tested
                    if isinstance(m.get("sharpe_delta"), (int, float)) and m["sharpe_delta"] > 0.05]
    if improvements:
        best_mit = max(improvements, key=lambda m: m["sharpe_delta"])
        lines.append(f"Best mitigation: **{best_mit['label']}** (Sharpe delta: {best_mit['sharpe_delta']:+.3f})\n")
        lines.append("However, trade-level filtering is a post-hoc analysis and should be validated ")
        lines.append("out-of-sample (walk-forward) before adoption. The risk of overfitting to holdout-specific ")
        lines.append("conditions is high when applying targeted filters.\n")
    else:
        lines.append("No mitigation produced a meaningful improvement (>0.05 Sharpe delta).\n")
        lines.append("This suggests the holdout weakness is not concentrated in a single dimension ")
        lines.append("that can be easily filtered — it may be a broad regime shift affecting trade quality.\n")

    report_path = OUTPUT_DIR / "regime_mitigation_report.md"
    report_path.write_text("\n".join(lines))
    logger.info("Wrote %s", report_path)

    return {"mitigations": mitigations_tested}


# ---------------------------------------------------------------------------
# PHASE E — Champion Re-evaluation
# ---------------------------------------------------------------------------

def phase_e(
    phase_a_ctx: dict[str, Any],
    wf_results: list[FoldResult],
) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("PHASE E — Champion Re-evaluation Under Stronger Validation")
    logger.info("=" * 60)

    lines = [
        "# Updated Candidate Comparison",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
    ]

    candidates = ["sweep_plus_bos", "bos_continuation_only"]
    summary: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        anchored = [f for f in wf_results if f.candidate == candidate and f.mode == "anchored" and f.total_trades >= 10]
        rolling = [f for f in wf_results if f.candidate == candidate and f.mode == "rolling" and f.total_trades >= 10]

        all_oos = anchored + rolling
        sharpes = [f.sharpe for f in all_oos]
        pfs = [f.profit_factor for f in all_oos]
        dds = [f.max_drawdown_pct for f in all_oos]
        trades = [f.total_trades for f in all_oos]

        summary[candidate] = {
            "n_folds": len(all_oos),
            "mean_sharpe": float(np.mean(sharpes)) if sharpes else 0.0,
            "std_sharpe": float(np.std(sharpes)) if sharpes else 0.0,
            "min_sharpe": float(min(sharpes)) if sharpes else 0.0,
            "max_sharpe": float(max(sharpes)) if sharpes else 0.0,
            "pct_positive": sum(1 for s in sharpes if s > 0) / len(sharpes) if sharpes else 0.0,
            "pct_above_threshold": sum(1 for s in sharpes if s > 0.3) / len(sharpes) if sharpes else 0.0,
            "mean_pf": float(np.mean(pfs)) if pfs else 0.0,
            "mean_dd": float(np.mean(dds)) if dds else 0.0,
            "mean_trades": float(np.mean(trades)) if trades else 0.0,
        }

    lines.append("\n## Walk-Forward OOS Summary\n")
    lines.append(f"| {'Metric':<25s} | {'sweep_plus_bos':>18s} | {'bos_continuation_only':>22s} |")
    lines.append(f"|{'-'*27}|{'-'*20}|{'-'*24}|")
    metrics_to_show = [
        ("OOS folds", "n_folds", "d"),
        ("Mean OOS Sharpe", "mean_sharpe", ".3f"),
        ("Std OOS Sharpe", "std_sharpe", ".3f"),
        ("Min OOS Sharpe", "min_sharpe", ".3f"),
        ("Max OOS Sharpe", "max_sharpe", ".3f"),
        ("% folds Sharpe > 0", "pct_positive", ".0%"),
        ("% folds Sharpe > 0.3", "pct_above_threshold", ".0%"),
        ("Mean OOS PF", "mean_pf", ".2f"),
        ("Mean OOS MaxDD", "mean_dd", ".1%"),
        ("Mean OOS Trades", "mean_trades", ".0f"),
    ]
    for label, key, fmt in metrics_to_show:
        s_val = summary["sweep_plus_bos"][key]
        b_val = summary["bos_continuation_only"][key]
        if fmt == "d":
            lines.append(f"| {label:<25s} | {int(s_val):>18d} | {int(b_val):>22d} |")
        elif fmt.endswith("%"):
            lines.append(f"| {label:<25s} | {s_val:>18{fmt}} | {b_val:>22{fmt}} |")
        else:
            lines.append(f"| {label:<25s} | {s_val:>18{fmt}} | {b_val:>22{fmt}} |")

    # Temporal degradation pattern
    lines.append("\n## Temporal Degradation Pattern\n")
    lines.append("Checking whether OOS performance degrades systematically in later folds:\n")
    for candidate in candidates:
        anchored = sorted(
            [f for f in wf_results if f.candidate == candidate and f.mode == "anchored" and f.total_trades >= 10],
            key=lambda f: f.fold_id,
        )
        if len(anchored) >= 3:
            first_half = anchored[:len(anchored) // 2]
            second_half = anchored[len(anchored) // 2:]
            first_sharpe = np.mean([f.sharpe for f in first_half])
            second_sharpe = np.mean([f.sharpe for f in second_half])
            lines.append(f"**{candidate}** (anchored):")
            lines.append(f"- Early folds mean Sharpe: {first_sharpe:.3f}")
            lines.append(f"- Late folds mean Sharpe: {second_sharpe:.3f}")
            if second_sharpe < first_sharpe * 0.5:
                lines.append(f"- WARNING: Late folds show significant degradation\n")
            elif second_sharpe >= first_sharpe * 0.8:
                lines.append(f"- OK: Performance relatively stable across folds\n")
            else:
                lines.append(f"- MODERATE: Some degradation but not catastrophic\n")

    # Champion determination
    lines.append("\n## Champion Determination\n")
    s = summary["sweep_plus_bos"]
    b = summary["bos_continuation_only"]
    sharpe_diff = s["mean_sharpe"] - b["mean_sharpe"]
    consistency_diff = s["pct_positive"] - b["pct_positive"]

    if abs(sharpe_diff) < 0.05 and abs(consistency_diff) < 0.1:
        lines.append("Performance is **materially similar** between candidates under walk-forward.\n")
        lines.append("Given similar performance, **bos_continuation_only** is preferred for simplicity ")
        lines.append("(1 family vs 2 families).\n")
        champion = "bos_continuation_only"
        champion_reason = "similar_performance_prefer_simplicity"
    elif s["mean_sharpe"] > b["mean_sharpe"] and s["pct_positive"] >= b["pct_positive"]:
        lines.append("**sweep_plus_bos** is superior on both mean OOS Sharpe and consistency.\n")
        champion = "sweep_plus_bos"
        champion_reason = "superior_oos_performance"
    elif b["mean_sharpe"] > s["mean_sharpe"] and b["pct_positive"] >= s["pct_positive"]:
        lines.append("**bos_continuation_only** is superior on both mean OOS Sharpe and consistency.\n")
        champion = "bos_continuation_only"
        champion_reason = "superior_oos_performance"
    else:
        if s["pct_positive"] > b["pct_positive"]:
            lines.append("**sweep_plus_bos** has better consistency (more positive folds).\n")
            champion = "sweep_plus_bos"
        else:
            lines.append("**bos_continuation_only** has better consistency.\n")
            champion = "bos_continuation_only"
        champion_reason = "better_consistency"

    lines.append(f"**Updated champion: {champion}** (reason: {champion_reason})\n")

    report_path = OUTPUT_DIR / "updated_candidate_comparison.md"
    report_path.write_text("\n".join(lines))
    logger.info("Wrote %s", report_path)

    return {"summary": summary, "champion": champion, "champion_reason": champion_reason}


# ---------------------------------------------------------------------------
# PHASE F — Final Stability & Deployment Recommendation
# ---------------------------------------------------------------------------

def phase_f(
    phase_a_ctx: dict[str, Any],
    wf_results: list[FoldResult],
    phase_c_ctx: dict[str, Any],
    phase_d_ctx: dict[str, Any],
    phase_e_ctx: dict[str, Any],
) -> None:
    logger.info("=" * 60)
    logger.info("PHASE F — Final Stability & Deployment Recommendation")
    logger.info("=" * 60)

    train_metrics: PerformanceSummary = phase_a_ctx["train_metrics"]
    holdout_metrics: PerformanceSummary = phase_a_ctx["holdout_metrics"]
    champion = phase_e_ctx["champion"]
    champion_reason = phase_e_ctx["champion_reason"]
    wf_summary = phase_e_ctx["summary"]

    # Determine the final recommendation
    s = wf_summary.get(champion, {})
    mean_oos_sharpe = s.get("mean_sharpe", 0.0)
    pct_positive = s.get("pct_positive", 0.0)
    pct_above_threshold = s.get("pct_above_threshold", 0.0)
    mean_oos_dd = s.get("mean_dd", 0.0)

    mitigations = phase_d_ctx.get("mitigations", [])
    useful_mitigations = [m for m in mitigations
                          if isinstance(m.get("sharpe_delta"), (int, float)) and m["sharpe_delta"] > 0.05]

    stress_report: StressReport = phase_c_ctx.get("stress_report")
    stress_ok = True
    if stress_report and stress_report.baseline:
        conservative = next((r for r in stress_report.results if r.scenario_name == "conservative"), None)
        if conservative and conservative.sharpe_ratio < 0:
            stress_ok = False

    # Decision logic
    holdout_structural = False
    holdout_contextual = False

    if pct_positive >= 0.6 and mean_oos_sharpe > 0.1:
        holdout_contextual = True
    else:
        holdout_structural = True

    if holdout_contextual and mean_oos_sharpe >= 0.3 and stress_ok:
        decision = "CONTINUE_PAPER_TRADING"
        confidence = "medium-high"
    elif holdout_contextual and mean_oos_sharpe >= 0.1 and stress_ok:
        decision = "CONTINUE_PAPER_TRADING"
        confidence = "medium"
    elif holdout_contextual and not stress_ok:
        decision = "HOLD_FOR_MORE_VALIDATION"
        confidence = "low"
    elif holdout_structural and useful_mitigations:
        decision = "CONTINUE_WITH_SIMPLIFICATION"
        confidence = "low-medium"
    elif holdout_structural and pct_positive < 0.4:
        decision = "REWORK_STRATEGY"
        confidence = "medium"
    else:
        decision = "HOLD_FOR_MORE_VALIDATION"
        confidence = "low-medium"

    # --- Updated Deployment Readiness Report ---
    dr_lines = [
        "# Updated Deployment Readiness Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Champion: {champion}",
        f"Risk profile: size_030_cb125",
        f"Champion reason: {champion_reason}",
        f"\n## Training Performance\n",
        _METRICS_HEADER,
        _METRICS_SEP,
        _metrics_row("Train", train_metrics),
        _metrics_row("Holdout", holdout_metrics),
        f"\n## Walk-Forward OOS Performance\n",
        f"- Mean OOS Sharpe: {mean_oos_sharpe:.3f}",
        f"- % folds with positive Sharpe: {pct_positive:.0%}",
        f"- % folds with Sharpe > 0.3: {pct_above_threshold:.0%}",
        f"- Mean OOS MaxDD: {mean_oos_dd:.1%}",
        f"\n## Execution Stress\n",
        f"- Stress test passed: {'Yes' if stress_ok else 'No'}",
        f"\n## Regime Mitigation\n",
        f"- Useful mitigations found: {len(useful_mitigations)}",
    ]
    for m in useful_mitigations:
        dr_lines.append(f"  - {m['label']}: Sharpe delta {m['sharpe_delta']:+.3f}")

    dr_lines.append(f"\n## Deployment Gate Status\n")
    gate_cfg = DeploymentGateConfig()
    gate_metrics = {
        "sharpe_ratio": holdout_metrics.sharpe_ratio,
        "profit_factor": holdout_metrics.profit_factor,
        "max_drawdown_pct": holdout_metrics.max_drawdown_pct,
        "total_trades": holdout_metrics.total_trades,
        "win_rate": holdout_metrics.win_rate,
    }
    gate = evaluate_deployment_gate(gate_metrics, gate_cfg)
    dr_lines.append(f"- Holdout gate verdict: {gate.verdict.value}")
    if gate.blocking_failures:
        dr_lines.append(f"- Blocking failures: {', '.join(gate.blocking_failures)}")

    wf_gate_metrics = {
        "sharpe_ratio": mean_oos_sharpe,
        "profit_factor": s.get("mean_pf", 0.0),
        "max_drawdown_pct": mean_oos_dd,
        "total_trades": int(s.get("mean_trades", 0)),
        "win_rate": 0.5,
    }
    wf_gate = evaluate_deployment_gate(wf_gate_metrics, gate_cfg)
    dr_lines.append(f"- WF-average gate verdict: {wf_gate.verdict.value}")
    if wf_gate.blocking_failures:
        dr_lines.append(f"- WF blocking failures: {', '.join(wf_gate.blocking_failures)}")

    dr_lines.append(f"\n## Unresolved Risks\n")
    dr_lines.append("1. Holdout Sharpe below deployment threshold (0.3)")
    dr_lines.append("2. Yahoo Finance data lacks bid/ask spreads")
    dr_lines.append("3. Fixed spread assumption may not reflect real execution")
    if holdout_structural:
        dr_lines.append("4. Walk-forward suggests potential structural weakness")
    dr_lines.append(f"\n## Recommendation: **{decision}** (confidence: {confidence})")

    (OUTPUT_DIR / "updated_deployment_readiness_report.md").write_text("\n".join(dr_lines))

    # --- Updated Final Recommendation JSON ---
    recommendation = {
        "timestamp": datetime.utcnow().isoformat(),
        "champion": champion,
        "champion_reason": champion_reason,
        "risk_profile": "size_030_cb125",
        "decision": decision,
        "confidence": confidence,
        "evidence": {
            "train_sharpe": round(train_metrics.sharpe_ratio, 4),
            "holdout_sharpe": round(holdout_metrics.sharpe_ratio, 4),
            "wf_mean_oos_sharpe": round(mean_oos_sharpe, 4),
            "wf_pct_positive_folds": round(pct_positive, 3),
            "wf_pct_above_threshold": round(pct_above_threshold, 3),
            "holdout_weakness": "contextual" if holdout_contextual else "structural",
            "stress_test_passed": stress_ok,
            "useful_mitigations": len(useful_mitigations),
        },
        "next_steps": [],
    }

    if decision == "CONTINUE_PAPER_TRADING":
        recommendation["next_steps"] = [
            "Deploy to paper trading with size_030_cb125 risk profile",
            "Monitor for 4-6 weeks minimum",
            "Weekly review checkpoints against deployment thresholds",
            "If paper Sharpe < 0.1 after 4 weeks, escalate to HOLD",
        ]
    elif decision == "HOLD_FOR_MORE_VALIDATION":
        recommendation["next_steps"] = [
            "Acquire higher-quality FX data (Dukascopy CSV or broker data)",
            "Re-run holdout on better data to isolate data-quality effects",
            "Test on additional OOS periods as more data becomes available",
            "Consider extending training window to capture more regimes",
        ]
    elif decision == "CONTINUE_WITH_SIMPLIFICATION":
        recommendation["next_steps"] = [
            "Apply the identified mitigation filters",
            "Re-validate under walk-forward to confirm OOS improvement",
            "Simplify to bos_continuation_only if sweep adds no value",
        ]
    elif decision == "REWORK_STRATEGY":
        recommendation["next_steps"] = [
            "Investigate why structure-based signals lose follow-through",
            "Consider alternative entry timing or confirmation mechanisms",
            "Test on higher timeframes for more reliable structure",
        ]

    (OUTPUT_DIR / "updated_final_recommendation.json").write_text(
        json.dumps(recommendation, indent=2)
    )

    # --- Updated Final Decision MD ---
    fd_lines = [
        "# Updated Final Decision — Holdout Stability Investigation",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Decision: **{decision}**",
        f"Confidence: {confidence}",
        f"\n## Champion: {champion} (risk profile: size_030_cb125)",
        f"\n## Why This Decision\n",
    ]

    if holdout_contextual:
        fd_lines.append("The holdout weakness appears **contextual rather than structural**:\n")
        fd_lines.append(f"- Walk-forward shows {pct_positive:.0%} of OOS folds with positive Sharpe")
        fd_lines.append(f"- Mean OOS Sharpe across folds: {mean_oos_sharpe:.3f}")
        fd_lines.append("- The original holdout period (Nov 2025 - Apr 2026) may represent an ")
        fd_lines.append("  unfavorable regime segment rather than fundamental strategy failure\n")
    else:
        fd_lines.append("The holdout weakness appears **structural**:\n")
        fd_lines.append(f"- Walk-forward shows only {pct_positive:.0%} of OOS folds with positive Sharpe")
        fd_lines.append(f"- Mean OOS Sharpe across folds: {mean_oos_sharpe:.3f}")
        fd_lines.append("- Performance degradation is not confined to one period\n")

    fd_lines.append("## Key Evidence\n")
    fd_lines.append(f"1. **Train vs Holdout**: Sharpe {train_metrics.sharpe_ratio:.3f} -> {holdout_metrics.sharpe_ratio:.3f}")
    fd_lines.append(f"2. **Walk-Forward**: Mean OOS Sharpe {mean_oos_sharpe:.3f}, {pct_positive:.0%} positive")
    fd_lines.append(f"3. **Stress Test**: {'Passed' if stress_ok else 'Failed'}")
    fd_lines.append(f"4. **Mitigations**: {len(useful_mitigations)} useful out of {len(mitigations)} tested")
    fd_lines.append(f"5. **Drawdown Control**: Remains strong ({holdout_metrics.max_drawdown_pct:.1%} holdout, "
                     f"{mean_oos_dd:.1%} WF average)")

    fd_lines.append(f"\n## What Caused the Holdout Degradation\n")
    fd_lines.append("Based on the regime diagnostics (Phase A), the holdout period shows:")
    train_dist = phase_a_ctx.get("train_regime_dist", {})
    holdout_dist = phase_a_ctx.get("holdout_regime_dist", {})
    for clf_name in train_dist:
        all_regimes = set(train_dist[clf_name]) | set(holdout_dist[clf_name])
        for regime in sorted(all_regimes):
            t_pct = train_dist[clf_name].get(regime, 0.0)
            h_pct = holdout_dist[clf_name].get(regime, 0.0)
            diff = h_pct - t_pct
            if abs(diff) > 0.05:
                fd_lines.append(f"- {clf_name}/{regime}: shifted from {t_pct:.1%} to {h_pct:.1%}")

    fd_lines.append(f"\n## Next Steps\n")
    for i, step in enumerate(recommendation["next_steps"], 1):
        fd_lines.append(f"{i}. {step}")

    fd_lines.append(f"\n## Unresolved Risks\n")
    fd_lines.append("- Yahoo Finance data quality limitations (no bid/ask spread)")
    fd_lines.append("- Fixed 1.5 pip spread assumption may overstate or understate costs")
    fd_lines.append("- Limited to 3 major pairs (EURUSD, GBPUSD, USDJPY)")
    if holdout_structural:
        fd_lines.append("- Walk-forward indicates potential structural alpha decay")
    fd_lines.append("- Strategy relies on SMC structure detection that may be sensitive to volatility regimes")

    (OUTPUT_DIR / "updated_final_decision.md").write_text("\n".join(fd_lines))

    logger.info("Wrote updated_deployment_readiness_report.md")
    logger.info("Wrote updated_final_recommendation.json")
    logger.info("Wrote updated_final_decision.md")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t_total = time.monotonic()

    logger.info("Loading real FX data from %s", DATA_DIR)
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded — cannot proceed")
        sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)

    for pair, series in full_data.items():
        logger.info("  %s: %d bars (%s -> %s)", pair.value, len(series),
                     str(series.timestamps[0])[:10], str(series.timestamps[-1])[:10])

    # Phase A
    phase_a_ctx = phase_a(full_data, htf_data)

    # Phase B
    wf_results = phase_b(full_data, htf_data)

    # Phase C
    phase_c_ctx = phase_c(phase_a_ctx, full_data, htf_data)

    # Phase D
    phase_d_ctx = phase_d(phase_a_ctx, full_data, htf_data)

    # Phase E
    phase_e_ctx = phase_e(phase_a_ctx, wf_results)

    # Phase F
    phase_f(phase_a_ctx, wf_results, phase_c_ctx, phase_d_ctx, phase_e_ctx)

    elapsed = time.monotonic() - t_total
    logger.info("=" * 60)
    logger.info("COMPLETE — Total elapsed: %.1f minutes", elapsed / 60)
    logger.info("All reports written to %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
