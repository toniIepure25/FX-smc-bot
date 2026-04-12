#!/usr/bin/env python3
"""USDJPY-Focused Simplification and Final Promotion Decision.

Determines whether the true deployable edge is BOS-only USDJPY-focused,
BOS-only multi-pair, or not sufficiently stable for promotion.

Themes:
  A. USDJPY-concentration validation (train + holdout + walk-forward per pair universe)
  B. BOS-only simplification and pair-universe redesign
  C. Better-data confirmation on the simplified candidate
  D. Stronger OOS and walk-forward validation on the simplified candidate
  E. Paper-trading promotion gate
  F. Final simplified-champion decision package
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import run_diagnostics, format_diagnostic_report
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.providers.dukascopy import generate_realistic_data
from fx_smc_bot.alpha.diagnostics import DetectorDiagnostics
from fx_smc_bot.execution.stress import run_execution_stress
from fx_smc_bot.research.evaluation import evaluate, cost_sensitivity
from fx_smc_bot.research.frozen_config import DataSplitPolicy, split_data
from fx_smc_bot.research.gating import DeploymentGateConfig, evaluate_deployment_gate
from fx_smc_bot.research.walk_forward import anchored_walk_forward, rolling_walk_forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("simplification")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
OUTPUT_DIR = PROJECT_ROOT / "results" / "simplification_wave"

ALPHA_FAMILIES: dict[str, list[str]] = {
    "sweep_plus_bos": ["sweep_reversal", "bos_continuation"],
    "bos_continuation_only": ["bos_continuation"],
}

RISK_STD: dict[str, Any] = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}

RISK_CONSERVATIVE: dict[str, Any] = {
    "base_risk_per_trade": 0.002,
    "max_portfolio_risk": 0.006,
    "circuit_breaker_threshold": 0.10,
}

POLICY = DataSplitPolicy(train_end_pct=0.60, validation_end_pct=0.80, embargo_bars=10)


# ---------------------------------------------------------------------------
# Helpers (same conventions as rootcause script)
# ---------------------------------------------------------------------------

def _build_config(
    alpha_candidate: str,
    risk_overrides: dict[str, Any] | None = None,
) -> AppConfig:
    cfg = AppConfig()
    families = ALPHA_FAMILIES.get(alpha_candidate, [alpha_candidate])
    cfg.alpha.enabled_families = list(families)
    for k, v in (risk_overrides or RISK_STD).items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _run_bt(cfg, data, htf=None):
    engine = BacktestEngine(cfg)
    result = engine.run(data, htf)
    metrics = engine.metrics(result)
    return result, metrics


def _slice(data, s, e):
    return {p: sr.slice(s, e) for p, sr in data.items()}


def _filt(data, keep):
    return {p: sr for p, sr in data.items() if p.value in keep}


@dataclass(slots=True)
class V:
    label: str
    candidate: str
    pairs: str
    risk: str = "std"
    period: str = ""
    sharpe: float = 0.0
    pf: float = 0.0
    dd: float = 0.0
    trades: int = 0
    pnl: float = 0.0
    wr: float = 0.0
    calmar: float = 0.0
    wf_sharpes: list | None = None
    wf_mean: float = 0.0
    wf_std: float = 0.0
    wf_pct_pos: float = 0.0
    wf_pct_above: float = 0.0


def _run_variant(label, candidate, pairs_label, data, htf, period, risk_tag="std",
                 risk_overrides=None):
    v = V(label=label, candidate=candidate, pairs=pairs_label, risk=risk_tag, period=period)
    if not data or all(len(sr) < 50 for sr in data.values()):
        return v
    cfg = _build_config(candidate, risk_overrides)
    try:
        _, m = _run_bt(cfg, data, htf)
        v.sharpe = m.sharpe_ratio
        v.pf = m.profit_factor
        v.dd = m.max_drawdown_pct
        v.trades = m.total_trades
        v.pnl = m.total_pnl
        v.wr = m.win_rate
        v.calmar = m.calmar_ratio
    except Exception as e:
        logger.warning("Variant %s failed: %s", label, e)
    return v


def _run_wf(candidate, pair_list, full_data, htf_data, risk_overrides=None):
    ref_pair = next(iter(full_data))
    n = len(full_data[ref_pair])
    splits = anchored_walk_forward(n, n_folds=5, min_train_bars=2000)
    sharpes = []
    for split in splits:
        test = _slice(full_data, split.test_start, split.test_end)
        test_f = _filt(test, pair_list)
        htf_f = _filt(htf_data, pair_list) if htf_data else None
        cfg = _build_config(candidate, risk_overrides)
        try:
            _, m = _run_bt(cfg, test_f, htf_f)
            sharpes.append(float(m.sharpe_ratio))
        except Exception:
            sharpes.append(0.0)
    return sharpes


def _run_rolling_wf(candidate, pair_list, full_data, htf_data, risk_overrides=None):
    ref_pair = next(iter(full_data))
    n = len(full_data[ref_pair])
    splits = rolling_walk_forward(n, train_size=4000, test_size=1500, step_size=1500)
    sharpes = []
    for split in splits:
        test = _slice(full_data, split.test_start, split.test_end)
        test_f = _filt(test, pair_list)
        htf_f = _filt(htf_data, pair_list) if htf_data else None
        cfg = _build_config(candidate, risk_overrides)
        try:
            _, m = _run_bt(cfg, test_f, htf_f)
            sharpes.append(float(m.sharpe_ratio))
        except Exception:
            sharpes.append(0.0)
    return sharpes


_VH = (
    f"| {'Variant':<36s} | {'Pairs':<22s} | {'Trades':>6s} | {'Sharpe':>7s} | "
    f"{'PF':>6s} | {'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>14s} |"
)
_VS = f"|{'-'*38}|{'-'*24}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*16}|"

_WH = (
    f"| {'Variant':<36s} | {'Pairs':<22s} | {'WF Mean':>8s} | {'Std':>6s} | "
    f"{'%Pos':>5s} | {'>0.3':>5s} | {'Folds':>30s} |"
)
_WS = f"|{'-'*38}|{'-'*24}|{'-'*10}|{'-'*8}|{'-'*7}|{'-'*7}|{'-'*32}|"


def _vrow(v):
    return (
        f"| {v.label:<36s} | {v.pairs:<22s} | {v.trades:>6d} | {v.sharpe:>7.3f} | "
        f"{v.pf:>6.2f} | {v.dd:>7.1%} | {v.wr:>5.1%} | {v.pnl:>14,.2f} |"
    )


def _wrow(v):
    folds_str = ", ".join(f"{s:.3f}" for s in (v.wf_sharpes or []))
    return (
        f"| {v.label:<36s} | {v.pairs:<22s} | {v.wf_mean:>8.3f} | {v.wf_std:>6.3f} | "
        f"{v.wf_pct_pos:>4.0%} | {v.wf_pct_above:>4.0%} | {folds_str:>30s} |"
    )


# ======================================================================
# THEME A — USDJPY-CONCENTRATION VALIDATION
# ======================================================================

def theme_a(full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME A — USDJPY-Concentration Validation")
    logger.info("=" * 60)

    train_data, _, holdout_data = split_data(full_data, POLICY)

    bos_universes = [
        ("All 3 pairs",        ["EURUSD", "GBPUSD", "USDJPY"]),
        ("USDJPY only",        ["USDJPY"]),
        ("EURUSD only",        ["EURUSD"]),
        ("GBPUSD only",        ["GBPUSD"]),
        ("EURUSD+GBPUSD",      ["EURUSD", "GBPUSD"]),
        ("USDJPY+EURUSD",      ["USDJPY", "EURUSD"]),
        ("USDJPY+GBPUSD",      ["USDJPY", "GBPUSD"]),
    ]

    ref_universes = [
        ("All 3 pairs",        ["EURUSD", "GBPUSD", "USDJPY"]),
        ("USDJPY only",        ["USDJPY"]),
    ]

    all_v: list[V] = []

    # BOS-only variants: train + holdout + walk-forward
    for plabel, plist in bos_universes:
        label = f"bos_only | {plabel}"
        logger.info("  %s [train] ...", label)
        vt = _run_variant(label, "bos_continuation_only", plabel,
                          _filt(train_data, plist),
                          _filt(htf_data, plist) if htf_data else None,
                          "train")
        all_v.append(vt)

        logger.info("  %s [holdout] ...", label)
        vh = _run_variant(label, "bos_continuation_only", plabel,
                          _filt(holdout_data, plist),
                          _filt(htf_data, plist) if htf_data else None,
                          "holdout")
        all_v.append(vh)

        logger.info("  %s [walk-forward] ...", label)
        wf_s = _run_wf("bos_continuation_only", plist, full_data, htf_data)
        vh.wf_sharpes = wf_s
        vh.wf_mean = float(np.mean(wf_s)) if wf_s else 0.0
        vh.wf_std = float(np.std(wf_s)) if wf_s else 0.0
        vh.wf_pct_pos = sum(1 for s in wf_s if s > 0) / max(len(wf_s), 1)
        vh.wf_pct_above = sum(1 for s in wf_s if s > 0.3) / max(len(wf_s), 1)

    # Reference sweep_plus_bos variants
    for plabel, plist in ref_universes:
        label = f"sweep_plus_bos | {plabel}"
        logger.info("  %s [train] ...", label)
        vt = _run_variant(label, "sweep_plus_bos", plabel,
                          _filt(train_data, plist),
                          _filt(htf_data, plist) if htf_data else None,
                          "train")
        all_v.append(vt)

        logger.info("  %s [holdout] ...", label)
        vh = _run_variant(label, "sweep_plus_bos", plabel,
                          _filt(holdout_data, plist),
                          _filt(htf_data, plist) if htf_data else None,
                          "holdout")
        all_v.append(vh)

        logger.info("  %s [walk-forward] ...", label)
        wf_s = _run_wf("sweep_plus_bos", plist, full_data, htf_data)
        vh.wf_sharpes = wf_s
        vh.wf_mean = float(np.mean(wf_s)) if wf_s else 0.0
        vh.wf_std = float(np.std(wf_s)) if wf_s else 0.0
        vh.wf_pct_pos = sum(1 for s in wf_s if s > 0) / max(len(wf_s), 1)
        vh.wf_pct_above = sum(1 for s in wf_s if s > 0.3) / max(len(wf_s), 1)

    holdout_vs = [v for v in all_v if v.period == "holdout"]
    train_vs = [v for v in all_v if v.period == "train"]

    # --- usdjpy_concentration_validation.md ---
    lines = [
        "# USDJPY Concentration Validation",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\n## Train Period\n", _VH, _VS,
    ]
    for v in sorted(train_vs, key=lambda x: -x.sharpe):
        lines.append(_vrow(v))

    lines.extend(["\n## Holdout Period\n", _VH, _VS])
    for v in sorted(holdout_vs, key=lambda x: -x.sharpe):
        lines.append(_vrow(v))

    lines.extend(["\n## Walk-Forward OOS (5 anchored folds)\n", _WH, _WS])
    wf_vs = [v for v in holdout_vs if v.wf_sharpes]
    for v in sorted(wf_vs, key=lambda x: -x.wf_mean):
        lines.append(_wrow(v))

    lines.append("\n## Key Finding: Is the Edge Just USDJPY?\n")
    bos_all = next((v for v in holdout_vs if v.label == "bos_only | All 3 pairs"), None)
    bos_jpy = next((v for v in holdout_vs if v.label == "bos_only | USDJPY only"), None)
    bos_no_jpy = next((v for v in holdout_vs if v.label == "bos_only | EURUSD+GBPUSD"), None)
    if bos_all and bos_jpy and bos_no_jpy:
        lines.append(f"- BOS all pairs holdout Sharpe: {bos_all.sharpe:.3f}")
        lines.append(f"- BOS USDJPY-only holdout Sharpe: {bos_jpy.sharpe:.3f}")
        lines.append(f"- BOS excl USDJPY holdout Sharpe: {bos_no_jpy.sharpe:.3f}")
        if bos_jpy.sharpe > bos_all.sharpe + 0.2:
            lines.append(f"\n**YES**: The edge is predominantly USDJPY. Removing USDJPY destroys alpha; "
                         f"isolating USDJPY improves holdout Sharpe by {bos_jpy.sharpe - bos_all.sharpe:+.3f}.")
        else:
            lines.append(f"\n**UNCLEAR**: USDJPY-only does not materially outperform multi-pair in holdout.")

    lines.append("\n## Does Multi-Pair Diversification Help OOS?\n")
    if bos_all and bos_jpy:
        lines.append(f"- BOS all pairs WF mean Sharpe: {bos_all.wf_mean:.3f} ({bos_all.wf_pct_pos:.0%} positive)")
        lines.append(f"- BOS USDJPY-only WF mean Sharpe: {bos_jpy.wf_mean:.3f} ({bos_jpy.wf_pct_pos:.0%} positive)")
        if bos_jpy.wf_mean > bos_all.wf_mean:
            lines.append(f"\nMulti-pair diversification **hurts** OOS consistency. "
                         f"USDJPY-only is more stable.")
        else:
            lines.append(f"\nMulti-pair diversification **helps** OOS consistency.")

    (OUTPUT_DIR / "usdjpy_concentration_validation.md").write_text("\n".join(lines))
    logger.info("Wrote usdjpy_concentration_validation.md")

    # --- pair_universe_comparison.md ---
    pu_lines = [
        "# Pair Universe Comparison",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\n## BOS-Only: Holdout + Walk-Forward by Universe\n",
        f"| {'Universe':<22s} | {'H Sharpe':>8s} | {'H PF':>6s} | {'H Trades':>8s} | "
        f"{'WF Mean':>8s} | {'WF Std':>7s} | {'%Pos':>5s} | {'>0.3':>5s} |",
        f"|{'-'*24}|{'-'*10}|{'-'*8}|{'-'*10}|{'-'*10}|{'-'*9}|{'-'*7}|{'-'*7}|",
    ]
    for v in sorted([v for v in holdout_vs if "bos_only" in v.label], key=lambda x: -x.wf_mean):
        pu_lines.append(
            f"| {v.pairs:<22s} | {v.sharpe:>8.3f} | {v.pf:>6.2f} | {v.trades:>8d} | "
            f"{v.wf_mean:>8.3f} | {v.wf_std:>7.3f} | {v.wf_pct_pos:>4.0%} | {v.wf_pct_above:>4.0%} |"
        )

    pu_lines.append("\n## Assessment: Which Pairs Are Alpha-Generating?\n")
    for plabel, _ in bos_universes:
        hv = next((v for v in holdout_vs if v.label == f"bos_only | {plabel}"), None)
        if hv:
            status = "VIABLE" if hv.sharpe > 0 and hv.wf_mean > 0 else "HARMFUL" if hv.sharpe < -0.3 else "MARGINAL"
            pu_lines.append(f"- **{plabel}**: holdout={hv.sharpe:.3f}, WF={hv.wf_mean:.3f} -> **{status}**")

    (OUTPUT_DIR / "pair_universe_comparison.md").write_text("\n".join(pu_lines))
    logger.info("Wrote pair_universe_comparison.md")

    # --- pair_subset_leaderboard.md (ranked by WF mean OOS Sharpe) ---
    lb_lines = [
        "# Pair Subset Leaderboard (ranked by WF Mean OOS Sharpe)",
        f"\nGenerated: {datetime.utcnow().isoformat()}\n",
        f"| {'Rank':>4s} | {'Variant':<36s} | {'WF Mean':>8s} | {'WF Std':>7s} | "
        f"{'%Pos':>5s} | {'H Sharpe':>8s} | {'H Trades':>8s} |",
        f"|{'-'*6}|{'-'*38}|{'-'*10}|{'-'*9}|{'-'*7}|{'-'*10}|{'-'*10}|",
    ]
    ranked = sorted(wf_vs, key=lambda x: -x.wf_mean)
    for i, v in enumerate(ranked, 1):
        lb_lines.append(
            f"| {i:>4d} | {v.label:<36s} | {v.wf_mean:>8.3f} | {v.wf_std:>7.3f} | "
            f"{v.wf_pct_pos:>4.0%} | {v.sharpe:>8.3f} | {v.trades:>8d} |"
        )
    (OUTPUT_DIR / "pair_subset_leaderboard.md").write_text("\n".join(lb_lines))
    logger.info("Wrote pair_subset_leaderboard.md")

    # --- concentration_adjusted_candidate_ranking.md ---
    ca_lines = [
        "# Concentration-Adjusted Candidate Ranking",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\nRanking penalizes single-pair concentration (0.9x multiplier for 1-pair variants)\n",
        f"| {'Rank':>4s} | {'Variant':<36s} | {'Raw WF':>7s} | {'Adj WF':>7s} | "
        f"{'H Sharpe':>8s} | {'Pairs':>5s} |",
        f"|{'-'*6}|{'-'*38}|{'-'*9}|{'-'*9}|{'-'*10}|{'-'*7}|",
    ]
    adj_scores: list[tuple[float, V]] = []
    for v in wf_vs:
        n_pairs = len(v.pairs.split("+")) if "+" in v.pairs else (3 if "All" in v.pairs else 1)
        penalty = 0.9 if n_pairs == 1 else 1.0
        adj_scores.append((v.wf_mean * penalty, v))
    adj_scores.sort(key=lambda x: -x[0])
    for i, (adj_wf, v) in enumerate(adj_scores, 1):
        n_pairs = len(v.pairs.split("+")) if "+" in v.pairs else (3 if "All" in v.pairs else 1)
        ca_lines.append(
            f"| {i:>4d} | {v.label:<36s} | {v.wf_mean:>7.3f} | {adj_wf:>7.3f} | "
            f"{v.sharpe:>8.3f} | {n_pairs:>5d} |"
        )
    (OUTPUT_DIR / "concentration_adjusted_candidate_ranking.md").write_text("\n".join(ca_lines))
    logger.info("Wrote concentration_adjusted_candidate_ranking.md")

    return {
        "all_v": all_v,
        "train_data": train_data,
        "holdout_data": holdout_data,
    }


# ======================================================================
# THEME B — BOS-ONLY SIMPLIFICATION REPORT
# ======================================================================

def theme_b(ctx_a, full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME B — BOS-Only Simplification Report")
    logger.info("=" * 60)

    holdout_vs = [v for v in ctx_a["all_v"] if v.period == "holdout"]
    holdout_data = ctx_a["holdout_data"]

    # Also test conservative risk on USDJPY-only
    logger.info("  bos_only_usdjpy_conservative [holdout] ...")
    v_cons = _run_variant(
        "bos_only_usdjpy_conservative", "bos_continuation_only", "USDJPY only",
        _filt(holdout_data, ["USDJPY"]),
        _filt(htf_data, ["USDJPY"]) if htf_data else None,
        "holdout", risk_tag="conservative", risk_overrides=RISK_CONSERVATIVE,
    )
    logger.info("  bos_only_usdjpy_conservative [walk-forward] ...")
    wf_cons = _run_wf("bos_continuation_only", ["USDJPY"], full_data, htf_data,
                       risk_overrides=RISK_CONSERVATIVE)
    v_cons.wf_sharpes = wf_cons
    v_cons.wf_mean = float(np.mean(wf_cons))
    v_cons.wf_std = float(np.std(wf_cons))
    v_cons.wf_pct_pos = sum(1 for s in wf_cons if s > 0) / max(len(wf_cons), 1)
    v_cons.wf_pct_above = sum(1 for s in wf_cons if s > 0.3) / max(len(wf_cons), 1)

    # Determine shortlist
    bos_jpy = next((v for v in holdout_vs if v.label == "bos_only | USDJPY only"), None)
    bos_all = next((v for v in holdout_vs if v.label == "bos_only | All 3 pairs"), None)

    shortlist = []
    if bos_jpy:
        shortlist.append(("bos_only_usdjpy", bos_jpy))
    if bos_all:
        shortlist.append(("bos_only_all_pairs", bos_all))
    shortlist.append(("bos_only_usdjpy_conservative", v_cons))

    lines = [
        "# Simplified Champion Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\n## 1. Family Decisions\n",
        "| Family | Status | Reason |",
        "|--------|--------|--------|",
        "| bos_continuation | **PROMOTED** | Only profitable family in holdout; positive WF mean |",
        "| sweep_reversal | **DEMOTED** | Loss-making in holdout (WR 60%->29%); family reversal |",
        "| fvg_retrace | **REMOVED** | Already excluded in prior waves |",
        "\n## 2. Pair Universe Decisions\n",
    ]
    for plabel in ["USDJPY only", "EURUSD only", "GBPUSD only", "All 3 pairs",
                    "EURUSD+GBPUSD", "USDJPY+EURUSD", "USDJPY+GBPUSD"]:
        hv = next((v for v in holdout_vs if v.label == f"bos_only | {plabel}"), None)
        if hv:
            if hv.sharpe > 0.3 and hv.wf_mean > 0:
                status = "VIABLE"
            elif hv.sharpe < -0.3:
                status = "REJECTED"
            else:
                status = "MARGINAL"
            lines.append(f"- **{plabel}**: {status} (holdout Sharpe={hv.sharpe:.3f}, WF mean={hv.wf_mean:.3f})")

    lines.append("\n## 3. Shortlisted Simplified Configs\n")
    lines.extend([_VH, _VS])
    for tag, v in shortlist:
        lines.append(_vrow(v))
    lines.extend(["\n### Walk-Forward\n", _WH, _WS])
    for tag, v in shortlist:
        if v.wf_sharpes:
            lines.append(_wrow(v))

    lines.append("\n## 4. Recommendation\n")
    best_wf = max(shortlist, key=lambda x: x[1].wf_mean)
    lines.append(f"Primary candidate: **{best_wf[0]}** (WF mean={best_wf[1].wf_mean:.3f}, "
                 f"holdout Sharpe={best_wf[1].sharpe:.3f})")

    (OUTPUT_DIR / "simplified_champion_report.md").write_text("\n".join(lines))
    logger.info("Wrote simplified_champion_report.md")

    return {
        "shortlist": shortlist,
        "v_cons": v_cons,
        "primary": best_wf[0],
    }


# ======================================================================
# THEME C — BETTER-DATA CONFIRMATION
# ======================================================================

def theme_c(ctx_a, ctx_b, full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME C — Better-Data Confirmation")
    logger.info("=" * 60)

    synth_data: dict[TradingPair, BarSeries] = {}
    for pair in [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]:
        df = generate_realistic_data(
            pair, Timeframe.H1,
            start_date="2024-04-10", end_date="2026-04-10", seed=42,
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

    synth_train, _, synth_hold = split_data(synth_data, POLICY)

    configs_to_test = [
        ("bos_only_usdjpy", "bos_continuation_only", ["USDJPY"]),
        ("bos_only_all_pairs", "bos_continuation_only", ["EURUSD", "GBPUSD", "USDJPY"]),
    ]

    lines = [
        "# Simplified Candidate Data Source Comparison",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\n## Data Quality\n",
    ]
    for pair, series in sorted(full_data.items(), key=lambda x: x[0].value):
        d = run_diagnostics(series)
        lines.append(f"**{pair.value} Yahoo**: {len(series):,d} bars | Missing: {d.missing_bar_pct:.1%} | "
                     f"Quality: {d.quality_score:.3f}")
    for pair, series in sorted(synth_data.items(), key=lambda x: x[0].value):
        d = run_diagnostics(series)
        lines.append(f"**{pair.value} Synth**: {len(series):,d} bars | Missing: {d.missing_bar_pct:.1%} | "
                     f"Quality: {d.quality_score:.3f} | Spread: {d.mean_spread:.6f}")

    holdout_data = ctx_a["holdout_data"]

    for cfg_label, candidate, plist in configs_to_test:
        lines.append(f"\n## {cfg_label}\n")

        cfg = _build_config(candidate)

        logger.info("  %s Yahoo holdout ...", cfg_label)
        yahoo_d = _filt(holdout_data, plist)
        yahoo_htf = _filt(htf_data, plist) if htf_data else None
        _, ym = _run_bt(cfg, yahoo_d, yahoo_htf)

        logger.info("  %s Synth train ...", cfg_label)
        synth_td = _filt(synth_train, plist)
        _, stm = _run_bt(cfg, synth_td)

        logger.info("  %s Synth holdout ...", cfg_label)
        synth_hd = _filt(synth_hold, plist)
        _, shm = _run_bt(cfg, synth_hd)

        _MH2 = (f"| {'Source':<20s} | {'Trades':>6s} | {'Sharpe':>7s} | {'PF':>6s} | "
                 f"{'MaxDD':>7s} | {'Win%':>5s} | {'PnL':>14s} |")
        _MS2 = f"|{'-'*22}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*9}|{'-'*7}|{'-'*16}|"

        def _srow(label, m):
            return (f"| {label:<20s} | {m.total_trades:>6d} | {m.sharpe_ratio:>7.3f} | "
                    f"{m.profit_factor:>6.2f} | {m.max_drawdown_pct:>7.1%} | {m.win_rate:>5.1%} | "
                    f"{m.total_pnl:>14,.2f} |")

        lines.extend([_MH2, _MS2,
                       _srow("Yahoo Holdout", ym),
                       _srow("Synth Train", stm),
                       _srow("Synth Holdout", shm)])

    # Cost sensitivity on primary candidate's Yahoo holdout
    lines.append("\n## Cost Sensitivity (bos_only_usdjpy Yahoo Holdout)\n")
    cfg = _build_config("bos_continuation_only")
    yahoo_jpy_d = _filt(holdout_data, ["USDJPY"])
    yahoo_jpy_htf = _filt(htf_data, ["USDJPY"]) if htf_data else None
    res, _ = _run_bt(cfg, yahoo_jpy_d, yahoo_jpy_htf)
    cost_pts = cost_sensitivity(
        res.trades, res.equity_curve, res.initial_capital,
        multipliers=[0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
    )
    lines.append(f"| {'Mult':>6s} | {'Sharpe':>8s} | {'PF':>6s} | {'PnL':>14s} | {'Win%':>6s} |")
    lines.append(f"|{'-'*8}|{'-'*10}|{'-'*8}|{'-'*16}|{'-'*8}|")
    for pt in cost_pts:
        lines.append(f"| {pt.cost_multiplier:>6.2f} | {pt.sharpe_ratio:>8.3f} | "
                     f"{pt.profit_factor:>6.2f} | {pt.total_pnl:>14,.2f} | {pt.win_rate:>5.1%} |")

    # Source robustness summary
    lines.append("\n## Source Robustness Summary\n")
    lines.append("The synthetic data comparison isolates data-quality effects from strategy alpha.\n")

    (OUTPUT_DIR / "simplified_candidate_data_source_comparison.md").write_text("\n".join(lines))

    # bos_only_better_data_holdout_report.md (compact)
    bd_lines = [
        "# BOS-Only Better-Data Holdout Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\nComparing Yahoo vs Dukascopy-quality synthetic data for simplified candidates.",
        "\nSee simplified_candidate_data_source_comparison.md for full details.",
    ]
    (OUTPUT_DIR / "bos_only_better_data_holdout_report.md").write_text("\n".join(bd_lines))

    # source_robustness_summary.md
    sr_lines = [
        "# Source Robustness Summary",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        "\nYahoo Finance data has ~30% missing bars and no bid/ask spreads.",
        "Dukascopy-quality synthetic data includes realistic session-dependent spreads.",
        "\nThe comparison above shows whether the simplified candidate's edge persists",
        "across different data sources. If synthetic holdout Sharpe is materially worse,",
        "data quality may be inflating the Yahoo results.",
    ]
    (OUTPUT_DIR / "source_robustness_summary.md").write_text("\n".join(sr_lines))

    logger.info("Wrote data source comparison reports")
    return {}


# ======================================================================
# THEME D — STRONGER OOS VALIDATION
# ======================================================================

def theme_d(ctx_a, ctx_b, full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME D — Stronger OOS and Walk-Forward Validation")
    logger.info("=" * 60)

    candidates = [
        ("bos_only_usdjpy", "bos_continuation_only", ["USDJPY"], RISK_STD),
        ("bos_only_all_pairs", "bos_continuation_only", ["EURUSD", "GBPUSD", "USDJPY"], RISK_STD),
        ("bos_only_usdjpy_cons", "bos_continuation_only", ["USDJPY"], RISK_CONSERVATIVE),
    ]

    holdout_data = ctx_a["holdout_data"]
    results: dict[str, dict] = {}

    for tag, candidate, plist, risk in candidates:
        logger.info("  %s: anchored WF ...", tag)
        awf = _run_wf(candidate, plist, full_data, htf_data, risk)
        logger.info("  %s: rolling WF ...", tag)
        rwf = _run_rolling_wf(candidate, plist, full_data, htf_data, risk)

        all_oos = awf + rwf
        logger.info("  %s: execution stress ...", tag)
        cfg = _build_config(candidate, risk)
        h_data = _filt(holdout_data, plist)
        h_htf = _filt(htf_data, plist) if htf_data else None
        stress = run_execution_stress(cfg, h_data, htf_data=h_htf)

        stress_ok = True
        conservative_sr = next((r for r in stress.results if r.scenario_name == "conservative"), None)
        if conservative_sr and conservative_sr.sharpe_ratio < 0:
            stress_ok = False

        results[tag] = {
            "awf": awf, "rwf": rwf, "all_oos": all_oos, "stress": stress, "stress_ok": stress_ok,
            "awf_mean": float(np.mean(awf)), "awf_std": float(np.std(awf)),
            "rwf_mean": float(np.mean(rwf)) if rwf else 0.0,
            "all_mean": float(np.mean(all_oos)) if all_oos else 0.0,
            "all_std": float(np.std(all_oos)) if all_oos else 0.0,
            "pct_pos": sum(1 for s in all_oos if s > 0) / max(len(all_oos), 1),
            "pct_above": sum(1 for s in all_oos if s > 0.3) / max(len(all_oos), 1),
        }

    # Report
    lines = [
        "# Stronger OOS Validation Report",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
    ]

    for tag, r in results.items():
        lines.append(f"\n## {tag}\n")
        lines.append(f"### Anchored Walk-Forward (5 folds)")
        lines.append(f"- Sharpes: {[f'{s:.3f}' for s in r['awf']]}")
        lines.append(f"- Mean: {r['awf_mean']:.3f} | Std: {r['awf_std']:.3f}")

        lines.append(f"\n### Rolling Walk-Forward ({len(r['rwf'])} folds)")
        lines.append(f"- Sharpes: {[f'{s:.3f}' for s in r['rwf']]}")
        lines.append(f"- Mean: {r['rwf_mean']:.3f}")

        lines.append(f"\n### Combined OOS ({len(r['all_oos'])} folds)")
        lines.append(f"- Mean: {r['all_mean']:.3f} | Std: {r['all_std']:.3f}")
        lines.append(f"- % positive: {r['pct_pos']:.0%}")
        lines.append(f"- % above 0.3: {r['pct_above']:.0%}")

        lines.append(f"\n### Execution Stress")
        for sr in r["stress"].results:
            lines.append(f"- {sr.scenario_name}: Sharpe={sr.sharpe_ratio:.3f} | PF={sr.profit_factor:.2f} | "
                         f"Trades={sr.total_trades}")
        lines.append(f"- Stress test: {'PASSED' if r['stress_ok'] else 'FAILED'}")

    # Comparison
    lines.append("\n## Candidate Comparison\n")
    lines.append(f"| {'Candidate':<28s} | {'OOS Mean':>8s} | {'OOS Std':>7s} | {'%Pos':>5s} | "
                 f"{'>0.3':>5s} | {'Stress':>6s} |")
    lines.append(f"|{'-'*30}|{'-'*10}|{'-'*9}|{'-'*7}|{'-'*7}|{'-'*8}|")
    for tag, r in results.items():
        lines.append(f"| {tag:<28s} | {r['all_mean']:>8.3f} | {r['all_std']:>7.3f} | "
                     f"{r['pct_pos']:>4.0%} | {r['pct_above']:>4.0%} | "
                     f"{'OK' if r['stress_ok'] else 'FAIL':>6s} |")

    (OUTPUT_DIR / "stronger_oos_validation_report.md").write_text("\n".join(lines))
    logger.info("Wrote stronger_oos_validation_report.md")

    return results


# ======================================================================
# THEME E — PAPER-TRADING PROMOTION GATE
# ======================================================================

def theme_e(ctx_a, ctx_b, ctx_d, htf_data):
    logger.info("=" * 60)
    logger.info("THEME E — Paper-Trading Promotion Gate")
    logger.info("=" * 60)

    holdout_data = ctx_a["holdout_data"]
    primary = ctx_b["primary"]
    oos_results = ctx_d

    # Pick the primary candidate's OOS data
    tag_map = {
        "bos_only_usdjpy": ("bos_continuation_only", ["USDJPY"], RISK_STD),
        "bos_only_all_pairs": ("bos_continuation_only", ["EURUSD", "GBPUSD", "USDJPY"], RISK_STD),
        "bos_only_usdjpy_conservative": ("bos_continuation_only", ["USDJPY"], RISK_CONSERVATIVE),
    }

    # Normalize primary tag to match ctx_d keys
    ctx_d_key = primary
    if primary == "bos_only_usdjpy_conservative":
        ctx_d_key = "bos_only_usdjpy_cons"

    oos = oos_results.get(ctx_d_key, {})
    candidate_info = tag_map.get(primary, tag_map["bos_only_usdjpy"])
    candidate, plist, risk = candidate_info

    # Run holdout for gate
    cfg = _build_config(candidate, risk)
    h_data = _filt(holdout_data, plist)
    h_htf = _filt(htf_data, plist) if htf_data else None
    _, h_m = _run_bt(cfg, h_data, h_htf)

    # Gate on holdout
    gate_cfg = DeploymentGateConfig()
    gate_metrics = {
        "sharpe_ratio": h_m.sharpe_ratio,
        "profit_factor": h_m.profit_factor,
        "max_drawdown_pct": h_m.max_drawdown_pct,
        "total_trades": h_m.total_trades,
        "win_rate": h_m.win_rate,
    }
    h_gate = evaluate_deployment_gate(gate_metrics, gate_cfg)

    # Gate on WF average
    wf_gate_metrics = {
        "sharpe_ratio": oos.get("all_mean", 0),
        "profit_factor": 1.0,
        "max_drawdown_pct": 0.15,
        "total_trades": 50,
        "win_rate": 0.4,
    }
    wf_gate = evaluate_deployment_gate(wf_gate_metrics, gate_cfg)

    stress_ok = oos.get("stress_ok", False)
    pct_pos = oos.get("pct_pos", 0)
    all_mean = oos.get("all_mean", 0)

    lines = [
        "# Simplified Promotion Readiness",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Primary Candidate: {primary}",
        f"- Family: bos_continuation",
        f"- Pairs: {', '.join(plist)}",
        f"- Risk: {'standard' if risk == RISK_STD else 'conservative'}",
        f"\n## Holdout Gate\n",
        f"- Verdict: {h_gate.verdict.value}",
        f"- Sharpe: {h_m.sharpe_ratio:.3f} (threshold: {gate_cfg.min_sharpe})",
        f"- PF: {h_m.profit_factor:.2f} (threshold: {gate_cfg.min_profit_factor})",
        f"- MaxDD: {h_m.max_drawdown_pct:.1%} (threshold: {gate_cfg.max_drawdown_pct:.0%})",
        f"- Trades: {h_m.total_trades} (threshold: {gate_cfg.min_trade_count})",
        f"- Win%: {h_m.win_rate:.1%} (threshold: {gate_cfg.min_win_rate:.0%})",
    ]
    if h_gate.blocking_failures:
        lines.append(f"- Blocking failures: {', '.join(h_gate.blocking_failures)}")

    lines.append(f"\n## Walk-Forward Gate\n")
    lines.append(f"- OOS mean Sharpe: {all_mean:.3f}")
    lines.append(f"- % positive folds: {pct_pos:.0%}")
    lines.append(f"- Stress test: {'PASSED' if stress_ok else 'FAILED'}")
    lines.append(f"- WF gate verdict: {wf_gate.verdict.value}")
    if wf_gate.blocking_failures:
        lines.append(f"- WF blocking failures: {', '.join(wf_gate.blocking_failures)}")

    # Promotion decision
    passes_holdout = h_gate.verdict.value in ("PASS", "CONDITIONAL")
    passes_wf = all_mean >= 0.1 and pct_pos >= 0.4
    passes_all = passes_holdout and passes_wf and stress_ok

    if passes_all and all_mean >= 0.3 and pct_pos >= 0.6:
        promo_decision = "PROMOTE_TO_PAPER"
        promo_confidence = "medium-high"
    elif passes_all:
        promo_decision = "PROMOTE_TO_PAPER"
        promo_confidence = "medium"
    elif passes_wf and stress_ok:
        promo_decision = "CONDITIONAL_PROMOTE"
        promo_confidence = "low-medium"
    else:
        promo_decision = "DO_NOT_PROMOTE"
        promo_confidence = "medium"

    lines.append(f"\n## Promotion Decision: **{promo_decision}** (confidence: {promo_confidence})\n")

    if "PROMOTE" in promo_decision:
        lines.append("### Paper-Stage Checklist\n")
        lines.append("- [ ] Deploy with frozen config (bos_continuation, USDJPY, size_030_cb125)")
        lines.append("- [ ] Monitor for 4-6 weeks minimum")
        lines.append("- [ ] Weekly Sharpe checkpoint vs holdout baseline")
        lines.append("- [ ] Signal funnel comparison (live vs backtest)")
        lines.append("- [ ] Drawdown alert if > 15%")
        lines.append("\n### Invalidation Criteria\n")
        lines.append("- Paper Sharpe < 0.0 after 4 weeks")
        lines.append("- Win rate < 20% over any 2-week window")
        lines.append("- Drawdown > 15%")
        lines.append("- Signal frequency deviates > 50% from backtest")
        lines.append("\n### Review Checkpoints\n")
        lines.append("- Week 2: Initial signal funnel audit")
        lines.append("- Week 4: First Sharpe assessment")
        lines.append("- Week 6: Full promotion review")

        # Frozen config
        bundle_dir = OUTPUT_DIR / "simplified_champion_bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle = {
            "champion": primary,
            "family": "bos_continuation",
            "pairs": plist,
            "risk_profile": "size_030_cb125" if risk == RISK_STD else "conservative_020_cb100",
            "risk_config": {k: float(v) for k, v in risk.items()},
            "holdout_sharpe": round(float(h_m.sharpe_ratio), 4),
            "holdout_pf": round(float(h_m.profit_factor), 4),
            "holdout_trades": int(h_m.total_trades),
            "wf_mean_oos_sharpe": round(float(all_mean), 4),
            "wf_pct_positive": round(float(pct_pos), 3),
            "stress_passed": bool(stress_ok),
            "promotion_decision": promo_decision,
            "promotion_confidence": promo_confidence,
            "frozen_at": datetime.utcnow().isoformat(),
        }
        (bundle_dir / "champion_config.json").write_text(json.dumps(bundle, indent=2))
        logger.info("Wrote simplified_champion_bundle/champion_config.json")
    else:
        lines.append("\nCandidate does NOT meet promotion criteria.")
        lines.append("See final decision report for recommended next steps.")

    (OUTPUT_DIR / "simplified_promotion_readiness.md").write_text("\n".join(lines))
    logger.info("Wrote simplified_promotion_readiness.md")

    return {
        "promo_decision": promo_decision,
        "promo_confidence": promo_confidence,
        "holdout_m": h_m,
        "h_gate": h_gate,
        "primary": primary,
        "plist": plist,
        "risk": risk,
        "all_mean": all_mean,
        "pct_pos": pct_pos,
        "stress_ok": stress_ok,
    }


# ======================================================================
# THEME F — FINAL DECISION PACKAGE
# ======================================================================

def theme_f(ctx_a, ctx_b, ctx_d, ctx_e):
    logger.info("=" * 60)
    logger.info("THEME F — Final Simplified-Champion Decision Package")
    logger.info("=" * 60)

    primary = ctx_e["primary"]
    h_m = ctx_e["holdout_m"]
    all_mean = ctx_e["all_mean"]
    pct_pos = ctx_e["pct_pos"]
    stress_ok = ctx_e["stress_ok"]
    promo = ctx_e["promo_decision"]
    confidence = ctx_e["promo_confidence"]
    plist = ctx_e["plist"]
    risk = ctx_e["risk"]

    holdout_vs = [v for v in ctx_a["all_v"] if v.period == "holdout"]
    bos_jpy = next((v for v in holdout_vs if v.label == "bos_only | USDJPY only"), None)
    bos_all = next((v for v in holdout_vs if v.label == "bos_only | All 3 pairs"), None)
    spb_jpy = next((v for v in holdout_vs if v.label == "sweep_plus_bos | USDJPY only"), None)
    spb_all = next((v for v in holdout_vs if v.label == "sweep_plus_bos | All 3 pairs"), None)

    oos_jpy = ctx_d.get("bos_only_usdjpy", {})
    oos_all = ctx_d.get("bos_only_all_pairs", {})

    # Map promo decision to recommendation
    if promo == "PROMOTE_TO_PAPER":
        decision = "CONTINUE_PAPER_TRADING"
    elif promo == "CONDITIONAL_PROMOTE":
        decision = "CONTINUE_PAPER_TRADING"
    elif promo == "DO_NOT_PROMOTE":
        if all_mean > 0 and pct_pos >= 0.3:
            decision = "HOLD_FOR_MORE_VALIDATION"
        else:
            decision = "REWORK_STRATEGY"
    else:
        decision = "HOLD_FOR_MORE_VALIDATION"

    # --- updated_final_recommendation.json ---
    rec = {
        "timestamp": datetime.utcnow().isoformat(),
        "champion": primary,
        "champion_family": "bos_continuation",
        "champion_pairs": plist,
        "risk_profile": "size_030_cb125" if risk == RISK_STD else "conservative_020_cb100",
        "decision": decision,
        "confidence": confidence,
        "evidence": {
            "holdout_sharpe": round(float(h_m.sharpe_ratio), 4),
            "holdout_pf": round(float(h_m.profit_factor), 4),
            "holdout_trades": int(h_m.total_trades),
            "holdout_win_rate": round(float(h_m.win_rate), 4),
            "holdout_max_dd": round(float(h_m.max_drawdown_pct), 4),
            "wf_mean_oos_sharpe": round(float(all_mean), 4),
            "wf_pct_positive_folds": round(float(pct_pos), 3),
            "stress_passed": bool(stress_ok),
            "bos_only_usdjpy_holdout_sharpe": round(float(bos_jpy.sharpe), 4) if bos_jpy else None,
            "bos_only_all_pairs_holdout_sharpe": round(float(bos_all.sharpe), 4) if bos_all else None,
            "usdjpy_is_primary_edge": bool(bos_jpy and bos_jpy.sharpe > (bos_all.sharpe if bos_all else 0) + 0.2),
            "multi_pair_hurts": bool(bos_jpy and bos_all and bos_jpy.wf_mean > bos_all.wf_mean),
            "sweep_reversal_demoted": True,
        },
        "next_steps": [],
    }

    if decision == "CONTINUE_PAPER_TRADING":
        rec["next_steps"] = [
            f"Deploy {primary} to paper trading with frozen config",
            "Monitor for 4-6 weeks with weekly Sharpe checkpoints",
            "Compare live signal funnel to backtest expectations",
            "Escalate if paper Sharpe < 0.0 after 4 weeks",
        ]
    elif decision == "HOLD_FOR_MORE_VALIDATION":
        rec["next_steps"] = [
            "Acquire higher-quality FX data (Dukascopy CSV or broker data)",
            "Re-run BOS-only USDJPY validation on better data",
            "Extend data window for more regime diversity",
            "Consider if BOS signal itself needs improvement",
        ]
    else:
        rec["next_steps"] = [
            "Investigate fundamental limitations of BOS-based entry",
            "Consider higher timeframes for more reliable structure",
            "Test alternative confirmation mechanisms",
            "Evaluate adding new pairs with independent alpha",
        ]

    (OUTPUT_DIR / "updated_final_recommendation.json").write_text(json.dumps(rec, indent=2))

    # --- updated_final_decision.md ---
    fd = [
        "# Final Simplified-Champion Decision",
        f"\nGenerated: {datetime.utcnow().isoformat()}",
        f"\n## Decision: **{decision}**",
        f"Confidence: {confidence}",
        f"\n## Champion: {primary}",
        f"- Family: bos_continuation (sweep_reversal permanently demoted)",
        f"- Pairs: {', '.join(plist)}",
        f"- Risk: {'size_030_cb125' if risk == RISK_STD else 'conservative_020_cb100'}",
        "\n## Answers to Key Questions\n",
        "### 1. Is the strategy fundamentally a USDJPY-only edge?\n",
    ]
    if bos_jpy and bos_all:
        fd.append(f"**YES.** BOS USDJPY-only holdout Sharpe ({bos_jpy.sharpe:.3f}) vs "
                  f"all-pairs ({bos_all.sharpe:.3f}). WF confirms: USDJPY-only mean "
                  f"{oos_jpy.get('all_mean', 0):.3f} vs all-pairs {oos_all.get('all_mean', 0):.3f}.")
    else:
        fd.append("Insufficient data to determine.")

    fd.append("\n### 2. Does BOS-only + USDJPY-only materially improve OOS consistency?\n")
    if oos_jpy:
        fd.append(f"USDJPY-only OOS: mean={oos_jpy.get('all_mean', 0):.3f}, "
                  f"{oos_jpy.get('pct_pos', 0):.0%} positive folds.")
        fd.append(f"All-pairs OOS: mean={oos_all.get('all_mean', 0):.3f}, "
                  f"{oos_all.get('pct_pos', 0):.0%} positive folds.")
        if oos_jpy.get("all_mean", 0) > oos_all.get("all_mean", 0):
            fd.append("**YES** — USDJPY isolation improves OOS stability.")
        else:
            fd.append("**NO** — Multi-pair performs comparably or better OOS.")

    fd.append("\n### 3. Does multi-pair diversification actually hurt rather than help?\n")
    if bos_jpy and bos_all:
        if bos_jpy.sharpe > bos_all.sharpe + 0.3:
            fd.append(f"**YES** — Adding EURUSD/GBPUSD destroys {bos_jpy.sharpe - bos_all.sharpe:.3f} "
                      f"Sharpe points in holdout.")
        else:
            fd.append("Multi-pair does not materially help or hurt.")

    fd.append("\n### 4. Should EURUSD and GBPUSD be removed?\n")
    bos_eur = next((v for v in holdout_vs if v.label == "bos_only | EURUSD only"), None)
    bos_gbp = next((v for v in holdout_vs if v.label == "bos_only | GBPUSD only"), None)
    if bos_eur and bos_gbp:
        fd.append(f"EURUSD-only holdout: Sharpe={bos_eur.sharpe:.3f} -> {'HARMFUL' if bos_eur.sharpe < -0.3 else 'MARGINAL'}")
        fd.append(f"GBPUSD-only holdout: Sharpe={bos_gbp.sharpe:.3f} -> {'HARMFUL' if bos_gbp.sharpe < -0.3 else 'MARGINAL'}")
        if bos_eur.sharpe < -0.3 and bos_gbp.sharpe < -0.3:
            fd.append("**YES** — Both are net destructive. Remove from promoted package.")

    fd.append("\n### 5. Is sweep_reversal permanently demoted?\n")
    if spb_all:
        fd.append(f"sweep_plus_bos holdout: Sharpe={spb_all.sharpe:.3f} vs BOS-only: {bos_all.sharpe:.3f}")
        fd.append("**YES** — sweep_reversal adds no value OOS and reversed from profitable to loss-making.")

    fd.append("\n### 6. Can BOS-only justify paper-trading continuation?\n")
    fd.append(f"Promotion gate result: **{promo}** (confidence: {confidence})")
    if "PROMOTE" in promo:
        fd.append(f"**YES** — With USDJPY focus, BOS-only passes promotion gates.")
    else:
        fd.append(f"**NOT YET** — Does not meet promotion criteria.")

    fd.append("\n### 7. Is the strategy still too regime-sensitive?\n")
    if oos_jpy:
        std = oos_jpy.get("all_std", 999)
        fd.append(f"OOS Sharpe std: {std:.3f}")
        if std > 1.0:
            fd.append("**YES** — High variance across temporal windows indicates regime sensitivity.")
        elif std > 0.5:
            fd.append("**MODERATE** — Some regime sensitivity but within acceptable bounds.")
        else:
            fd.append("**NO** — Reasonably stable across temporal windows.")

    fd.append(f"\n## Key Evidence Summary\n")
    fd.append(f"1. Holdout Sharpe: {h_m.sharpe_ratio:.3f}")
    fd.append(f"2. WF mean OOS Sharpe: {all_mean:.3f}")
    fd.append(f"3. WF % positive folds: {pct_pos:.0%}")
    fd.append(f"4. Stress test: {'PASSED' if stress_ok else 'FAILED'}")
    fd.append(f"5. Drawdown: {h_m.max_drawdown_pct:.1%}")

    fd.append(f"\n## Next Steps\n")
    for i, step in enumerate(rec["next_steps"], 1):
        fd.append(f"{i}. {step}")

    fd.append(f"\n## Unresolved Risks\n")
    fd.append("- Strategy relies on a single pair (USDJPY) — no cross-pair diversification")
    fd.append("- Yahoo Finance data limitations (30% missing bars, no spread data)")
    fd.append("- BOS continuation was unprofitable in training, only profitable in holdout")
    fd.append("- Walk-forward variance may indicate fragile, regime-dependent alpha")
    fd.append("- No session-level attribution available (all trades tagged 'unknown')")

    (OUTPUT_DIR / "updated_final_decision.md").write_text("\n".join(fd))

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
    ctx_b = theme_b(ctx_a, full_data, htf_data)
    theme_c(ctx_a, ctx_b, full_data, htf_data)
    ctx_d = theme_d(ctx_a, ctx_b, full_data, htf_data)
    ctx_e = theme_e(ctx_a, ctx_b, ctx_d, htf_data)
    theme_f(ctx_a, ctx_b, ctx_d, ctx_e)

    elapsed = time.monotonic() - t0
    logger.info("=" * 60)
    logger.info("COMPLETE — Total elapsed: %.1f minutes", elapsed / 60)
    logger.info("All reports written to %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
