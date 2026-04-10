"""Experiment campaign orchestration: config sweeps, baseline-vs-SMC,
walk-forward, and ablation campaigns with aggregate reporting.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult
from fx_smc_bot.research.ablation import (
    AblationResult,
    run_family_ablation,
    run_filter_ablation,
    run_scoring_ablation,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CampaignRunResult:
    name: str
    metrics: dict[str, float] = field(default_factory=dict)
    trade_count: int = 0
    config_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CampaignReport:
    campaign_type: str
    timestamp: str = ""
    runs: list[CampaignRunResult] = field(default_factory=list)
    aggregate: dict[str, Any] = field(default_factory=dict)

    def summary_table(self) -> str:
        lines = [
            f"Campaign: {self.campaign_type}  ({len(self.runs)} runs)",
            f"{'Name':<35s}  {'Trades':>7s}  {'Sharpe':>8s}  {'PF':>7s}  {'WinRate':>8s}  {'PnL':>12s}",
            "-" * 83,
        ]
        for r in self.runs:
            m = r.metrics
            lines.append(
                f"{r.name:<35s}  {r.trade_count:>7d}  "
                f"{m.get('sharpe_ratio', 0):>8.3f}  "
                f"{m.get('profit_factor', 0):>7.2f}  "
                f"{m.get('win_rate', 0):>8.1%}  "
                f"{m.get('total_pnl', 0):>12,.2f}"
            )
        return "\n".join(lines)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)


def _run_single(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
    name: str,
    overrides: dict[str, Any],
) -> CampaignRunResult:
    cfg = config.model_copy(deep=True)
    for dotted_key, value in overrides.items():
        parts = dotted_key.split(".")
        obj = cfg
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], value)

    try:
        engine = BacktestEngine(cfg)
        result = engine.run(data, htf_data)
        metrics = engine.metrics(result)
        return CampaignRunResult(
            name=name,
            metrics={
                "sharpe_ratio": metrics.sharpe_ratio,
                "profit_factor": metrics.profit_factor,
                "win_rate": metrics.win_rate,
                "total_pnl": metrics.total_pnl,
                "max_drawdown": metrics.max_drawdown,
                "total_trades": metrics.total_trades,
            },
            trade_count=metrics.total_trades,
            config_overrides=overrides,
        )
    except Exception as e:
        logger.warning("Campaign run '%s' failed: %s", name, e)
        return CampaignRunResult(name=name, config_overrides=overrides)


def run_config_sweep(
    base_config: AppConfig,
    data: dict[TradingPair, BarSeries],
    overrides_list: list[dict[str, Any]],
    htf_data: dict[TradingPair, BarSeries] | None = None,
    campaign_name: str = "config_sweep",
) -> CampaignReport:
    """Run a parameter grid sweep."""
    report = CampaignReport(
        campaign_type=campaign_name,
        timestamp=datetime.utcnow().isoformat(),
    )
    for i, overrides in enumerate(overrides_list):
        name = f"variant_{i:03d}"
        for k, v in overrides.items():
            name += f"_{k.split('.')[-1]}={v}"
        result = _run_single(base_config, data, htf_data, name, overrides)
        report.runs.append(result)
        logger.info("Sweep %d/%d: %s", i + 1, len(overrides_list), name)

    _compute_aggregate(report)
    return report


def run_baseline_vs_smc(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> CampaignReport:
    """Compare baseline strategies vs full SMC stack and individual SMC families."""
    report = CampaignReport(
        campaign_type="baseline_vs_smc",
        timestamp=datetime.utcnow().isoformat(),
    )

    configs = [
        ("full_smc", {"alpha.enabled_families": ["sweep_reversal", "bos_continuation", "fvg_retrace"]}),
        ("momentum_only", {"alpha.enabled_families": ["momentum"]}),
        ("session_breakout_only", {"alpha.enabled_families": ["session_breakout"]}),
        ("mean_reversion_only", {"alpha.enabled_families": ["mean_reversion"]}),
        ("sweep_reversal_only", {"alpha.enabled_families": ["sweep_reversal"]}),
        ("bos_continuation_only", {"alpha.enabled_families": ["bos_continuation"]}),
        ("fvg_retrace_only", {"alpha.enabled_families": ["fvg_retrace"]}),
    ]

    for name, overrides in configs:
        result = _run_single(config, data, htf_data, name, overrides)
        report.runs.append(result)
        logger.info("Baseline vs SMC: %s complete", name)

    _compute_aggregate(report)
    return report


def run_walk_forward_campaign(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    n_splits: int = 5,
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> CampaignReport:
    """Run walk-forward splits with per-fold metrics."""
    report = CampaignReport(
        campaign_type="walk_forward",
        timestamp=datetime.utcnow().isoformat(),
    )

    ref_pair = next(iter(data))
    total_bars = len(data[ref_pair].timestamps)
    fold_size = total_bars // (n_splits + 1)

    for fold in range(n_splits):
        train_end = fold_size * (fold + 2)
        test_start = train_end
        test_end = min(test_start + fold_size, total_bars)

        if test_start >= total_bars or test_end <= test_start:
            continue

        fold_data = {}
        for pair, series in data.items():
            fold_data[pair] = series.slice(test_start, test_end)

        result = _run_single(config, fold_data, htf_data, f"fold_{fold}", {})
        report.runs.append(result)
        logger.info("Walk-forward fold %d/%d complete", fold + 1, n_splits)

    _compute_aggregate(report)
    return report


def _compute_aggregate(report: CampaignReport) -> None:
    """Compute aggregate statistics across campaign runs."""
    valid = [r for r in report.runs if r.metrics]
    if not valid:
        return

    sharpes = [r.metrics.get("sharpe_ratio", 0) for r in valid]
    pnls = [r.metrics.get("total_pnl", 0) for r in valid]
    trades = [r.trade_count for r in valid]

    import numpy as np
    report.aggregate = {
        "n_runs": len(valid),
        "mean_sharpe": float(np.mean(sharpes)),
        "std_sharpe": float(np.std(sharpes)),
        "mean_pnl": float(np.mean(pnls)),
        "total_trades": sum(trades),
        "best_run": max(valid, key=lambda r: r.metrics.get("sharpe_ratio", -99)).name,
        "worst_run": min(valid, key=lambda r: r.metrics.get("sharpe_ratio", 99)).name,
    }
