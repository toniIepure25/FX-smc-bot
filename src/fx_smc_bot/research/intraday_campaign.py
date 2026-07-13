"""Intraday SMC validation campaign engine.

Orchestrates end-to-end backtesting of intraday SMC strategies with full
statistical analysis, placebo comparison, and result persistence.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Literal

import numpy as np

from fx_smc_bot.config import (
    AppConfig,
    PAIR_PIP_INFO,
    TIMEFRAME_MINUTES,
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.provenance import build_provenance
from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import compute_metrics
from fx_smc_bot.domain import BacktestResult, ClosedTrade

logger = logging.getLogger(__name__)


@dataclass
class StrategyRunConfig:
    """Configuration for a single strategy run within the campaign."""
    family: str
    pair: TradingPair
    session: str
    exec_timeframe: Timeframe = Timeframe.M5
    htf_timeframe: Timeframe = Timeframe.H1
    ablation: str | None = None
    label: str = ""

    def __post_init__(self):
        if not self.label:
            parts = [self.family, self.pair.value, self.session]
            if self.ablation:
                parts.append(self.ablation)
            self.label = "/".join(parts)


@dataclass
class RunResult:
    """Result from a single strategy run."""
    config: StrategyRunConfig
    backtest_result: BacktestResult | None = None
    trade_count: int = 0
    net_pnl: float = 0.0
    sharpe: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    error: str | None = None

    def summary_dict(self) -> dict[str, Any]:
        return {
            "label": self.config.label,
            "family": self.config.family,
            "pair": self.config.pair.value,
            "session": self.config.session,
            "ablation": self.config.ablation,
            "trade_count": self.trade_count,
            "net_pnl": round(self.net_pnl, 2),
            "sharpe": round(self.sharpe, 4) if self.sharpe is not None else None,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "profit_factor": round(self.profit_factor, 4) if self.profit_factor is not None else None,
            "max_drawdown": round(self.max_drawdown, 4) if self.max_drawdown is not None else None,
            "error": self.error,
        }


@dataclass
class CampaignResult:
    """Aggregated results from a full campaign."""
    run_id: str
    timestamp: str
    runs: list[RunResult] = field(default_factory=list)
    data_provenance: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""
    notes: str = ""

    def summary(self) -> list[dict[str, Any]]:
        return [r.summary_dict() for r in self.runs]


def _build_app_config(
    strategy_family: str,
    session: str,
    exec_tf: Timeframe = Timeframe.M5,
    htf_tf: Timeframe = Timeframe.H1,
    fill_policy: str = "conservative",
    commission_per_lot: float = 3.5,
    spread_pips: float = 1.5,
    slippage_pips: float = 0.3,
    initial_capital: float = 100_000.0,
) -> AppConfig:
    """Create an AppConfig tuned for intraday strategy evaluation."""
    from fx_smc_bot.config import FillPolicy
    cfg = AppConfig()
    cfg.execution.fill_policy = FillPolicy(fill_policy)
    cfg.backtest.commission_per_lot = commission_per_lot
    cfg.backtest.initial_capital = initial_capital
    return cfg


def _extract_daily_returns(
    equity_curve: list,
    initial_capital: float,
) -> np.ndarray:
    """Extract daily returns from an equity curve."""
    if len(equity_curve) < 2:
        return np.array([])

    daily: dict[date, float] = {}
    for pt in equity_curve:
        d = pt.timestamp.date() if isinstance(pt.timestamp, datetime) else pt.timestamp
        daily[d] = pt.equity

    dates = sorted(daily.keys())
    if len(dates) < 2:
        return np.array([])

    equities = [daily[d] for d in dates]
    returns = np.diff(equities) / np.array(equities[:-1])
    return returns


def run_single(
    run_config: StrategyRunConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
    app_config: AppConfig | None = None,
) -> RunResult:
    """Execute a single strategy run and return results."""
    result = RunResult(config=run_config)

    if run_config.pair not in data:
        result.error = f"No data for {run_config.pair.value}"
        return result

    try:
        cfg = app_config or _build_app_config(
            run_config.family,
            run_config.session,
            exec_tf=run_config.exec_timeframe,
            htf_tf=run_config.htf_timeframe,
        )

        single_pair_data = {run_config.pair: data[run_config.pair]}
        single_htf = (
            {run_config.pair: htf_data[run_config.pair]}
            if htf_data and run_config.pair in htf_data
            else None
        )

        engine = BacktestEngine(config=cfg)
        bt_result = engine.run(single_pair_data, htf_data=single_htf)

        result.backtest_result = bt_result
        result.trade_count = len(bt_result.trades)
        result.net_pnl = sum(t.pnl for t in bt_result.trades)

        if bt_result.trades:
            metrics = compute_metrics(
                bt_result.trades, bt_result.equity_curve, bt_result.initial_capital,
            )
            result.win_rate = metrics.win_rate
            result.profit_factor = metrics.profit_factor
            result.max_drawdown = metrics.max_drawdown_pct

            daily_rets = _extract_daily_returns(
                bt_result.equity_curve, bt_result.initial_capital,
            )
            if len(daily_rets) > 1 and np.std(daily_rets) > 0:
                result.sharpe = float(np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252))

    except Exception as e:
        logger.exception("Error running %s", run_config.label)
        result.error = str(e)

    return result


def run_campaign(
    strategies: list[str],
    pairs: list[TradingPair],
    sessions: list[str],
    data_dir: Path,
    output_dir: Path,
    exec_tf: Timeframe = Timeframe.M5,
    htf_tf: Timeframe = Timeframe.H1,
    ablation: str | None = None,
    seed: int = 42,
) -> CampaignResult:
    """Run a full validation campaign across strategies, pairs, sessions."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    campaign = CampaignResult(
        run_id=run_id,
        timestamp=datetime.now().isoformat(),
    )

    logger.info("Loading data from %s (exec_tf=%s, htf_tf=%s)", data_dir, exec_tf.value, htf_tf.value)
    data = load_pair_data(data_dir, pairs=pairs, timeframe=exec_tf)
    htf_data = load_htf_data(data, htf_timeframe=htf_tf, data_dir=data_dir) if data else None

    if not data:
        logger.error("No data loaded from %s", data_dir)
        campaign.notes = "No data loaded"
        return campaign

    for pair, series in data.items():
        prov = build_provenance(series, source="campaign_loader")
        campaign.data_provenance[pair.value] = {
            "bars": len(series),
            "timeframe": series.timeframe.value,
            "start": str(series.timestamps[0]),
            "end": str(series.timestamps[-1]),
            "missing_intervals": len(prov.missing_intervals) if prov.missing_intervals else 0,
        }

    total_runs = len(strategies) * len(pairs) * len(sessions)
    logger.info("Campaign: %d runs (%d strategies x %d pairs x %d sessions)",
                total_runs, len(strategies), len(pairs), len(sessions))

    for strat in strategies:
        for pair in pairs:
            for sess in sessions:
                run_cfg = StrategyRunConfig(
                    family=strat,
                    pair=pair,
                    session=sess,
                    exec_timeframe=exec_tf,
                    htf_timeframe=htf_tf,
                    ablation=ablation,
                )
                logger.info("Running: %s", run_cfg.label)
                result = run_single(run_cfg, data, htf_data)
                campaign.runs.append(result)
                logger.info(
                    "  -> trades=%d pnl=%.2f sharpe=%s",
                    result.trade_count, result.net_pnl,
                    f"{result.sharpe:.4f}" if result.sharpe is not None else "N/A",
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    save_campaign_results(campaign, output_dir)
    return campaign


def save_campaign_results(campaign: CampaignResult, output_dir: Path) -> Path:
    """Save campaign results to JSON."""
    summary = {
        "run_id": campaign.run_id,
        "timestamp": campaign.timestamp,
        "config_hash": campaign.config_hash,
        "data_provenance": campaign.data_provenance,
        "notes": campaign.notes,
        "runs": campaign.summary(),
    }

    path = output_dir / f"campaign_{campaign.run_id}.json"
    path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Campaign results saved to %s", path)
    return path


def build_statistical_report(
    campaign: CampaignResult,
    n_bootstrap: int = 5000,
    block_length: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Build a statistical report for the campaign using bootstrap inference.

    Returns a dict with per-strategy statistical summaries.
    """
    from fx_smc_bot.research.statistical_inference import build_inference_report

    report: dict[str, Any] = {"run_id": campaign.run_id, "strategies": {}}

    for run in campaign.runs:
        if run.error or not run.backtest_result or not run.backtest_result.trades:
            report["strategies"][run.config.label] = {"error": run.error or "no trades"}
            continue

        daily_rets = _extract_daily_returns(
            run.backtest_result.equity_curve,
            run.backtest_result.initial_capital,
        )
        if len(daily_rets) < 10:
            report["strategies"][run.config.label] = {"error": "insufficient data (<10 daily returns)"}
            continue

        try:
            inf_report = build_inference_report(
                daily_rets,
                n_bootstrap=n_bootstrap,
                block_length=block_length,
                seed=seed,
            )
            ci = inf_report.sharpe_ci
            report["strategies"][run.config.label] = {
                "sharpe": inf_report.sharpe,
                "sharpe_ci_lower": ci.lower if ci else None,
                "sharpe_ci_upper": ci.upper if ci else None,
                "sortino": inf_report.sortino,
                "psr": inf_report.psr,
                "psr_significant": inf_report.psr > 0.95 if inf_report.psr is not None else None,
                "var_5pct": inf_report.var_5pct,
                "cvar_5pct": inf_report.cvar_5pct,
                "n_observations": len(daily_rets),
                "trade_count": run.trade_count,
            }
        except Exception as e:
            logger.warning("Statistical analysis failed for %s: %s", run.config.label, e)
            report["strategies"][run.config.label] = {"error": str(e)}

    return report
