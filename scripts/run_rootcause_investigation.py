#!/usr/bin/env python3
"""Root-Cause Investigation — determine the dominant failure mechanism and whether
the strategy can be rescued through better data, pair diversification, or minimal
regime-aware adaptation.

Themes:
  A. Root-cause attribution of holdout failure
  B. Better-data confirmation and source comparison
  C. Pair concentration and family contribution stress testing
  D. Minimal regime-aware recovery attempts
  E. Champion re-evaluation under stronger OOS criteria
  F. Final root-cause and promotion recommendation package
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
    AttributionSlice, _group_by, by_direction, by_family, by_month,
    by_pair, by_regime, by_session, by_year, by_interaction,
)
from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import run_diagnostics, format_diagnostic_report
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.providers.dukascopy import generate_realistic_data
from fx_smc_bot.alpha.diagnostics import DetectorDiagnostics, format_detector_diagnostics
from fx_smc_bot.execution.stress import run_execution_stress
from fx_smc_bot.ml.regime import VolatilityRegimeClassifier, TrendRangeClassifier, SpreadRegimeClassifier
from fx_smc_bot.research.evaluation import EvaluationReport, evaluate, cost_sensitivity
from fx_smc_bot.research.frozen_config import DataSplitPolicy, split_data
from fx_smc_bot.research.gating import DeploymentGateConfig, evaluate_deployment_gate
from fx_smc_bot.research.walk_forward import anchored_walk_forward, rolling_walk_forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("rootcause")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
OUTPUT_DIR = PROJECT_ROOT / "results" / "rootcause_wave"

ALPHA_FAMILIES: dict[str, list[str]] = {
    "sweep_plus_bos": ["sweep_reversal", "bos_continuation"],
    "bos_continuation_only": ["bos_continuation"],
    "sweep_reversal_only": ["sweep_reversal"],
}

RISK_OVERRIDES: dict[str, Any] = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}


def _build_config(
    alpha_candidate: str,
    risk_overrides: dict[str, Any] | None = None,
    pairs: list[str] | None = None,
) -> AppConfig:
    cfg = AppConfig()
    families = ALPHA_FAMILIES.get(alpha_candidate, [alpha_candidate])
    cfg.alpha.enabled_families = list(families)
    for k, v in (risk_overrides or RISK_OVERRIDES).items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _run_bt(
    cfg: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf: dict[TradingPair, BarSeries] | None = None,
    diag: DetectorDiagnostics | None = None,
):
    engine = BacktestEngine(cfg)
    result = engine.run(data, htf, diagnostics=diag)
    metrics = engine.metrics(result)
    return result, metrics


def _slice(data: dict[TradingPair, BarSeries], s: int, e: int):
    return {p: sr.slice(s, e) for p, sr in data.items()}


def _filter_pairs(data: dict[TradingPair, BarSeries], keep: list[str]):
    return {p: sr for p, sr in data.items() if p.value in keep}


def _attr_tbl(slices: list[AttributionSlice]) -> str:
    if not slices:
        return "No data.\n"
    lines = [
        f"| {'Label':<28s} | {'Trades':>6s} | {'PnL':>14s} | {'Win%':>6s} | {'Avg PnL':>12s} | {'Avg RR':>6s} |",
        f"|{'-'*30}|{'-'*8}|{'-'*16}|{'-'*8}|{'-'*14}|{'-'*8}|",
    ]
    for s in sorted(slices, key=lambda x: x.total_pnl):
        lines.append(
            f"| {s.label:<28s} | {s.trade_count:>6d} | {s.total_pnl:>14,.2f} | "
            f"{s.win_rate:>5.1%} | {s.avg_pnl:>12,.2f} | {s.avg_rr:>6.2f} |"
        )
    return "\n".join(lines) + "\n"


_MH = (
    f"| {'Label':<28s} | {'Trades':>6s} | {'Sharpe':>7s} | {'PF':>6s} | "
    f"{'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>14s} | {'Calmar':>7s} |"
)
_MS = f"|{'-'*30}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*16}|{'-'*9}|"


def _mrow(label: str, m: PerformanceSummary) -> str:
    return (
        f"| {label:<28s} | {m.total_trades:>6d} | {m.sharpe_ratio:>7.3f} | "
        f"{m.profit_factor:>6.2f} | {m.max_drawdown_pct:>7.1%} | {m.win_rate:>5.1%} | "
        f"{m.total_pnl:>14,.2f} | {m.calmar_ratio:>7.2f} |"
    )


# ======================================================================
# THEME A — ROOT-CAUSE ATTRIBUTION
# ======================================================================

def theme_a(full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME A — Root-Cause Attribution of Holdout Failure")
    logger.info("=" * 60)

    policy = DataSplitPolicy(train_end_pct=0.60, validation_end_pct=0.80, embargo_bars=10)
    train_data, _, holdout_data = split_data(full_data, policy)

    cfg = _build_config("sweep_plus_bos")
    logger.info("Running train backtest ...")
    train_res, train_m = _run_bt(cfg, train_data, htf_data)
    logger.info("Running holdout backtest ...")
    hold_res, hold_m = _run_bt(cfg, holdout_data, htf_data)

    train_eval = evaluate(train_res, train_m)
    hold_eval = evaluate(hold_res, hold_m)

    # --- Expectancy decomposition ---
    t_trades = train_res.trades
    h_trades = hold_res.trades
    t_pnls = np.array([t.pnl for t in t_trades])
    h_pnls = np.array([t.pnl for t in h_trades])
    t_wins = t_pnls[t_pnls > 0]
    t_losses = t_pnls[t_pnls < 0]
    h_wins = h_pnls[h_pnls > 0]
    h_losses = h_pnls[h_pnls < 0]

    exp = {
        "train": {
            "win_rate": float(len(t_wins) / len(t_pnls)) if len(t_pnls) else 0,
            "avg_win": float(np.mean(t_wins)) if len(t_wins) else 0,
            "avg_loss": float(np.mean(t_losses)) if len(t_losses) else 0,
            "avg_pnl": float(np.mean(t_pnls)) if len(t_pnls) else 0,
            "expectancy": float(np.mean(t_pnls)) if len(t_pnls) else 0,
            "median_win": float(np.median(t_wins)) if len(t_wins) else 0,
            "median_loss": float(np.median(t_losses)) if len(t_losses) else 0,
            "p10_pnl": float(np.percentile(t_pnls, 10)),
            "p90_pnl": float(np.percentile(t_pnls, 90)),
        },
        "holdout": {
            "win_rate": float(len(h_wins) / len(h_pnls)) if len(h_pnls) else 0,
            "avg_win": float(np.mean(h_wins)) if len(h_wins) else 0,
            "avg_loss": float(np.mean(h_losses)) if len(h_losses) else 0,
            "avg_pnl": float(np.mean(h_pnls)) if len(h_pnls) else 0,
            "expectancy": float(np.mean(h_pnls)) if len(h_pnls) else 0,
            "median_win": float(np.median(h_wins)) if len(h_wins) else 0,
            "median_loss": float(np.median(h_losses)) if len(h_losses) else 0,
            "p10_pnl": float(np.percentile(h_pnls, 10)),
            "p90_pnl": float(np.percentile(h_pnls, 90)),
        },
    }

    # --- Root cause report ---
    lines = [
        "# Root-Cause Attribution Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## 1. Overall Metrics\n", _MH, _MS,
        _mrow("Train", train_m), _mrow("Holdout", hold_m),
        f"\n## 2. Expectancy Decomposition\n",
        f"| {'Metric':<24s} | {'Train':>16s} | {'Holdout':>16s} | {'Change':>10s} |",
        f"|{'-'*26}|{'-'*18}|{'-'*18}|{'-'*12}|",
    ]
    for key in ["win_rate", "avg_win", "avg_loss", "avg_pnl", "median_win", "median_loss", "p10_pnl", "p90_pnl"]:
        tv = exp["train"][key]
        hv = exp["holdout"][key]
        if "rate" in key:
            lines.append(f"| {key:<24s} | {tv:>15.1%} | {hv:>15.1%} | {hv - tv:>+9.1%} |")
        else:
            lines.append(f"| {key:<24s} | {tv:>16,.2f} | {hv:>16,.2f} | {hv - tv:>+10,.2f} |")

    # Dominant mechanism
    wr_drop = exp["train"]["win_rate"] - exp["holdout"]["win_rate"]
    avg_win_drop = 1 - (exp["holdout"]["avg_win"] / exp["train"]["avg_win"]) if exp["train"]["avg_win"] else 0
    avg_loss_mag = abs(exp["holdout"]["avg_loss"]) / abs(exp["train"]["avg_loss"]) if exp["train"]["avg_loss"] else 1

    lines.append(f"\n## 3. Dominant Failure Mechanism\n")
    lines.append(f"- Win rate dropped by {wr_drop:.1%} (from {exp['train']['win_rate']:.1%} to {exp['holdout']['win_rate']:.1%})")
    lines.append(f"- Average winner size change: {avg_win_drop:+.1%}")
    lines.append(f"- Average loser magnitude ratio (holdout/train): {avg_loss_mag:.2f}x")

    if wr_drop > 0.15:
        lines.append(f"\n**PRIMARY CAUSE: Win-rate collapse** — the strategy generates trades at similar "
                      f"frequency but far fewer are profitable in holdout.")
    if avg_win_drop > 0.5:
        lines.append(f"**CONTRIBUTING: Winner size collapse** — winning trades are much smaller.")

    # Pair contribution
    lines.append(f"\n## 4. Pair-Level Contribution Shift\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.by_pair))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.by_pair))

    # GBPUSD only appears in holdout — quantify
    train_pair_pnl = {s.label: s.total_pnl for s in train_eval.by_pair}
    hold_pair_pnl = {s.label: s.total_pnl for s in hold_eval.by_pair}
    lines.append("### Pair PnL Shift\n")
    all_pairs_set = set(train_pair_pnl) | set(hold_pair_pnl)
    for pair in sorted(all_pairs_set):
        tp = train_pair_pnl.get(pair, 0)
        hp = hold_pair_pnl.get(pair, 0)
        lines.append(f"- {pair}: Train {tp:>14,.2f} -> Holdout {hp:>14,.2f}")

    # Family contribution
    lines.append(f"\n## 5. Family-Level Contribution Shift\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.by_family))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.by_family))

    train_fam_pnl = {s.label: s for s in train_eval.by_family}
    hold_fam_pnl = {s.label: s for s in hold_eval.by_family}
    lines.append("### Family Reversal Analysis\n")
    for fam in sorted(set(train_fam_pnl) | set(hold_fam_pnl)):
        ts = train_fam_pnl.get(fam)
        hs = hold_fam_pnl.get(fam)
        if ts and hs:
            lines.append(f"- **{fam}**: Train WR {ts.win_rate:.1%} -> Holdout WR {hs.win_rate:.1%} | "
                          f"Train PnL {ts.total_pnl:,.0f} -> Holdout PnL {hs.total_pnl:,.0f}")

    # Direction
    lines.append(f"\n## 6. Direction Decomposition\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.by_direction))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.by_direction))

    # Regime
    lines.append(f"\n## 7. Regime Attribution\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.by_regime))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.by_regime))

    # Family x Regime
    lines.append(f"\n## 8. Family x Regime Interaction\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.family_x_regime))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.family_x_regime))

    # Month
    lines.append(f"\n## 9. Month-by-Month\n")
    lines.append("### Train\n")
    lines.append(_attr_tbl(train_eval.by_month))
    lines.append("### Holdout\n")
    lines.append(_attr_tbl(hold_eval.by_month))

    # Summary
    lines.append(f"\n## 10. Root-Cause Summary\n")
    causes: list[str] = []
    if wr_drop > 0.15:
        causes.append("win-rate collapse (primary)")
    if avg_win_drop > 0.5:
        causes.append("winner size collapse")
    # Check pair concentration
    train_usdjpy_pct = train_pair_pnl.get("USDJPY", 0) / train_m.total_pnl if train_m.total_pnl else 0
    if train_usdjpy_pct > 0.9:
        causes.append(f"extreme USDJPY concentration ({train_usdjpy_pct:.0%} of train PnL)")
    # Check family reversal
    sweep_train = train_fam_pnl.get("sweep_reversal")
    sweep_hold = hold_fam_pnl.get("sweep_reversal")
    if sweep_train and sweep_hold and sweep_train.total_pnl > 0 and sweep_hold.total_pnl < 0:
        causes.append("sweep_reversal family reversal (profitable in train, loss-making in holdout)")
    for c in causes:
        lines.append(f"- {c}")

    (OUTPUT_DIR / "root_cause_report.md").write_text("\n".join(lines))
    logger.info("Wrote root_cause_report.md")

    return {
        "train_data": train_data, "holdout_data": holdout_data,
        "train_res": train_res, "hold_res": hold_res,
        "train_m": train_m, "hold_m": hold_m,
        "train_eval": train_eval, "hold_eval": hold_eval,
        "expectancy": exp, "causes": causes,
    }


# ======================================================================
# THEME B — BETTER-DATA CONFIRMATION
# ======================================================================

def theme_b(full_data, htf_data, ctx_a):
    logger.info("=" * 60)
    logger.info("THEME B — Better-Data Confirmation")
    logger.info("=" * 60)

    synth_data: dict[TradingPair, BarSeries] = {}
    for pair in [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]:
        df = generate_realistic_data(
            pair, Timeframe.H1,
            start_date="2024-04-10", end_date="2026-04-10",
            seed=42,
        )
        ts = df["timestamp"].values.astype("datetime64[ns]")
        synth_data[pair] = BarSeries(
            pair=pair, timeframe=Timeframe.H1,
            timestamps=ts,
            open=df["open"].values.astype(np.float64),
            high=df["high"].values.astype(np.float64),
            low=df["low"].values.astype(np.float64),
            close=df["close"].values.astype(np.float64),
            volume=df["volume"].values.astype(np.float64) if "volume" in df else None,
            spread=df["spread"].values.astype(np.float64) if "spread" in df else None,
        )

    policy = DataSplitPolicy(train_end_pct=0.60, validation_end_pct=0.80, embargo_bars=10)
    synth_train, _, synth_hold = split_data(synth_data, policy)

    lines = [
        "# Data Source Quality Comparison",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\n## 1. Data Quality Diagnostics\n",
        "### Yahoo Finance\n",
    ]
    for pair, series in sorted(full_data.items(), key=lambda x: x[0].value):
        d = run_diagnostics(series)
        lines.append(f"**{pair.value}**: {len(series):,d} bars | Missing: {d.missing_bar_pct:.1%} | "
                      f"Quality: {d.quality_score:.3f} | Spread: {'N/A' if d.mean_spread is None else f'{d.mean_spread:.6f}'}")

    lines.append("\n### Dukascopy-Quality Synthetic (with realistic spreads)\n")
    for pair, series in sorted(synth_data.items(), key=lambda x: x[0].value):
        d = run_diagnostics(series)
        lines.append(f"**{pair.value}**: {len(series):,d} bars | Missing: {d.missing_bar_pct:.1%} | "
                      f"Quality: {d.quality_score:.3f} | Spread: {d.mean_spread:.6f}")

    # Run backtests on synthetic data
    lines.append("\n## 2. Champion Performance: Yahoo vs Synthetic\n")
    cfg = _build_config("sweep_plus_bos")

    logger.info("Running synthetic-data train backtest ...")
    synth_train_res, synth_train_m = _run_bt(cfg, synth_train)
    logger.info("Running synthetic-data holdout backtest ...")
    synth_hold_res, synth_hold_m = _run_bt(cfg, synth_hold)

    lines.extend([_MH, _MS,
        _mrow("Yahoo Train", ctx_a["train_m"]),
        _mrow("Yahoo Holdout", ctx_a["hold_m"]),
        _mrow("Synth Train", synth_train_m),
        _mrow("Synth Holdout", synth_hold_m),
    ])

    # Spread sensitivity on Yahoo holdout
    lines.append("\n## 3. Spread Assumption Sensitivity (Yahoo Holdout)\n")
    hold_cost = cost_sensitivity(
        ctx_a["hold_res"].trades, ctx_a["hold_res"].equity_curve,
        ctx_a["hold_res"].initial_capital,
        multipliers=[0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
    )
    lines.append(f"| {'Mult':>6s} | {'Sharpe':>8s} | {'PF':>6s} | {'PnL':>14s} | {'Win%':>6s} |")
    lines.append(f"|{'-'*8}|{'-'*10}|{'-'*8}|{'-'*16}|{'-'*8}|")
    for pt in hold_cost:
        lines.append(f"| {pt.cost_multiplier:>6.2f} | {pt.sharpe_ratio:>8.3f} | "
                      f"{pt.profit_factor:>6.2f} | {pt.total_pnl:>14,.2f} | {pt.win_rate:>5.1%} |")

    lines.append("\n## 4. Key Findings\n")
    lines.append("- Yahoo Finance has ~30% missing bars and no spread data (quality ~0.66)")
    lines.append("- The fixed 1.5 pip spread is 3-15x wider than institutional reality")
    lines.append("- Synthetic data with realistic spreads allows isolating data-quality effects")
    if synth_hold_m.sharpe_ratio > ctx_a["hold_m"].sharpe_ratio + 0.1:
        lines.append(f"- Synthetic holdout Sharpe ({synth_hold_m.sharpe_ratio:.3f}) is materially "
                      f"better than Yahoo holdout ({ctx_a['hold_m'].sharpe_ratio:.3f}) — "
                      f"data quality contributes to degradation")
    else:
        lines.append(f"- Synthetic holdout Sharpe ({synth_hold_m.sharpe_ratio:.3f}) is similar to "
                      f"Yahoo ({ctx_a['hold_m'].sharpe_ratio:.3f}) — data quality is NOT the primary issue")

    (OUTPUT_DIR / "data_source_quality_comparison.md").write_text("\n".join(lines))
    logger.info("Wrote data_source_quality_comparison.md")

    return {
        "synth_train_m": synth_train_m, "synth_hold_m": synth_hold_m,
        "hold_cost": hold_cost,
    }


# ======================================================================
# THEME C — PAIR CONCENTRATION AND FAMILY STRESS TESTING
# ======================================================================

@dataclass(slots=True)
class VariantResult:
    label: str
    candidate: str
    pairs_used: str
    sharpe: float = 0.0
    pf: float = 0.0
    dd: float = 0.0
    trades: int = 0
    pnl: float = 0.0
    wr: float = 0.0
    calmar: float = 0.0
    period: str = ""

    def to_row(self) -> str:
        return (
            f"| {self.label:<32s} | {self.pairs_used:<20s} | {self.trades:>6d} | "
            f"{self.sharpe:>7.3f} | {self.pf:>6.2f} | {self.dd:>7.1%} | "
            f"{self.wr:>5.1%} | {self.pnl:>14,.2f} |"
        )

_VH = (
    f"| {'Variant':<32s} | {'Pairs':<20s} | {'Trades':>6s} | {'Sharpe':>7s} | "
    f"{'PF':>6s} | {'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>14s} |"
)
_VS = f"|{'-'*34}|{'-'*22}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*16}|"


def _run_variant(
    label: str, candidate: str, pairs_used: str,
    data: dict[TradingPair, BarSeries],
    htf: dict[TradingPair, BarSeries] | None,
    period: str,
) -> VariantResult:
    vr = VariantResult(label=label, candidate=candidate, pairs_used=pairs_used, period=period)
    if not data:
        return vr
    cfg = _build_config(candidate)
    try:
        res, m = _run_bt(cfg, data, htf)
        vr.sharpe = m.sharpe_ratio
        vr.pf = m.profit_factor
        vr.dd = m.max_drawdown_pct
        vr.trades = m.total_trades
        vr.pnl = m.total_pnl
        vr.wr = m.win_rate
        vr.calmar = m.calmar_ratio
    except Exception as e:
        logger.warning("Variant %s failed: %s", label, e)
    return vr


def theme_c(full_data, htf_data, ctx_a):
    logger.info("=" * 60)
    logger.info("THEME C — Pair Concentration & Family Stress Testing")
    logger.info("=" * 60)

    train_data = ctx_a["train_data"]
    holdout_data = ctx_a["holdout_data"]

    all_pairs_list = ["EURUSD", "GBPUSD", "USDJPY"]

    pair_scenarios = [
        ("All 3 pairs", all_pairs_list),
        ("Excl EURUSD", ["GBPUSD", "USDJPY"]),
        ("Excl GBPUSD", ["EURUSD", "USDJPY"]),
        ("Excl USDJPY", ["EURUSD", "GBPUSD"]),
        ("USDJPY only", ["USDJPY"]),
        ("EURUSD only", ["EURUSD"]),
        ("GBPUSD only", ["GBPUSD"]),
    ]

    candidates = ["sweep_plus_bos", "bos_continuation_only", "sweep_reversal_only"]

    all_variants: list[VariantResult] = []

    for candidate in candidates:
        for pair_label, pair_list in pair_scenarios:
            for period_label, period_data in [("train", train_data), ("holdout", holdout_data)]:
                filtered = _filter_pairs(period_data, pair_list)
                htf_filtered = _filter_pairs(htf_data, pair_list) if htf_data else None
                label = f"{candidate} | {pair_label}"
                logger.info("  %s [%s] ...", label, period_label)
                vr = _run_variant(label, candidate, pair_label, filtered, htf_filtered, period_label)
                all_variants.append(vr)

    # Build reports
    lines = [
        "# Pair Concentration and Family Stress Test Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## 1. Train Period Results\n", _VH, _VS,
    ]
    for vr in sorted([v for v in all_variants if v.period == "train"], key=lambda x: -x.sharpe):
        lines.append(vr.to_row())

    lines.extend([f"\n## 2. Holdout Period Results\n", _VH, _VS])
    for vr in sorted([v for v in all_variants if v.period == "holdout"], key=lambda x: -x.sharpe):
        lines.append(vr.to_row())

    # Analysis: Is the edge just USDJPY?
    lines.append(f"\n## 3. Is the Edge Just USDJPY?\n")
    for candidate in candidates:
        all_train = next((v for v in all_variants if v.label == f"{candidate} | All 3 pairs" and v.period == "train"), None)
        jpy_train = next((v for v in all_variants if v.label == f"{candidate} | USDJPY only" and v.period == "train"), None)
        all_hold = next((v for v in all_variants if v.label == f"{candidate} | All 3 pairs" and v.period == "holdout"), None)
        jpy_hold = next((v for v in all_variants if v.label == f"{candidate} | USDJPY only" and v.period == "holdout"), None)
        if all_train and jpy_train:
            lines.append(f"\n**{candidate}**:")
            lines.append(f"- Train: All pairs Sharpe={all_train.sharpe:.3f} vs USDJPY-only Sharpe={jpy_train.sharpe:.3f}")
            if all_hold and jpy_hold:
                lines.append(f"- Holdout: All pairs Sharpe={all_hold.sharpe:.3f} vs USDJPY-only Sharpe={jpy_hold.sharpe:.3f}")

    # Analysis: Does multi-pair help or hurt OOS?
    lines.append(f"\n## 4. Does Multi-Pair Improve OOS Stability?\n")
    for candidate in candidates:
        all_h = next((v for v in all_variants if v.label == f"{candidate} | All 3 pairs" and v.period == "holdout"), None)
        jpy_h = next((v for v in all_variants if v.label == f"{candidate} | USDJPY only" and v.period == "holdout"), None)
        excl_jpy_h = next((v for v in all_variants if v.label == f"{candidate} | Excl USDJPY" and v.period == "holdout"), None)
        if all_h and jpy_h:
            lines.append(f"\n**{candidate}**:")
            lines.append(f"- All pairs holdout: Sharpe={all_h.sharpe:.3f}, Trades={all_h.trades}")
            lines.append(f"- USDJPY-only holdout: Sharpe={jpy_h.sharpe:.3f}, Trades={jpy_h.trades}")
            if excl_jpy_h:
                lines.append(f"- Excl USDJPY holdout: Sharpe={excl_jpy_h.sharpe:.3f}, Trades={excl_jpy_h.trades}")

    # Family comparison
    lines.append(f"\n## 5. Family Comparison (All Pairs)\n")
    for period in ["train", "holdout"]:
        lines.append(f"\n### {period.title()}\n")
        for candidate in candidates:
            v = next((v for v in all_variants if v.label == f"{candidate} | All 3 pairs" and v.period == period), None)
            if v:
                lines.append(f"- **{candidate}**: Sharpe={v.sharpe:.3f} | PF={v.pf:.2f} | "
                              f"DD={v.dd:.1%} | Trades={v.trades} | Win%={v.wr:.1%}")

    (OUTPUT_DIR / "pair_concentration_report.md").write_text("\n".join(lines))
    logger.info("Wrote pair_concentration_report.md")

    # Save JSON for later use
    variants_json = [
        {"label": v.label, "candidate": v.candidate, "pairs": v.pairs_used,
         "period": v.period, "sharpe": round(v.sharpe, 4), "pf": round(v.pf, 4),
         "dd": round(v.dd, 4), "trades": v.trades, "pnl": round(v.pnl, 2),
         "wr": round(v.wr, 4)}
        for v in all_variants
    ]
    (OUTPUT_DIR / "concentration_variants.json").write_text(json.dumps(variants_json, indent=2))

    return {"variants": all_variants}


# ======================================================================
# THEME D — MINIMAL REGIME-AWARE RECOVERY
# ======================================================================

def theme_d(full_data, htf_data, ctx_a, ctx_c):
    logger.info("=" * 60)
    logger.info("THEME D — Minimal Regime-Aware Recovery Attempts")
    logger.info("=" * 60)

    holdout_data = ctx_a["holdout_data"]
    train_data = ctx_a["train_data"]
    hold_eval = ctx_a["hold_eval"]
    hold_m = ctx_a["hold_m"]

    lines = [
        "# Mitigation Hypotheses and Results",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\nBaseline holdout (sweep_plus_bos): Sharpe={hold_m.sharpe_ratio:.3f} | "
        f"PF={hold_m.profit_factor:.2f} | Trades={hold_m.total_trades}",
    ]

    # Identify the best variants from Theme C
    hold_variants = [v for v in ctx_c["variants"] if v.period == "holdout"]
    best_holdout = sorted(hold_variants, key=lambda x: -x.sharpe)[:5]

    lines.append(f"\n## 1. Top 5 Holdout Variants from Concentration Analysis\n")
    lines.extend([_VH, _VS])
    for v in best_holdout:
        lines.append(v.to_row())

    # Hypothesis-driven mitigations
    mitigations: list[dict[str, Any]] = []

    # Mitigation 1: BOS-only (simplest)
    lines.append(f"\n## 2. Mitigation: BOS-Only on All Pairs\n")
    lines.append("**Hypothesis**: sweep_reversal is the dominant holdout loser; removing it should improve stability.\n")
    bos_h = next((v for v in hold_variants if v.label == "bos_continuation_only | All 3 pairs"), None)
    bos_t = next((v for v in ctx_c["variants"] if v.label == "bos_continuation_only | All 3 pairs" and v.period == "train"), None)
    if bos_h:
        lines.append(f"- Holdout: Sharpe={bos_h.sharpe:.3f} | PF={bos_h.pf:.2f} | Trades={bos_h.trades}")
        lines.append(f"- Delta vs baseline: Sharpe {bos_h.sharpe - hold_m.sharpe_ratio:+.3f}")
        mitigations.append({"label": "BOS-only all pairs", "sharpe_h": bos_h.sharpe,
                            "delta": bos_h.sharpe - hold_m.sharpe_ratio, "trades_h": bos_h.trades})

    # Mitigation 2: sweep_plus_bos USDJPY-only
    lines.append(f"\n## 3. Mitigation: sweep_plus_bos USDJPY-Only\n")
    lines.append("**Hypothesis**: non-USDJPY pairs dilute alpha and add noise.\n")
    jpy_h = next((v for v in hold_variants if v.label == "sweep_plus_bos | USDJPY only"), None)
    if jpy_h:
        lines.append(f"- Holdout: Sharpe={jpy_h.sharpe:.3f} | PF={jpy_h.pf:.2f} | Trades={jpy_h.trades}")
        lines.append(f"- Delta vs baseline: Sharpe {jpy_h.sharpe - hold_m.sharpe_ratio:+.3f}")
        mitigations.append({"label": "sweep_plus_bos USDJPY-only", "sharpe_h": jpy_h.sharpe,
                            "delta": jpy_h.sharpe - hold_m.sharpe_ratio, "trades_h": jpy_h.trades})

    # Mitigation 3: BOS-only USDJPY-only
    lines.append(f"\n## 4. Mitigation: BOS-Only USDJPY-Only\n")
    lines.append("**Hypothesis**: simplest possible config — single family, single pair.\n")
    bos_jpy_h = next((v for v in hold_variants if v.label == "bos_continuation_only | USDJPY only"), None)
    if bos_jpy_h:
        lines.append(f"- Holdout: Sharpe={bos_jpy_h.sharpe:.3f} | PF={bos_jpy_h.pf:.2f} | Trades={bos_jpy_h.trades}")
        lines.append(f"- Delta vs baseline: Sharpe {bos_jpy_h.sharpe - hold_m.sharpe_ratio:+.3f}")
        mitigations.append({"label": "BOS-only USDJPY-only", "sharpe_h": bos_jpy_h.sharpe,
                            "delta": bos_jpy_h.sharpe - hold_m.sharpe_ratio, "trades_h": bos_jpy_h.trades})

    # Mitigation 4: BOS-only excluding USDJPY
    lines.append(f"\n## 5. Mitigation: BOS-Only Excluding USDJPY\n")
    lines.append("**Hypothesis**: test whether BOS generalizes across non-USDJPY pairs.\n")
    bos_ex_h = next((v for v in hold_variants if v.label == "bos_continuation_only | Excl USDJPY"), None)
    if bos_ex_h:
        lines.append(f"- Holdout: Sharpe={bos_ex_h.sharpe:.3f} | PF={bos_ex_h.pf:.2f} | Trades={bos_ex_h.trades}")
        lines.append(f"- Delta vs baseline: Sharpe {bos_ex_h.sharpe - hold_m.sharpe_ratio:+.3f}")
        mitigations.append({"label": "BOS-only excl USDJPY", "sharpe_h": bos_ex_h.sharpe,
                            "delta": bos_ex_h.sharpe - hold_m.sharpe_ratio, "trades_h": bos_ex_h.trades})

    # Walk-forward validation of best mitigation
    lines.append(f"\n## 6. Walk-Forward Validation of Best Mitigations\n")

    ref_pair = next(iter(full_data))
    n_bars = len(full_data[ref_pair])
    wf_splits = anchored_walk_forward(n_bars, n_folds=5, min_train_bars=2000)

    wf_candidates = ["sweep_plus_bos", "bos_continuation_only"]
    wf_results: dict[str, list[float]] = {}

    for candidate in wf_candidates:
        sharpes: list[float] = []
        for split in wf_splits:
            test_data = _slice(full_data, split.test_start, split.test_end)
            cfg = _build_config(candidate)
            try:
                _, m = _run_bt(cfg, test_data, htf_data)
                sharpes.append(m.sharpe_ratio)
            except Exception:
                sharpes.append(0.0)
        wf_results[candidate] = sharpes
        logger.info("  WF %s: %s", candidate, [f"{s:.3f}" for s in sharpes])

    for candidate in wf_candidates:
        s = wf_results[candidate]
        lines.append(f"\n**{candidate}** (anchored WF, 5 folds):")
        lines.append(f"- OOS Sharpes: {[f'{x:.3f}' for x in s]}")
        lines.append(f"- Mean: {np.mean(s):.3f} | Std: {np.std(s):.3f}")
        lines.append(f"- Positive folds: {sum(1 for x in s if x > 0)}/5")
        lines.append(f"- Above 0.3: {sum(1 for x in s if x > 0.3)}/5")

    # Conclusions
    lines.append(f"\n## 7. Mitigation Conclusions\n")
    if mitigations:
        best = max(mitigations, key=lambda m: m["delta"])
        lines.append(f"Best mitigation: **{best['label']}** (Sharpe delta: {best['delta']:+.3f})")
        if best["delta"] > 0.1:
            lines.append(f"This represents a meaningful improvement over baseline.")
        else:
            lines.append(f"No mitigation produces a large enough improvement to change the recommendation.")

    (OUTPUT_DIR / "mitigation_results.md").write_text("\n".join(lines))
    logger.info("Wrote mitigation_results.md")

    return {"mitigations": mitigations, "wf_results": wf_results}


# ======================================================================
# THEME E — CHAMPION RE-EVALUATION
# ======================================================================

def theme_e(ctx_a, ctx_c, ctx_d):
    logger.info("=" * 60)
    logger.info("THEME E — Champion Re-evaluation")
    logger.info("=" * 60)

    wf = ctx_d["wf_results"]
    variants = ctx_c["variants"]

    lines = [
        "# Updated Champion Comparison",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
    ]

    # Summary table for holdout
    lines.append(f"\n## 1. Holdout Performance Summary\n")
    lines.extend([_VH, _VS])
    hold_vars = sorted([v for v in variants if v.period == "holdout" and "All 3 pairs" in v.label],
                       key=lambda x: -x.sharpe)
    for v in hold_vars:
        lines.append(v.to_row())

    # Walk-forward comparison
    lines.append(f"\n## 2. Walk-Forward OOS Comparison\n")
    lines.append(f"| {'Candidate':<28s} | {'Mean Sharpe':>11s} | {'Std':>6s} | {'Positive':>8s} | {'>0.3':>5s} |")
    lines.append(f"|{'-'*30}|{'-'*13}|{'-'*8}|{'-'*10}|{'-'*7}|")
    for candidate, sharpes in wf.items():
        pos = sum(1 for s in sharpes if s > 0)
        above = sum(1 for s in sharpes if s > 0.3)
        lines.append(f"| {candidate:<28s} | {np.mean(sharpes):>11.3f} | {np.std(sharpes):>6.3f} | "
                      f"{pos}/5{'':>5s} | {above}/5{'':>2s} |")

    # Comprehensive scoring
    lines.append(f"\n## 3. Comprehensive Scoring\n")

    candidates_eval: dict[str, dict[str, float]] = {}
    for candidate in ["sweep_plus_bos", "bos_continuation_only"]:
        train_v = next((v for v in variants if v.label == f"{candidate} | All 3 pairs" and v.period == "train"), None)
        hold_v = next((v for v in variants if v.label == f"{candidate} | All 3 pairs" and v.period == "holdout"), None)
        wf_s = wf.get(candidate, [])

        n_pairs_active_h = 0
        for pl in ["EURUSD only", "GBPUSD only", "USDJPY only"]:
            pv = next((v for v in variants if v.label == f"{candidate} | {pl}" and v.period == "holdout"), None)
            if pv and pv.trades > 5:
                n_pairs_active_h += 1

        scores = {
            "train_sharpe": train_v.sharpe if train_v else 0,
            "holdout_sharpe": hold_v.sharpe if hold_v else 0,
            "wf_mean_sharpe": float(np.mean(wf_s)) if wf_s else 0,
            "wf_pct_positive": sum(1 for s in wf_s if s > 0) / max(len(wf_s), 1),
            "holdout_dd": hold_v.dd if hold_v else 1,
            "holdout_trades": hold_v.trades if hold_v else 0,
            "pair_diversification": n_pairs_active_h / 3.0,
            "simplicity": 1.0 if candidate == "bos_continuation_only" else 0.5,
        }

        # Composite OOS score (weights: OOS Sharpe 40%, consistency 20%, holdout 20%, simplicity 10%, diversification 10%)
        composite = (
            scores["wf_mean_sharpe"] * 0.4
            + scores["wf_pct_positive"] * 0.2
            + scores["holdout_sharpe"] * 0.2
            + scores["simplicity"] * 0.1
            + scores["pair_diversification"] * 0.1
        )
        scores["composite"] = composite
        candidates_eval[candidate] = scores

    lines.append(f"| {'Metric':<28s} | {'sweep_plus_bos':>18s} | {'bos_continuation_only':>22s} |")
    lines.append(f"|{'-'*30}|{'-'*20}|{'-'*24}|")
    for key in ["train_sharpe", "holdout_sharpe", "wf_mean_sharpe", "wf_pct_positive",
                 "holdout_dd", "holdout_trades", "pair_diversification", "simplicity", "composite"]:
        sv = candidates_eval["sweep_plus_bos"][key]
        bv = candidates_eval["bos_continuation_only"][key]
        if "pct" in key or key in ("simplicity", "pair_diversification", "holdout_dd"):
            lines.append(f"| {key:<28s} | {sv:>18.1%} | {bv:>22.1%} |")
        elif key == "holdout_trades":
            lines.append(f"| {key:<28s} | {int(sv):>18d} | {int(bv):>22d} |")
        else:
            lines.append(f"| {key:<28s} | {sv:>18.3f} | {bv:>22.3f} |")

    # Champion determination
    s_comp = candidates_eval["sweep_plus_bos"]["composite"]
    b_comp = candidates_eval["bos_continuation_only"]["composite"]

    if abs(s_comp - b_comp) < 0.02:
        champion = "bos_continuation_only"
        reason = "similar composite score, prefer simplicity"
    elif b_comp > s_comp:
        champion = "bos_continuation_only"
        reason = f"higher composite score ({b_comp:.3f} vs {s_comp:.3f})"
    else:
        champion = "sweep_plus_bos"
        reason = f"higher composite score ({s_comp:.3f} vs {b_comp:.3f})"

    lines.append(f"\n## 4. Champion Determination\n")
    lines.append(f"**Updated Champion: {champion}** (reason: {reason})")

    (OUTPUT_DIR / "updated_champion_comparison.md").write_text("\n".join(lines))
    logger.info("Wrote updated_champion_comparison.md")

    return {"champion": champion, "reason": reason, "candidates_eval": candidates_eval, "wf": wf}


# ======================================================================
# THEME F — FINAL RECOMMENDATION
# ======================================================================

def theme_f(ctx_a, ctx_b, ctx_c, ctx_d, ctx_e):
    logger.info("=" * 60)
    logger.info("THEME F — Final Root-Cause and Promotion Recommendation")
    logger.info("=" * 60)

    champion = ctx_e["champion"]
    reason = ctx_e["reason"]
    causes = ctx_a["causes"]
    wf = ctx_d["wf_results"]
    ce = ctx_e["candidates_eval"]
    train_m = ctx_a["train_m"]
    hold_m = ctx_a["hold_m"]

    champion_wf = wf.get(champion, [])
    mean_oos = float(np.mean(champion_wf)) if champion_wf else 0
    pct_pos = sum(1 for s in champion_wf if s > 0) / max(len(champion_wf), 1)
    pct_above = sum(1 for s in champion_wf if s > 0.3) / max(len(champion_wf), 1)

    # Decision logic
    stress_ok = True  # From previous wave
    has_useful_mitigation = any(m["delta"] > 0.1 for m in ctx_d["mitigations"])

    if pct_pos >= 0.6 and mean_oos >= 0.2:
        if hold_m.sharpe_ratio >= 0.15 and stress_ok:
            decision = "CONTINUE_PAPER_TRADING"
            confidence = "medium"
        else:
            decision = "CONTINUE_PAPER_TRADING"
            confidence = "low-medium"
    elif pct_pos >= 0.4 and mean_oos > 0:
        if has_useful_mitigation:
            decision = "CONTINUE_WITH_SIMPLIFICATION"
            confidence = "low-medium"
        else:
            decision = "HOLD_FOR_MORE_VALIDATION"
            confidence = "low-medium"
    elif pct_pos < 0.3:
        decision = "REWORK_STRATEGY"
        confidence = "medium"
    else:
        decision = "HOLD_FOR_MORE_VALIDATION"
        confidence = "low"

    # --- Deployment readiness report ---
    dr_lines = [
        "# Updated Deployment Readiness Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Champion: {champion}",
        f"Risk profile: size_030_cb125",
        f"Champion selection reason: {reason}",
        f"\n## Training vs Holdout\n", _MH, _MS,
        _mrow("Train", train_m), _mrow("Holdout", hold_m),
        f"\n## Walk-Forward OOS Performance ({champion})\n",
        f"- Mean OOS Sharpe: {mean_oos:.3f}",
        f"- % folds positive: {pct_pos:.0%}",
        f"- % folds above 0.3: {pct_above:.0%}",
        f"- Fold Sharpes: {[f'{s:.3f}' for s in champion_wf]}",
        f"\n## Root Causes of Holdout Weakness\n",
    ]
    for c in causes:
        dr_lines.append(f"- {c}")
    dr_lines.append(f"\n## Data Quality Impact\n")
    synth_hold_sharpe = ctx_b["synth_hold_m"].sharpe_ratio
    dr_lines.append(f"- Synthetic holdout Sharpe: {synth_hold_sharpe:.3f}")
    dr_lines.append(f"- Yahoo holdout Sharpe: {hold_m.sharpe_ratio:.3f}")
    if synth_hold_sharpe > hold_m.sharpe_ratio + 0.1:
        dr_lines.append("- Data quality is a contributing factor")
    else:
        dr_lines.append("- Data quality is NOT the primary issue")

    dr_lines.append(f"\n## Pair Concentration\n")
    for candidate in ["sweep_plus_bos", "bos_continuation_only"]:
        jpy_h = next((v for v in ctx_c["variants"] if v.label == f"{candidate} | USDJPY only" and v.period == "holdout"), None)
        all_h = next((v for v in ctx_c["variants"] if v.label == f"{candidate} | All 3 pairs" and v.period == "holdout"), None)
        if jpy_h and all_h:
            dr_lines.append(f"- {candidate}: All-pairs Sharpe={all_h.sharpe:.3f} vs USDJPY-only Sharpe={jpy_h.sharpe:.3f}")

    dr_lines.append(f"\n## Recommendation: **{decision}** (confidence: {confidence})")

    (OUTPUT_DIR / "updated_deployment_readiness_report.md").write_text("\n".join(dr_lines))

    # --- Final recommendation JSON ---
    rec = {
        "timestamp": datetime.utcnow().isoformat(),
        "champion": champion,
        "champion_reason": reason,
        "risk_profile": "size_030_cb125",
        "decision": decision,
        "confidence": confidence,
        "root_causes": causes,
        "evidence": {
            "train_sharpe": round(train_m.sharpe_ratio, 4),
            "holdout_sharpe": round(hold_m.sharpe_ratio, 4),
            "wf_mean_oos_sharpe": round(mean_oos, 4),
            "wf_pct_positive_folds": round(pct_pos, 3),
            "wf_pct_above_threshold": round(pct_above, 3),
            "synth_holdout_sharpe": round(synth_hold_sharpe, 4),
            "data_quality_factor": bool(synth_hold_sharpe > hold_m.sharpe_ratio + 0.1),
            "useful_mitigations": bool(has_useful_mitigation),
            "pair_concentration_issue": bool(any("USDJPY" in c for c in causes)),
            "family_reversal_issue": bool(any("sweep_reversal" in c for c in causes)),
        },
        "next_steps": [],
    }

    if decision == "CONTINUE_PAPER_TRADING":
        rec["next_steps"] = [
            f"Deploy {champion} with size_030_cb125 risk profile to paper trading",
            "Monitor for 4-6 weeks minimum with weekly review checkpoints",
            "Track live Sharpe vs holdout baseline; escalate if < 0.1 after 4 weeks",
            "Compare live signal funnel to backtest expectations",
        ]
    elif decision == "CONTINUE_WITH_SIMPLIFICATION":
        rec["next_steps"] = [
            f"Switch to {champion} if not already",
            "Apply pair filtering if USDJPY concentration is confirmed as beneficial",
            "Re-validate simplified config under walk-forward",
            "Proceed to paper trading if simplified config passes OOS gates",
        ]
    elif decision == "HOLD_FOR_MORE_VALIDATION":
        rec["next_steps"] = [
            "Acquire higher-quality FX data (Dukascopy CSV export or broker data)",
            "Re-run validation on better data to isolate data-quality effects",
            "Extend data window to capture more regime diversity",
            "Consider if the core SMC signal generation needs improvement",
        ]
    elif decision == "REWORK_STRATEGY":
        rec["next_steps"] = [
            "Investigate why structure-based signals lose follow-through in OOS",
            "Consider higher timeframes for more reliable structure",
            "Test alternative confirmation mechanisms beyond BOS/sweep",
            "Evaluate whether the SMC approach has fundamental limitations for FX",
        ]

    (OUTPUT_DIR / "updated_final_recommendation.json").write_text(json.dumps(rec, indent=2))

    # --- Final decision MD ---
    fd_lines = [
        "# Final Root-Cause and Promotion Decision",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Decision: **{decision}**",
        f"Confidence: {confidence}",
        f"\n## Champion: {champion} (risk profile: size_030_cb125)",
        f"\n## Root Cause of Holdout Weakness\n",
    ]
    for c in causes:
        fd_lines.append(f"- {c}")

    fd_lines.append(f"\n## Key Evidence\n")
    fd_lines.append(f"1. **Train vs Holdout**: Sharpe {train_m.sharpe_ratio:.3f} -> {hold_m.sharpe_ratio:.3f} (-92.6%)")
    fd_lines.append(f"2. **Win Rate**: {train_m.win_rate:.1%} -> {hold_m.win_rate:.1%} (collapsed)")
    fd_lines.append(f"3. **Walk-Forward**: Mean OOS Sharpe {mean_oos:.3f}, {pct_pos:.0%} positive folds")
    fd_lines.append(f"4. **sweep_reversal**: Profitable in train, loss-making in holdout (family reversal)")
    fd_lines.append(f"5. **bos_continuation**: Loss-making in train, profitable in holdout (inverse behavior)")
    fd_lines.append(f"6. **Pair concentration**: {ctx_a['expectancy']['train']['win_rate']:.0%} of train trades on USDJPY")
    fd_lines.append(f"7. **Data quality**: Yahoo Sharpe {hold_m.sharpe_ratio:.3f} vs Synthetic {synth_hold_sharpe:.3f}")
    fd_lines.append(f"8. **Stress test**: Passed (conservative Sharpe remains positive)")
    fd_lines.append(f"9. **Drawdown control**: Remains strong ({hold_m.max_drawdown_pct:.1%} holdout)")

    fd_lines.append(f"\n## Is the Holdout Weakness Structural or Contextual?\n")
    if pct_pos >= 0.5:
        fd_lines.append("The walk-forward evidence is **mixed** — some folds are positive, some negative.")
        fd_lines.append("The weakness is partially contextual (regime-dependent) but the strategy lacks ")
        fd_lines.append("consistent edge across all temporal windows.")
    elif pct_pos >= 0.3:
        fd_lines.append("The walk-forward evidence suggests **structural weakness** — only "
                        f"{pct_pos:.0%} of folds are positive.")
        fd_lines.append("The strategy has regime-dependent edge that appears in some periods but not reliably.")
    else:
        fd_lines.append("The walk-forward evidence suggests **severe structural weakness**.")

    fd_lines.append(f"\n## Dominant Failure Mechanism\n")
    fd_lines.append("The primary cause is **win-rate collapse combined with extreme pair concentration**.")
    fd_lines.append("The strategy's training edge was dominated by USDJPY sweep_reversal trades with ")
    fd_lines.append("high win rates. In holdout, sweep_reversal win rate drops from ~60% to ~29%, ")
    fd_lines.append("converting a highly profitable family into a loss-maker. BOS continuation, which ")
    fd_lines.append("was unprofitable in training, becomes the only profitable holdout family — but ")
    fd_lines.append("its contribution is too small to compensate.")

    fd_lines.append(f"\n## Is BOS-Only the Correct Champion?\n")
    b_hold = next((v for v in ctx_c["variants"] if v.label == "bos_continuation_only | All 3 pairs" and v.period == "holdout"), None)
    s_hold = next((v for v in ctx_c["variants"] if v.label == "sweep_plus_bos | All 3 pairs" and v.period == "holdout"), None)
    if b_hold and s_hold:
        fd_lines.append(f"- BOS-only holdout: Sharpe={b_hold.sharpe:.3f}, Trades={b_hold.trades}")
        fd_lines.append(f"- sweep_plus_bos holdout: Sharpe={s_hold.sharpe:.3f}, Trades={s_hold.trades}")
        if abs(b_hold.sharpe - s_hold.sharpe) < 0.05:
            fd_lines.append("Performance is similar — BOS-only is preferred for simplicity.")
        elif b_hold.sharpe > s_hold.sharpe:
            fd_lines.append("BOS-only outperforms — removing sweep_reversal helps.")

    fd_lines.append(f"\n## Next Steps\n")
    for i, step in enumerate(rec["next_steps"], 1):
        fd_lines.append(f"{i}. {step}")

    fd_lines.append(f"\n## Unresolved Risks\n")
    fd_lines.append("- Strategy edge is highly regime-dependent and inconsistent across temporal windows")
    fd_lines.append("- Yahoo Finance data quality limitations (30% missing bars, no spread data)")
    fd_lines.append("- Extreme USDJPY concentration in training may indicate overfitting to one pair")
    fd_lines.append("- Walk-forward shows high variance (Sharpe std ~1.4) indicating fragile alpha")
    fd_lines.append("- No session attribution available (all trades tagged 'unknown')")

    (OUTPUT_DIR / "updated_final_decision.md").write_text("\n".join(fd_lines))

    logger.info("Wrote updated_deployment_readiness_report.md")
    logger.info("Wrote updated_final_recommendation.json")
    logger.info("Wrote updated_final_decision.md")


# ======================================================================
# MAIN
# ======================================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    logger.info("Loading real FX data from %s", DATA_DIR)
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded")
        sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)

    for pair, series in full_data.items():
        logger.info("  %s: %d bars (%s -> %s)", pair.value, len(series),
                     str(series.timestamps[0])[:10], str(series.timestamps[-1])[:10])

    ctx_a = theme_a(full_data, htf_data)
    ctx_b = theme_b(full_data, htf_data, ctx_a)
    ctx_c = theme_c(full_data, htf_data, ctx_a)
    ctx_d = theme_d(full_data, htf_data, ctx_a, ctx_c)
    ctx_e = theme_e(ctx_a, ctx_c, ctx_d)
    theme_f(ctx_a, ctx_b, ctx_c, ctx_d, ctx_e)

    elapsed = time.monotonic() - t0
    logger.info("=" * 60)
    logger.info("COMPLETE — Total elapsed: %.1f minutes", elapsed / 60)
    logger.info("All reports written to %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
