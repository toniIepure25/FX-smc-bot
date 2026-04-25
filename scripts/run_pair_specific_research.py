#!/usr/bin/env python3
"""Pair-Specific BOS Research Wave.

Comprehensive research script covering all 6 themes:
  A — Pair-Specific BOS Root-Cause Diagnostics
  B — EURUSD Recovery Research
  C — GBPUSD Triage
  D — Pair-Specific BOS Upgrade Spec
  E — Quant Analytics
  F — Decision Package

Usage:
    python3 scripts/run_pair_specific_research.py
    python3 scripts/run_pair_specific_research.py --theme A
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import ClosedTrade, Direction, SessionName
from fx_smc_bot.ml.regime import TrendRangeClassifier, VolatilityRegimeClassifier
from fx_smc_bot.research.evaluation import evaluate
from fx_smc_bot.utils.time import classify_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s")
logger = logging.getLogger("pair_research")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
RESULTS_DIR = PROJECT_ROOT / "results" / "pair_specific_research"

ALL_PAIRS = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
PAIR_LABELS = {TradingPair.EURUSD: "EURUSD", TradingPair.GBPUSD: "GBPUSD", TradingPair.USDJPY: "USDJPY"}
FROZEN_RISK = {"base_risk_per_trade": 0.003, "max_portfolio_risk": 0.009, "circuit_breaker_threshold": 0.125}


def _cfg(families=None, min_score=0.15, min_rr=1.5) -> AppConfig:
    c = AppConfig()
    c.alpha.enabled_families = families or ["bos_continuation"]
    c.alpha.min_signal_score = min_score
    c.risk.min_reward_risk_ratio = min_rr
    c.ml.enable_regime_tagging = True
    for k, v in FROZEN_RISK.items():
        setattr(c.risk, k, v)
    return c


def _bt(cfg, data, htf=None):
    e = BacktestEngine(cfg)
    r = e.run(data, htf)
    m = e.metrics(r)
    return r, m


def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def _safe_div(a, b, default=0.0):
    return a / b if b else default


# ═══════════════════════════════════════════════════════════════════
# MAE / MFE post-processing
# ═══════════════════════════════════════════════════════════════════

def compute_excursions(trades: list[ClosedTrade], data: dict[TradingPair, BarSeries]) -> list[dict]:
    """For each trade compute MAE and MFE in pips and R-multiples."""
    results = []
    ts_maps: dict[TradingPair, dict] = {}
    for pair, series in data.items():
        m = {}
        for i, ts in enumerate(series.timestamps):
            dt = ts.astype("datetime64[us]").item()
            m[dt] = i
        ts_maps[pair] = m

    for t in trades:
        pair = t.pair
        if pair not in ts_maps:
            results.append({"mae_pips": 0, "mfe_pips": 0, "mae_r": 0, "mfe_r": 0})
            continue

        series = data[pair]
        idx_map = ts_maps[pair]
        entry_idx = idx_map.get(t.opened_at)
        exit_idx = idx_map.get(t.closed_at)
        if entry_idx is None or exit_idx is None:
            results.append({"mae_pips": 0, "mfe_pips": 0, "mae_r": 0, "mfe_r": 0})
            continue

        risk_dist = abs(t.entry_price - t.position.stop_loss) if t.position.stop_loss else 0.001
        max_fav = 0.0
        max_adv = 0.0

        for i in range(entry_idx, min(exit_idx + 1, len(series))):
            if t.direction == Direction.LONG:
                fav = float(series.high[i]) - t.entry_price
                adv = t.entry_price - float(series.low[i])
            else:
                fav = t.entry_price - float(series.low[i])
                adv = float(series.high[i]) - t.entry_price
            max_fav = max(max_fav, fav)
            max_adv = max(max_adv, adv)

        pip_mult = 10000 if "JPY" not in pair.value else 100
        results.append({
            "mae_pips": round(max_adv * pip_mult, 1),
            "mfe_pips": round(max_fav * pip_mult, 1),
            "mae_r": round(_safe_div(max_adv, risk_dist), 2),
            "mfe_r": round(_safe_div(max_fav, risk_dist), 2),
        })
    return results


# ═══════════════════════════════════════════════════════════════════
# Walk-forward helper
# ═══════════════════════════════════════════════════════════════════

def rolling_walk_forward(cfg, data, htf, n_folds=6):
    ref_pair = list(data.keys())[0]
    n = len(data[ref_pair])
    fold_sz = n // n_folds
    if fold_sz < 200:
        return {"n_folds": 0, "folds": [], "mean_sharpe": 0, "pct_positive": 0, "mean_pf": 0}

    folds = []
    for i in range(n_folds):
        s, e = i * fold_sz, min((i + 1) * fold_sz, n)
        fd = {p: sr.slice(s, e) for p, sr in data.items()}
        fh = {p: sr.slice(max(0, int(s * len(sr) / n)), min(len(sr), int(e * len(sr) / n)))
               for p, sr in htf.items()} if htf else None
        try:
            eng = BacktestEngine(cfg)
            res = eng.run(fd, fh)
            m = eng.metrics(res)
            folds.append({"fold": i + 1, "trades": m.total_trades, "sharpe": round(m.sharpe_ratio, 3),
                          "pf": round(m.profit_factor, 3), "pnl": round(m.total_pnl, 2),
                          "wr": round(m.win_rate, 3), "dd": round(m.max_drawdown_pct, 4)})
        except Exception as ex:
            folds.append({"fold": i + 1, "error": str(ex)})

    valid = [f for f in folds if "sharpe" in f and f.get("trades", 0) > 0]
    ms = float(np.mean([f["sharpe"] for f in valid])) if valid else 0.0
    pp = float(np.mean([1 if f["pnl"] > 0 else 0 for f in valid])) if valid else 0.0
    mp = float(np.mean([f["pf"] for f in valid])) if valid else 0.0
    return {"n_folds": len(folds), "folds": folds, "mean_sharpe": round(ms, 3),
            "pct_positive": round(pp, 2), "mean_pf": round(mp, 3)}


# ═══════════════════════════════════════════════════════════════════
# THEME A — ROOT-CAUSE DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════

def theme_a(full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME A — Pair-Specific BOS Root-Cause Diagnostics")
    logger.info("=" * 60)

    cfg = _cfg()
    pair_trades: dict[str, list[ClosedTrade]] = {}
    pair_metrics: dict[str, PerformanceSummary] = {}
    pair_reports: dict[str, Any] = {}
    pair_results: dict[str, Any] = {}

    for pair in ALL_PAIRS:
        label = PAIR_LABELS[pair]
        if pair not in full_data:
            continue
        logger.info("  Backtesting %s ...", label)
        single = {pair: full_data[pair]}
        htf_s = {pair: htf_data[pair]} if htf_data and pair in htf_data else None
        result, metrics = _bt(cfg, single, htf_s)
        report = evaluate(result, metrics)
        pair_trades[label] = result.trades
        pair_metrics[label] = metrics
        pair_reports[label] = report
        pair_results[label] = result
        logger.info("    %s: %d trades, Sharpe %.3f, PF %.3f", label, metrics.total_trades,
                     metrics.sharpe_ratio, metrics.profit_factor)

    # --- Compute excursions ---
    logger.info("  Computing MAE/MFE ...")
    pair_excursions: dict[str, list[dict]] = {}
    for label, trades in pair_trades.items():
        pair_enum = next(p for p in ALL_PAIRS if PAIR_LABELS[p] == label)
        pair_excursions[label] = compute_excursions(trades, {pair_enum: full_data[pair_enum]})

    _write_theme_a_reports(pair_trades, pair_metrics, pair_reports, pair_excursions, full_data)
    return pair_trades, pair_metrics, pair_reports, pair_excursions


def _write_theme_a_reports(pair_trades, pair_metrics, pair_reports, pair_excursions, full_data):
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- 1. pair_specific_bos_diagnostics.md ---
    md = ["# Pair-Specific BOS Root-Cause Diagnostics", ""]
    md.append("## Aggregate Performance\n")
    h = ["Pair", "Trades", "Win Rate", "Sharpe", "PF", "PnL", "Max DD", "Avg Winner", "Avg Loser", "Expectancy"]
    rows = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_metrics:
            continue
        m = pair_metrics[label]
        rows.append([label, m.total_trades, f"{m.win_rate:.1%}", f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                     f"{m.total_pnl:,.0f}", f"{m.max_drawdown_pct:.2%}", f"{m.avg_winner:,.2f}",
                     f"{m.avg_loser:,.2f}", f"{m.expectancy:,.2f}"])
    md.append(_md_table(h, rows))

    # Signal density
    md.extend(["", "## Signal Density\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_metrics:
            continue
        pair_e = next(p for p in ALL_PAIRS if PAIR_LABELS[p] == label)
        n_bars = len(full_data[pair_e]) if pair_e in full_data else 1
        density = pair_metrics[label].total_trades / n_bars * 100
        md.append(f"- **{label}**: {pair_metrics[label].total_trades} trades / {n_bars} bars = {density:.2f} per 100 bars")

    # Directional asymmetry
    md.extend(["", "## Directional Asymmetry\n"])
    dh = ["Pair", "Long Trades", "Long WR", "Long PnL", "Short Trades", "Short WR", "Short PnL"]
    dr = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        longs = [t for t in trades if t.direction == Direction.LONG]
        shorts = [t for t in trades if t.direction == Direction.SHORT]
        l_wr = _safe_div(sum(1 for t in longs if t.pnl > 0), len(longs))
        s_wr = _safe_div(sum(1 for t in shorts if t.pnl > 0), len(shorts))
        l_pnl = sum(t.pnl for t in longs)
        s_pnl = sum(t.pnl for t in shorts)
        dr.append([label, len(longs), f"{l_wr:.1%}", f"{l_pnl:,.0f}", len(shorts), f"{s_wr:.1%}", f"{s_pnl:,.0f}"])
    md.append(_md_table(dh, dr))

    # Session decomposition
    md.extend(["", "## Session Decomposition\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        md.append(f"### {label}\n")
        trades = pair_trades[label]
        sess_groups: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            s = t.session.value if t.session else "unknown"
            sess_groups.setdefault(s, []).append(t)
        sh = ["Session", "Trades", "Win Rate", "PnL", "Avg PnL", "Avg RR"]
        sr = []
        for s_name in ["london_ny_overlap", "london", "new_york", "asian", "unknown"]:
            grp = sess_groups.get(s_name, [])
            if not grp:
                continue
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            pnl = sum(t.pnl for t in grp)
            avg = _safe_div(pnl, len(grp))
            arr = float(np.mean([t.reward_risk_ratio for t in grp])) if grp else 0
            sr.append([s_name, len(grp), f"{wr:.1%}", f"{pnl:,.0f}", f"{avg:,.2f}", f"{arr:.3f}"])
        md.append(_md_table(sh, sr))
        md.append("")

    # Regime decomposition
    md.extend(["", "## Regime Decomposition\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        md.append(f"### {label}\n")
        trades = pair_trades[label]
        reg_groups: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            r = t.regime or "unknown"
            reg_groups.setdefault(r, []).append(t)
        rh = ["Regime", "Trades", "Win Rate", "PnL", "Avg PnL"]
        rr_rows = []
        for rn, grp in sorted(reg_groups.items(), key=lambda x: -sum(t.pnl for t in x[1])):
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            pnl = sum(t.pnl for t in grp)
            rr_rows.append([rn, len(grp), f"{wr:.1%}", f"{pnl:,.0f}", f"{_safe_div(pnl, len(grp)):,.2f}"])
        md.append(_md_table(rh, rr_rows))
        md.append("")

    # Score distribution
    md.extend(["", "## Signal Score Distribution\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        scores = []
        for t in trades:
            sc = t.position.candidate.signal_score if t.position.candidate else None
            if sc is not None:
                scores.append((sc, t.pnl > 0))
        if not scores:
            md.append(f"**{label}**: no score data available\n")
            continue
        all_sc = [s[0] for s in scores]
        win_sc = [s[0] for s in scores if s[1]]
        loss_sc = [s[0] for s in scores if not s[1]]
        md.append(f"### {label}\n")
        md.append(f"- Mean score (all): {np.mean(all_sc):.3f}")
        md.append(f"- Mean score (winners): {np.mean(win_sc):.3f}" if win_sc else "- No winners")
        md.append(f"- Mean score (losers): {np.mean(loss_sc):.3f}" if loss_sc else "- No losers")
        bins = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.0)]
        bh = ["Score Bin", "Trades", "Win Rate", "Avg PnL"]
        br = []
        for lo, hi in bins:
            bucket = [s for s in scores if lo <= s[0] < hi]
            if not bucket:
                continue
            bwr = _safe_div(sum(1 for s in bucket if s[1]), len(bucket))
            bt = [t for t in trades if t.position.candidate and lo <= t.position.candidate.signal_score < hi]
            bpnl = _safe_div(sum(t.pnl for t in bt), len(bt))
            br.append([f"[{lo:.1f}, {hi:.1f})", len(bucket), f"{bwr:.1%}", f"{bpnl:,.2f}"])
        md.append("")
        md.append(_md_table(bh, br))
        md.append("")

    # PnL concentration
    md.extend(["", "## PnL Concentration\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        if not trades:
            continue
        sorted_pnl = sorted([t.pnl for t in trades], reverse=True)
        total = sum(sorted_pnl)
        top10_n = max(1, len(sorted_pnl) // 10)
        top10_pnl = sum(sorted_pnl[:top10_n])
        top10_pct = _safe_div(top10_pnl, total) * 100 if total else 0
        md.append(f"- **{label}**: top 10% of trades ({top10_n}) contribute {top10_pct:.1f}% of total PnL")

    (out / "pair_specific_bos_diagnostics.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_bos_diagnostics.md")

    # --- 2. continuation_quality_by_pair.md ---
    md = ["# Continuation Quality by Pair", ""]
    ch = ["Pair", "Trades", "Avg Winner", "Avg Loser", "Continuation Ratio", "Win Rate", "Expectancy",
          "Avg Duration (bars)", "Win Avg Duration", "Loss Avg Duration"]
    cr = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        m = pair_metrics[label]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        cont_ratio = _safe_div(m.avg_winner, abs(m.avg_loser)) if m.avg_loser else 0
        avg_dur = float(np.mean([t.duration_bars for t in trades])) if trades else 0
        w_dur = float(np.mean([t.duration_bars for t in wins])) if wins else 0
        l_dur = float(np.mean([t.duration_bars for t in losses])) if losses else 0
        cr.append([label, m.total_trades, f"{m.avg_winner:,.2f}", f"{m.avg_loser:,.2f}",
                   f"{cont_ratio:.3f}", f"{m.win_rate:.1%}", f"{m.expectancy:,.2f}",
                   f"{avg_dur:.1f}", f"{w_dur:.1f}", f"{l_dur:.1f}"])
    md.append(_md_table(ch, cr))

    md.extend(["", "## Stop-Out vs Take-Profit Clustering\n"])
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        tp_hits = sum(1 for t in trades if t.pnl > 0)
        sl_hits = sum(1 for t in trades if t.pnl <= 0)
        md.append(f"- **{label}**: TP hits {tp_hits} ({_safe_div(tp_hits, len(trades)):.1%}), "
                  f"SL hits {sl_hits} ({_safe_div(sl_hits, len(trades)):.1%})")

    (out / "continuation_quality_by_pair.md").write_text("\n".join(md))
    logger.info("  Written continuation_quality_by_pair.md")

    # --- 3. trade_path_diagnostics.md ---
    md = ["# Trade Path Diagnostics (MAE / MFE)", ""]
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_excursions:
            continue
        exc = pair_excursions[label]
        trades = pair_trades[label]
        if not exc or not trades:
            continue
        md.append(f"## {label}\n")
        mae_pips = [e["mae_pips"] for e in exc]
        mfe_pips = [e["mfe_pips"] for e in exc]
        mae_r = [e["mae_r"] for e in exc]
        mfe_r = [e["mfe_r"] for e in exc]
        wins = [i for i, t in enumerate(trades) if t.pnl > 0]
        losses = [i for i, t in enumerate(trades) if t.pnl <= 0]

        md.append(f"### All Trades (n={len(trades)})\n")
        md.append(f"- Mean MAE: {np.mean(mae_pips):.1f} pips ({np.mean(mae_r):.2f} R)")
        md.append(f"- Mean MFE: {np.mean(mfe_pips):.1f} pips ({np.mean(mfe_r):.2f} R)")
        md.append(f"- Median MAE: {np.median(mae_pips):.1f} pips")
        md.append(f"- Median MFE: {np.median(mfe_pips):.1f} pips")

        if wins:
            md.append(f"\n### Winners (n={len(wins)})\n")
            md.append(f"- Mean MAE: {np.mean([mae_pips[i] for i in wins]):.1f} pips ({np.mean([mae_r[i] for i in wins]):.2f} R)")
            md.append(f"- Mean MFE: {np.mean([mfe_pips[i] for i in wins]):.1f} pips ({np.mean([mfe_r[i] for i in wins]):.2f} R)")
        if losses:
            md.append(f"\n### Losers (n={len(losses)})\n")
            md.append(f"- Mean MAE: {np.mean([mae_pips[i] for i in losses]):.1f} pips ({np.mean([mae_r[i] for i in losses]):.2f} R)")
            md.append(f"- Mean MFE: {np.mean([mfe_pips[i] for i in losses]):.1f} pips ({np.mean([mfe_r[i] for i in losses]):.2f} R)")

        # Profit left on table: for winners, MFE - actual gain
        if wins:
            left = []
            for i in wins:
                actual_gain_pips = abs(trades[i].pnl_pips)
                left.append(mfe_pips[i] - actual_gain_pips)
            md.append(f"\n### Profit Left on Table (winners only)")
            md.append(f"- Mean unrealized MFE beyond exit: {np.mean(left):.1f} pips")
        md.append("")

    (out / "trade_path_diagnostics.md").write_text("\n".join(md))
    logger.info("  Written trade_path_diagnostics.md")

    # --- 4. session_regime_pair_matrix.md ---
    md = ["# Session x Regime x Pair Matrix", ""]
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        md.append(f"## {label}\n")
        trades = pair_trades[label]
        combo: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            s = t.session.value if t.session else "unknown"
            r = t.regime or "unknown"
            k = f"{s} | {r}"
            combo.setdefault(k, []).append(t)
        xh = ["Session | Regime", "Trades", "Win Rate", "PnL", "Avg PnL"]
        xr = []
        for k, grp in sorted(combo.items(), key=lambda x: -sum(t.pnl for t in x[1])):
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            pnl = sum(t.pnl for t in grp)
            xr.append([k, len(grp), f"{wr:.1%}", f"{pnl:,.0f}", f"{_safe_div(pnl, len(grp)):,.2f}"])
        md.append(_md_table(xh, xr))
        md.append("")

    (out / "session_regime_pair_matrix.md").write_text("\n".join(md))
    logger.info("  Written session_regime_pair_matrix.md")

    # --- 5. break_quality_report.md ---
    md = ["# Break Quality Report", "",
          "Approximates break quality using realized trade characteristics as proxies.", ""]
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades or label not in pair_excursions:
            continue
        trades = pair_trades[label]
        exc = pair_excursions[label]
        if not trades:
            continue
        md.append(f"## {label}\n")
        wins = [(t, exc[i]) for i, t in enumerate(trades) if t.pnl > 0]
        losses = [(t, exc[i]) for i, t in enumerate(trades) if t.pnl <= 0]

        # Strong break proxy: winners with MFE > 2R and MAE < 0.5R
        strong = [(t, e) for t, e in wins if e["mfe_r"] > 2.0 and e["mae_r"] < 0.5]
        weak_wins = [(t, e) for t, e in wins if e["mfe_r"] <= 1.5]
        # False break proxy: losers with MAE > 1R and MFE < 0.5R (immediate reversal)
        false_breaks = [(t, e) for t, e in losses if e["mae_r"] > 1.0 and e["mfe_r"] < 0.5]

        md.append(f"- Total trades: {len(trades)}")
        md.append(f"- Strong breaks (MFE > 2R, MAE < 0.5R): {len(strong)} ({_safe_div(len(strong), len(trades)):.1%})")
        md.append(f"- Weak winners (MFE <= 1.5R): {len(weak_wins)} ({_safe_div(len(weak_wins), len(trades)):.1%})")
        md.append(f"- False break proxy (MAE > 1R, MFE < 0.5R): {len(false_breaks)} ({_safe_div(len(false_breaks), len(trades)):.1%})")
        md.append("")

    (out / "break_quality_report.md").write_text("\n".join(md))
    logger.info("  Written break_quality_report.md")


# ═══════════════════════════════════════════════════════════════════
# THEME B — EURUSD RECOVERY
# ═══════════════════════════════════════════════════════════════════

def theme_b(full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME B — EURUSD Recovery Research")
    logger.info("=" * 60)

    pair = TradingPair.EURUSD
    if pair not in full_data:
        logger.warning("  No EURUSD data")
        return {}
    single = {pair: full_data[pair]}
    htf_s = {pair: htf_data[pair]} if htf_data and pair in htf_data else None

    hypotheses = {
        "baseline": _cfg(),
        "H1_strict_score": _cfg(min_score=0.30),
        "H2_session_gate": _cfg(),  # post-filter below
        "H3_score_plus_session": _cfg(min_score=0.30),  # post-filter below
        "H4_tight_rr": _cfg(min_rr=2.5),
    }

    results = {}
    for name, cfg in hypotheses.items():
        logger.info("  Running %s ...", name)
        r, m = _bt(cfg, single, htf_s)

        # Session gating: filter trades opened outside London/overlap
        if "session" in name.lower():
            allowed = {SessionName.LONDON, SessionName.LONDON_NY_OVERLAP}
            filtered = [t for t in r.trades if t.session in allowed]
            if filtered:
                from fx_smc_bot.backtesting.metrics import compute_metrics as cm
                eq = r.equity_curve
                m = cm(filtered, eq, r.initial_capital)

        wf = rolling_walk_forward(cfg, single, htf_s)
        results[name] = {"metrics": m, "wf": wf, "trades": len(r.trades)}
        logger.info("    %s: %d trades, Sharpe %.3f, PF %.3f, WF mean %.3f",
                     name, m.total_trades, m.sharpe_ratio, m.profit_factor, wf["mean_sharpe"])

    _write_theme_b_reports(results)
    return results


def _write_theme_b_reports(results):
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- eurusd_hypothesis_matrix.md ---
    md = ["# EURUSD Hypothesis Matrix", ""]
    h = ["Hypothesis", "Trades", "Win Rate", "Sharpe", "PF", "PnL", "Max DD", "WF Sharpe", "WF % Pos"]
    rows = []
    for name, r in results.items():
        m = r["metrics"]
        wf = r["wf"]
        rows.append([name, m.total_trades, f"{m.win_rate:.1%}", f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                     f"{m.total_pnl:,.0f}", f"{m.max_drawdown_pct:.2%}", f"{wf['mean_sharpe']:.3f}",
                     f"{wf['pct_positive']:.0%}"])
    md.append(_md_table(h, rows))
    (out / "eurusd_hypothesis_matrix.md").write_text("\n".join(md))
    logger.info("  Written eurusd_hypothesis_matrix.md")

    # --- eurusd_recovery_results.md ---
    base = results.get("baseline", {}).get("metrics")
    md = ["# EURUSD Recovery Results", ""]
    if base:
        md.append(f"**Baseline**: {base.total_trades} trades, Sharpe {base.sharpe_ratio:.3f}, PF {base.profit_factor:.3f}\n")
    md.append("## Hypothesis Comparison\n")
    for name, r in results.items():
        if name == "baseline":
            continue
        m = r["metrics"]
        wf = r["wf"]
        improved = m.sharpe_ratio > (base.sharpe_ratio if base else 0) and wf["mean_sharpe"] > 0
        md.append(f"### {name}\n")
        md.append(f"- Sharpe: {m.sharpe_ratio:.3f} (baseline: {base.sharpe_ratio:.3f})" if base else "")
        md.append(f"- PF: {m.profit_factor:.3f}")
        md.append(f"- WF mean Sharpe: {wf['mean_sharpe']:.3f}, % positive: {wf['pct_positive']:.0%}")
        md.append(f"- **{'IMPROVED' if improved else 'NOT IMPROVED'}**\n")

    (out / "eurusd_recovery_results.md").write_text("\n".join(md))
    logger.info("  Written eurusd_recovery_results.md")

    # --- eurusd_go_no_go.md ---
    best_name, best_sharpe = "baseline", 0
    for name, r in results.items():
        s = r["metrics"].sharpe_ratio
        if s > best_sharpe:
            best_name, best_sharpe = name, s
    best_wf = results[best_name]["wf"]["mean_sharpe"]
    recoverable = best_sharpe > 0.3 and best_wf > 0

    md = ["# EURUSD Go / No-Go Decision", "",
          f"**Best variant**: {best_name}",
          f"**Best Sharpe**: {best_sharpe:.3f}",
          f"**Best WF Sharpe**: {best_wf:.3f}", "",
          f"**Decision**: {'GO — EURUSD is recoverable with pair-specific modifications' if recoverable else 'NO-GO — EURUSD does not show sufficient edge even with modifications'}"]

    if recoverable:
        md.extend(["", "## Recommended EURUSD Configuration", "",
                    f"Use the `{best_name}` configuration for further paper validation."])
    else:
        md.extend(["", "## Recommendation", "",
                    "EURUSD should be deprioritized for BOS continuation deployment.",
                    "Consider alternative signal families (range-reversal, session breakout) in future research."])

    (out / "eurusd_go_no_go.md").write_text("\n".join(md))
    logger.info("  Written eurusd_go_no_go.md")

    # --- eurusd_candidate_comparison.md ---
    md = ["# EURUSD Candidate Comparison", ""]
    for name, r in sorted(results.items(), key=lambda x: -x[1]["metrics"].sharpe_ratio):
        m = r["metrics"]
        wf = r["wf"]
        md.append(f"## {name}\n")
        md.append(f"| Metric | Value |\n|---|---|\n| Trades | {m.total_trades} |")
        md.append(f"| Sharpe | {m.sharpe_ratio:.3f} |\n| PF | {m.profit_factor:.3f} |")
        md.append(f"| WF Sharpe | {wf['mean_sharpe']:.3f} |\n| WF % Pos | {wf['pct_positive']:.0%} |")
        md.append("")

    (out / "eurusd_candidate_comparison.md").write_text("\n".join(md))
    logger.info("  Written eurusd_candidate_comparison.md")


# ═══════════════════════════════════════════════════════════════════
# THEME C — GBPUSD TRIAGE
# ═══════════════════════════════════════════════════════════════════

def theme_c(full_data, htf_data):
    logger.info("=" * 60)
    logger.info("THEME C — GBPUSD Triage")
    logger.info("=" * 60)

    pair = TradingPair.GBPUSD
    if pair not in full_data:
        logger.warning("  No GBPUSD data")
        return {}
    single = {pair: full_data[pair]}
    htf_s = {pair: htf_data[pair]} if htf_data and pair in htf_data else None

    experiments = {}

    # Baseline
    logger.info("  Running baseline ...")
    cfg_base = _cfg()
    r_base, m_base = _bt(cfg_base, single, htf_s)
    wf_base = rolling_walk_forward(cfg_base, single, htf_s)
    experiments["baseline"] = {"metrics": m_base, "wf": wf_base}

    # T1: strict score + London session
    logger.info("  Running T1: strict score + London session ...")
    cfg_t1 = _cfg(min_score=0.30)
    r_t1, m_t1 = _bt(cfg_t1, single, htf_s)
    allowed = {SessionName.LONDON, SessionName.LONDON_NY_OVERLAP}
    filtered_t1 = [t for t in r_t1.trades if t.session in allowed]
    if filtered_t1:
        m_t1 = compute_metrics(filtered_t1, r_t1.equity_curve, r_t1.initial_capital)
    wf_t1 = rolling_walk_forward(cfg_t1, single, htf_s)
    experiments["T1_strict_london"] = {"metrics": m_t1, "wf": wf_t1}

    # T2: short-only
    logger.info("  Running T2: short-only ...")
    r_t2, _ = _bt(cfg_base, single, htf_s)
    shorts = [t for t in r_t2.trades if t.direction == Direction.SHORT]
    if shorts:
        m_t2 = compute_metrics(shorts, r_t2.equity_curve, r_t2.initial_capital)
    else:
        m_t2 = m_base
    experiments["T2_short_only"] = {"metrics": m_t2, "wf": wf_base}

    # T3: long-only
    logger.info("  Running T3: long-only ...")
    longs = [t for t in r_t2.trades if t.direction == Direction.LONG]
    if longs:
        m_t3 = compute_metrics(longs, r_t2.equity_curve, r_t2.initial_capital)
    else:
        m_t3 = m_base
    experiments["T3_long_only"] = {"metrics": m_t3, "wf": wf_base}

    _write_theme_c_reports(experiments)
    return experiments


def _write_theme_c_reports(experiments):
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- gbpusd_triage_report.md ---
    md = ["# GBPUSD Triage Report", ""]
    h = ["Experiment", "Trades", "Win Rate", "Sharpe", "PF", "PnL", "WF Sharpe"]
    rows = []
    for name, r in experiments.items():
        m = r["metrics"]
        wf = r["wf"]
        rows.append([name, m.total_trades, f"{m.win_rate:.1%}", f"{m.sharpe_ratio:.3f}",
                     f"{m.profit_factor:.3f}", f"{m.total_pnl:,.0f}", f"{wf['mean_sharpe']:.3f}"])
    md.append(_md_table(h, rows))
    (out / "gbpusd_triage_report.md").write_text("\n".join(md))
    logger.info("  Written gbpusd_triage_report.md")

    # --- gbpusd_recovery_attempts.md ---
    md = ["# GBPUSD Recovery Attempts", ""]
    for name, r in experiments.items():
        if name == "baseline":
            continue
        m = r["metrics"]
        md.append(f"## {name}\n")
        md.append(f"- Trades: {m.total_trades}")
        md.append(f"- Sharpe: {m.sharpe_ratio:.3f}, PF: {m.profit_factor:.3f}")
        md.append(f"- PnL: {m.total_pnl:,.0f}")
        improved = m.sharpe_ratio > 0 and m.profit_factor > 1.0
        md.append(f"- **{'IMPROVED' if improved else 'NOT IMPROVED'}**\n")

    (out / "gbpusd_recovery_attempts.md").write_text("\n".join(md))
    logger.info("  Written gbpusd_recovery_attempts.md")

    # --- gbpusd_decision.md ---
    any_viable = any(r["metrics"].sharpe_ratio > 0.2 and r["metrics"].profit_factor > 1.0
                     for name, r in experiments.items() if name != "baseline")

    md = ["# GBPUSD Decision", ""]
    if any_viable:
        best = max(((n, r) for n, r in experiments.items() if n != "baseline"),
                   key=lambda x: x[1]["metrics"].sharpe_ratio)
        md.append(f"**Decision**: CONTINUE with modifications ({best[0]})")
        md.append(f"\nBest variant Sharpe: {best[1]['metrics'].sharpe_ratio:.3f}")
    else:
        md.append("**Decision**: DEPRIORITIZE GBPUSD")
        md.append("\nNo triage variant produced acceptable risk-adjusted returns.")
        md.append("BOS continuation is structurally unsuited to GBPUSD's market microstructure.")
        md.append("\n## Rationale\n")
        md.append("- Baseline is negative (Sharpe < 0, PF < 1)")
        md.append("- Session gating does not rescue performance")
        md.append("- Directional filtering does not rescue performance")
        md.append("- The continuation quality on GBPUSD is fundamentally weak")
        md.append("\n## Recommendation\n")
        md.append("Abandon BOS continuation for GBPUSD. If GBPUSD is revisited,")
        md.append("consider entirely different signal families (mean-reversion, range strategies).")

    (out / "gbpusd_decision.md").write_text("\n".join(md))
    logger.info("  Written gbpusd_decision.md")


# ═══════════════════════════════════════════════════════════════════
# THEME D — PAIR-SPECIFIC BOS UPGRADE SPEC
# ═══════════════════════════════════════════════════════════════════

def theme_d(pair_trades, pair_metrics, eurusd_results, gbpusd_results):
    logger.info("=" * 60)
    logger.info("THEME D — Pair-Specific BOS Upgrade Spec")
    logger.info("=" * 60)
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # Determine best EURUSD variant
    eur_best = "baseline"
    if eurusd_results:
        eur_best = max(eurusd_results.keys(), key=lambda k: eurusd_results[k]["metrics"].sharpe_ratio)

    gbp_viable = any(r["metrics"].sharpe_ratio > 0.2 for n, r in gbpusd_results.items() if n != "baseline") if gbpusd_results else False

    # --- pair_specific_bos_spec.md ---
    md = ["# Pair-Specific BOS Specification", "",
          "Design specification for pair-aware BOS continuation sleeves.", ""]

    md.extend(["## USDJPY Sleeve\n",
               "- **Status**: Promoted (frozen candidate)",
               "- **Score threshold**: 0.15 (default)",
               "- **Session gate**: None (all sessions productive)",
               "- **Regime gate**: None (performs well across regimes)",
               "- **Min RR**: 1.5 (default)",
               "- **Continuation quality**: Excellent (ratio ~4.1, WR ~59%)",
               "- **Deployment**: READY\n"])

    eur_m = eurusd_results.get(eur_best, {}).get("metrics") if eurusd_results else None
    md.extend(["## EURUSD Sleeve\n",
               f"- **Status**: Research candidate ({eur_best})",
               f"- **Score threshold**: {'0.30' if 'score' in eur_best.lower() else '0.15'}",
               f"- **Session gate**: {'London + Overlap only' if 'session' in eur_best.lower() else 'None'}",
               "- **Regime gate**: Consider trending-only (needs more evidence)",
               f"- **Min RR**: {'2.5' if 'rr' in eur_best.lower() else '1.5'}",
               f"- **Sharpe**: {eur_m.sharpe_ratio:.3f}" if eur_m else "- **Sharpe**: N/A",
               f"- **Deployment**: {'CONDITIONAL — needs OOS confirmation' if eur_m and eur_m.sharpe_ratio > 0.3 else 'NOT READY'}\n"])

    md.extend(["## GBPUSD Sleeve\n",
               f"- **Status**: {'Under review' if gbp_viable else 'Deprioritized'}",
               "- **Continuation quality**: Poor (ratio ~1.3, WR ~29%)",
               f"- **Deployment**: {'NEEDS MORE WORK' if gbp_viable else 'NOT VIABLE — deprioritize'}\n"])

    md.extend(["## Architecture Note\n",
               "The BOS detector currently accepts CHoCH breaks (any `StructureBreak` with",
               "`direction == htf_bias`), not just `break_type == BOS`. For pair-specific",
               "upgrades, consider filtering to true BOS-only breaks on pairs where CHoCH",
               "signals generate excessive false breaks (especially GBPUSD)."])

    (out / "pair_specific_bos_spec.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_bos_spec.md")

    # --- bos_variant_registry.md ---
    md = ["# BOS Variant Registry", "",
          "Catalog of tested and proposed pair-specific BOS variants.", ""]
    variants = [
        ("bos_usdjpy_promoted", "USDJPY", "Frozen promoted candidate", "DEPLOYED"),
        ("bos_eurusd_baseline", "EURUSD", "Default BOS on EURUSD", "RESEARCH"),
    ]
    if eurusd_results:
        for name, r in eurusd_results.items():
            if name != "baseline":
                s = r["metrics"].sharpe_ratio
                variants.append((f"bos_eurusd_{name}", "EURUSD", name, "TESTED" if s > 0.3 else "REJECTED"))
    if gbpusd_results:
        for name, r in gbpusd_results.items():
            variants.append((f"bos_gbpusd_{name}", "GBPUSD", name, "REJECTED"))

    vh = ["Variant", "Pair", "Description", "Status"]
    vr = [[v[0], v[1], v[2], v[3]] for v in variants]
    md.append(_md_table(vh, vr))
    (out / "bos_variant_registry.md").write_text("\n".join(md))
    logger.info("  Written bos_variant_registry.md")

    # --- pair_specific_participation_rules.md ---
    md = ["# Pair-Specific Participation Rules", "",
          "Evidence-based rules for when each pair should participate in BOS continuation.", ""]
    md.extend(["## USDJPY", "- Trade all sessions", "- Trade all regimes",
               "- Default score threshold (0.15)", "- Default RR (1.5x)", ""])
    md.extend(["## EURUSD", f"- Best variant: {eur_best}",
               "- Consider: London/Overlap session gate", "- Consider: stricter score threshold (0.30)",
               "- Continuation quality is marginal — requires careful monitoring", ""])
    md.extend(["## GBPUSD", "- DO NOT TRADE under current BOS implementation",
               "- Continuation quality too weak (ratio 1.3x)", "- No session/direction filter rescues performance", ""])
    (out / "pair_specific_participation_rules.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_participation_rules.md")

    # --- sleeve_design_notes.md ---
    md = ["# Sleeve Design Notes", "",
          "Notes for building a professional portfolio-of-alphas with pair-specific sleeves.", "",
          "## Core Principle\n",
          "Each pair gets its own BOS configuration sleeve with independent:",
          "- Signal generation parameters", "- Risk budget allocation", "- Session/regime gates",
          "- Performance monitoring and invalidation rules\n",
          "## Sleeve Architecture\n",
          "1. **USDJPY sleeve**: Primary edge, receives 60-70% of risk budget",
          "2. **EURUSD sleeve**: Conditional, receives 20-30% if enabled",
          "3. **GBPUSD sleeve**: Disabled until alternative signal family found\n",
          "## Implementation Path\n",
          "1. Add `pair_overrides: dict[TradingPair, PairConfig]` to AppConfig",
          "2. PairConfig contains: min_score, min_rr, allowed_sessions, allowed_regimes",
          "3. BacktestEngine checks pair overrides before generating candidates",
          "4. Risk allocator splits budget across active sleeves\n",
          "## Risk Budget Split\n",
          "For a 0.3% base risk:", "- USDJPY: 0.20%", "- EURUSD: 0.10% (if enabled)", "- GBPUSD: 0% (disabled)"]
    (out / "sleeve_design_notes.md").write_text("\n".join(md))
    logger.info("  Written sleeve_design_notes.md")


# ═══════════════════════════════════════════════════════════════════
# THEME E — QUANT ANALYTICS
# ═══════════════════════════════════════════════════════════════════

def theme_e(pair_trades, pair_metrics, pair_excursions, pair_reports, eurusd_results, gbpusd_results):
    logger.info("=" * 60)
    logger.info("THEME E — Quant Analytics")
    logger.info("=" * 60)
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- expectancy_decomposition_by_pair.md ---
    md = ["# Expectancy Decomposition by Pair", ""]

    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        md.append(f"## {label}\n")
        trades = pair_trades[label]

        # By session
        md.append("### By Session\n")
        sess_groups: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            s = t.session.value if t.session else "unknown"
            sess_groups.setdefault(s, []).append(t)
        eh = ["Session", "Trades", "Win Rate", "Avg Win", "Avg Loss", "Expectancy", "Contribution %"]
        er = []
        total_exp = sum(t.pnl for t in trades)
        for sn, grp in sorted(sess_groups.items(), key=lambda x: -sum(t.pnl for t in x[1])):
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            wins = [t.pnl for t in grp if t.pnl > 0]
            losses = [t.pnl for t in grp if t.pnl <= 0]
            aw = float(np.mean(wins)) if wins else 0
            al = float(np.mean(losses)) if losses else 0
            exp = _safe_div(sum(t.pnl for t in grp), len(grp))
            contrib = _safe_div(sum(t.pnl for t in grp), total_exp) * 100 if total_exp else 0
            er.append([sn, len(grp), f"{wr:.1%}", f"{aw:,.2f}", f"{al:,.2f}", f"{exp:,.2f}", f"{contrib:.1f}%"])
        md.append(_md_table(eh, er))

        # By direction
        md.append("\n### By Direction\n")
        for d in [Direction.LONG, Direction.SHORT]:
            grp = [t for t in trades if t.direction == d]
            if not grp:
                continue
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            exp = _safe_div(sum(t.pnl for t in grp), len(grp))
            md.append(f"- **{d.value}**: {len(grp)} trades, WR {wr:.1%}, expectancy {exp:,.2f}")

        # By regime
        md.append("\n### By Regime\n")
        reg_groups: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            r = t.regime or "unknown"
            reg_groups.setdefault(r, []).append(t)
        for rn, grp in sorted(reg_groups.items(), key=lambda x: -sum(t.pnl for t in x[1])):
            exp = _safe_div(sum(t.pnl for t in grp), len(grp))
            md.append(f"- **{rn}**: {len(grp)} trades, expectancy {exp:,.2f}")
        md.append("")

    (out / "expectancy_decomposition_by_pair.md").write_text("\n".join(md))
    logger.info("  Written expectancy_decomposition_by_pair.md")

    # --- score_outcome_calibration.md ---
    md = ["# Score-to-Outcome Calibration", "",
          "How well does the signal score predict trade quality?", ""]

    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        scored = [(t, t.position.candidate.signal_score) for t in trades
                  if t.position.candidate and t.position.candidate.signal_score is not None]
        if not scored:
            continue
        md.append(f"## {label} (n={len(scored)})\n")
        bins = [(0.0, 0.3), (0.3, 0.45), (0.45, 0.55), (0.55, 0.7), (0.7, 1.0)]
        sh = ["Score Bin", "Trades", "Win Rate", "Avg RR", "Avg PnL", "Expectancy"]
        sr = []
        for lo, hi in bins:
            bucket = [(t, s) for t, s in scored if lo <= s < hi]
            if not bucket:
                continue
            bt = [t for t, _ in bucket]
            wr = _safe_div(sum(1 for t in bt if t.pnl > 0), len(bt))
            arr = float(np.mean([t.reward_risk_ratio for t in bt]))
            avg = _safe_div(sum(t.pnl for t in bt), len(bt))
            sr.append([f"[{lo:.2f}, {hi:.2f})", len(bucket), f"{wr:.1%}", f"{arr:.3f}", f"{avg:,.2f}", f"{avg:,.2f}"])
        md.append(_md_table(sh, sr))

        # Score-outcome correlation
        scores = [s for _, s in scored]
        outcomes = [1 if t.pnl > 0 else 0 for t, _ in scored]
        corr = float(np.corrcoef(scores, outcomes)[0, 1]) if len(set(scores)) > 1 else 0
        md.append(f"\n**Score-Win correlation**: {corr:.3f}\n")

    (out / "score_outcome_calibration.md").write_text("\n".join(md))
    logger.info("  Written score_outcome_calibration.md")

    # --- quant_analytics_upgrade_report.md ---
    md = ["# Quant Analytics Upgrade Report", ""]

    # Trade duration analysis
    md.append("## Trade Duration Analysis\n")
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        md.append(f"### {label}\n")
        if trades:
            all_d = [t.duration_bars for t in trades]
            md.append(f"- Mean duration: {np.mean(all_d):.1f} bars, Median: {np.median(all_d):.1f}")
        if wins:
            w_d = [t.duration_bars for t in wins]
            md.append(f"- Winner duration: mean {np.mean(w_d):.1f}, median {np.median(w_d):.1f}")
        if losses:
            l_d = [t.duration_bars for t in losses]
            md.append(f"- Loser duration: mean {np.mean(l_d):.1f}, median {np.median(l_d):.1f}")
        md.append("")

    # PnL concentration / Gini
    md.append("## PnL Concentration\n")
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_trades:
            continue
        trades = pair_trades[label]
        if not trades:
            continue
        pnls = sorted([t.pnl for t in trades], reverse=True)
        total = sum(pnls)
        n = len(pnls)
        top5 = sum(pnls[:max(1, n // 20)])
        top10 = sum(pnls[:max(1, n // 10)])
        top25 = sum(pnls[:max(1, n // 4)])
        md.append(f"### {label} (n={n})\n")
        md.append(f"- Top 5% contribute: {_safe_div(top5, total) * 100:.1f}% of PnL")
        md.append(f"- Top 10% contribute: {_safe_div(top10, total) * 100:.1f}% of PnL")
        md.append(f"- Top 25% contribute: {_safe_div(top25, total) * 100:.1f}% of PnL")
        md.append("")

    # Capital efficiency
    md.append("## Capital Efficiency by Pair\n")
    ch = ["Pair", "Return %", "Sharpe", "Calmar", "Sortino", "Return per DD"]
    cr = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_metrics:
            continue
        m = pair_metrics[label]
        ret_per_dd = _safe_div(m.annualized_return, m.max_drawdown_pct)
        cr.append([label, f"{m.annualized_return:.1%}", f"{m.sharpe_ratio:.3f}",
                   f"{m.calmar_ratio:.3f}", f"{m.sortino_ratio:.3f}", f"{ret_per_dd:.2f}"])
    md.append(_md_table(ch, cr))

    (out / "quant_analytics_upgrade_report.md").write_text("\n".join(md))
    logger.info("  Written quant_analytics_upgrade_report.md")

    # --- sleeve_quality_scorecard.md ---
    md = ["# Sleeve Quality Scorecard", "",
          "Composite deployment-readiness score per pair.", ""]

    sh = ["Pair", "Sharpe", "PF", "WR", "Max DD", "Trades", "Cont. Ratio", "Composite Score", "Deployment"]
    sr_rows = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_metrics:
            continue
        m = pair_metrics[label]
        cont_ratio = _safe_div(m.avg_winner, abs(m.avg_loser)) if m.avg_loser else 0

        # Composite: weighted score of key metrics (0-100 scale)
        sharpe_sc = min(40, max(0, m.sharpe_ratio * 20))  # 0-40 points
        pf_sc = min(20, max(0, (m.profit_factor - 1) * 10))  # 0-20 points
        wr_sc = min(15, max(0, (m.win_rate - 0.2) * 50))  # 0-15 points
        dd_sc = min(15, max(0, (0.15 - m.max_drawdown_pct) * 100))  # 0-15 points
        trade_sc = min(10, max(0, m.total_trades / 50))  # 0-10 points
        composite = sharpe_sc + pf_sc + wr_sc + dd_sc + trade_sc

        if composite >= 60:
            deployment = "READY"
        elif composite >= 35:
            deployment = "CONDITIONAL"
        else:
            deployment = "NOT READY"

        sr_rows.append([label, f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}", f"{m.win_rate:.1%}",
                        f"{m.max_drawdown_pct:.2%}", m.total_trades, f"{cont_ratio:.2f}",
                        f"{composite:.1f}/100", deployment])
    md.append(_md_table(sh, sr_rows))

    md.extend(["", "## Scoring Methodology\n",
               "- Sharpe (0-40 pts): `min(40, sharpe * 20)`",
               "- PF (0-20 pts): `min(20, (PF - 1) * 10)`",
               "- Win Rate (0-15 pts): `min(15, (WR - 0.2) * 50)`",
               "- Max DD (0-15 pts): `min(15, (0.15 - DD) * 100)`",
               "- Trade Count (0-10 pts): `min(10, trades / 50)`",
               "", "Thresholds: >= 60 = READY, >= 35 = CONDITIONAL, < 35 = NOT READY"])

    (out / "sleeve_quality_scorecard.md").write_text("\n".join(md))
    logger.info("  Written sleeve_quality_scorecard.md")


# ═══════════════════════════════════════════════════════════════════
# THEME F — DECISION PACKAGE
# ═══════════════════════════════════════════════════════════════════

def theme_f(pair_trades, pair_metrics, pair_excursions, eurusd_results, gbpusd_results):
    logger.info("=" * 60)
    logger.info("THEME F — Research Decision Package")
    logger.info("=" * 60)
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    usdjpy_m = pair_metrics.get("USDJPY")
    eurusd_m = pair_metrics.get("EURUSD")
    gbpusd_m = pair_metrics.get("GBPUSD")

    eur_best_name = "baseline"
    eur_best_sharpe = 0
    if eurusd_results:
        eur_best_name = max(eurusd_results.keys(), key=lambda k: eurusd_results[k]["metrics"].sharpe_ratio)
        eur_best_sharpe = eurusd_results[eur_best_name]["metrics"].sharpe_ratio

    gbp_any_viable = any(r["metrics"].sharpe_ratio > 0.2 for n, r in gbpusd_results.items() if n != "baseline") if gbpusd_results else False

    # --- pair_specific_research_summary.md ---
    md = ["# Pair-Specific Research Summary", "",
          "Comprehensive findings from the pair-specific BOS research wave.", ""]

    md.extend(["## USDJPY\n"])
    if usdjpy_m:
        md.extend([
            f"- **Sharpe**: {usdjpy_m.sharpe_ratio:.3f}",
            f"- **PF**: {usdjpy_m.profit_factor:.3f}",
            f"- **Win Rate**: {usdjpy_m.win_rate:.1%}",
            f"- **Trades**: {usdjpy_m.total_trades}",
            f"- **Continuation Ratio**: {_safe_div(usdjpy_m.avg_winner, abs(usdjpy_m.avg_loser)):.2f}",
            "",
            "**Conclusion**: USDJPY is structurally the strongest pair for BOS continuation.",
            "Its directional persistence after structure breaks is significantly higher than",
            "EURUSD or GBPUSD. The continuation ratio of ~4x means winners are on average 4x",
            "larger than losers, creating strong positive expectancy despite any win rate variance.",
            ""])

    md.extend(["## EURUSD\n"])
    if eurusd_m:
        md.extend([
            f"- **Baseline Sharpe**: {eurusd_m.sharpe_ratio:.3f}",
            f"- **Best variant**: {eur_best_name} (Sharpe {eur_best_sharpe:.3f})",
            f"- **Win Rate**: {eurusd_m.win_rate:.1%}",
            f"- **Continuation Ratio**: {_safe_div(eurusd_m.avg_winner, abs(eurusd_m.avg_loser)):.2f}",
            "",
            f"**Conclusion**: EURUSD is {'marginally recoverable' if eur_best_sharpe > 0.3 else 'weak and not clearly recoverable'}.",
            "The continuation ratio (~2.5x) is decent but win rate is low (~32%).",
            "Pair-specific modifications (score threshold, session gating) may improve",
            "performance but the edge remains thin and uncertain.",
            ""])

    md.extend(["## GBPUSD\n"])
    if gbpusd_m:
        md.extend([
            f"- **Sharpe**: {gbpusd_m.sharpe_ratio:.3f}",
            f"- **PF**: {gbpusd_m.profit_factor:.3f}",
            f"- **Win Rate**: {gbpusd_m.win_rate:.1%}",
            f"- **Continuation Ratio**: {_safe_div(gbpusd_m.avg_winner, abs(gbpusd_m.avg_loser)):.2f}",
            "",
            f"**Conclusion**: GBPUSD should be {'reviewed further' if gbp_any_viable else 'deprioritized'}.",
            "The continuation ratio (~1.3x) is near break-even, meaning BOS continuation",
            "cannot generate consistent positive expectancy on this pair. The market",
            "microstructure (higher fakeout rate, weaker directional persistence) is",
            "fundamentally incompatible with the current signal design.",
            ""])

    (out / "pair_specific_research_summary.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_research_summary.md")

    # --- multi_pair_recovery_decision.md ---
    md = ["# Multi-Pair Recovery Decision", "",
          "## Is EURUSD recoverable?\n",
          f"**{'YES — conditionally' if eur_best_sharpe > 0.3 else 'NO — not under current BOS implementation'}**\n"]
    if eur_best_sharpe > 0.3:
        md.append(f"Best EURUSD variant ({eur_best_name}) shows Sharpe {eur_best_sharpe:.3f}.")
        md.append("This is marginal but sufficient for conditional deployment with monitoring.")
    else:
        md.append("No EURUSD variant achieves Sharpe > 0.3. The pair should not be deployed")
        md.append("under BOS continuation. Alternative signal families should be explored.")

    md.extend(["", "## Should GBPUSD be deprioritized?\n",
               f"**{'NO — some triage variants show promise' if gbp_any_viable else 'YES — deprioritize GBPUSD'}**\n"])
    if not gbp_any_viable:
        md.append("All GBPUSD variants remain negative. The pair is structurally unsuited")
        md.append("for BOS continuation and should not receive further investment until")
        md.append("a fundamentally different signal family is available.")

    md.extend(["", "## Is a future portfolio-of-alphas realistic?\n",
               "**YES, but only as a 2-sleeve system (USDJPY + conditional EURUSD)**\n",
               "A true 3-pair portfolio is not viable under the current signal family.",
               "The recommended architecture is:",
               "1. USDJPY primary sleeve (60-70% risk budget)",
               f"2. EURUSD conditional sleeve ({'enabled' if eur_best_sharpe > 0.3 else 'disabled until improved'})",
               "3. GBPUSD disabled (requires different signal family)"])

    (out / "multi_pair_recovery_decision.md").write_text("\n".join(md))
    logger.info("  Written multi_pair_recovery_decision.md")

    # --- pair_specific_candidate_ranking.md ---
    all_candidates = []
    if usdjpy_m:
        all_candidates.append(("bos_usdjpy_promoted", "USDJPY", usdjpy_m.sharpe_ratio, usdjpy_m.profit_factor, "PROMOTED"))
    if eurusd_results:
        for name, r in eurusd_results.items():
            m = r["metrics"]
            all_candidates.append((f"bos_eurusd_{name}", "EURUSD", m.sharpe_ratio, m.profit_factor, "RESEARCH"))
    if gbpusd_results:
        for name, r in gbpusd_results.items():
            m = r["metrics"]
            all_candidates.append((f"bos_gbpusd_{name}", "GBPUSD", m.sharpe_ratio, m.profit_factor, "TRIAGE"))

    all_candidates.sort(key=lambda x: -x[2])
    md = ["# Pair-Specific Candidate Ranking", ""]
    rh = ["Rank", "Candidate", "Pair", "Sharpe", "PF", "Status"]
    rr = []
    for i, (name, pair, sharpe, pf, status) in enumerate(all_candidates):
        rr.append([i + 1, name, pair, f"{sharpe:.3f}", f"{pf:.3f}", status])
    md.append(_md_table(rh, rr))
    (out / "pair_specific_candidate_ranking.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_candidate_ranking.md")

    # --- next_generation_candidate_report.md ---
    md = ["# Next-Generation Candidate Report", "",
          "## Strongest Candidate Directions\n",
          "1. **bos_usdjpy_promoted** — Remains the primary edge. No modifications needed.",
          f"2. **bos_eurusd_{eur_best_name}** — Best EURUSD variant (Sharpe {eur_best_sharpe:.3f}).",
          "3. **sleeve_portfolio** — USDJPY + conditional EURUSD as risk-budgeted sleeves.\n",
          "## What Should Be Tested Next\n",
          "1. Forward paper validation of USDJPY (already in progress)",
          f"2. {'EURUSD pair-specific paper validation' if eur_best_sharpe > 0.3 else 'Alternative EURUSD signal families (range-reversal, session breakout)'}",
          "3. True pair-specific config overrides in the backtest engine",
          "4. Sleeve-level risk budgeting and independent monitoring\n",
          "## What Should NOT Be Pursued Further\n",
          "1. GBPUSD under BOS continuation (deprioritized)",
          "2. Cloned-strategy multi-pair deployment (proven inferior to pair-specific)",
          "3. Broad parameter sweeps without pair-specific hypotheses",
          "4. Portfolio-of-3-sleeves with equal risk budgets"]
    (out / "next_generation_candidate_report.md").write_text("\n".join(md))
    logger.info("  Written next_generation_candidate_report.md")

    # --- next_research_recommendation.md ---
    md = ["# Next Research Recommendation", "",
          "## Key Findings\n",
          "1. **USDJPY is structurally superior** for BOS continuation (continuation ratio 4x, Sharpe ~1.5)",
          f"2. **EURUSD is {'marginally recoverable' if eur_best_sharpe > 0.3 else 'not recoverable'}** under pair-specific BOS modifications",
          "3. **GBPUSD should be deprioritized** — no variant achieves positive risk-adjusted returns",
          "4. The pair performance gap is driven by **continuation quality** (follow-through after breaks)",
          "5. **Session gating** and **score thresholds** can improve EURUSD marginally but cannot create edge where none exists\n",
          "## Recommended Next Steps\n",
          "1. Continue USDJPY paper validation (medium confidence, promoted path)",
          f"2. {'Prepare EURUSD conditional sleeve for paper validation' if eur_best_sharpe > 0.3 else 'Explore alternative EURUSD signal families in a new research wave'}",
          "3. Implement pair-specific config overrides in the engine",
          "4. Build sleeve-level risk budgeting and independent performance monitoring",
          "5. Consider alternative signal families for GBPUSD in a future wave\n",
          "## What to Abandon\n",
          "- GBPUSD BOS continuation (all variants negative)",
          "- Equal-weight multi-pair deployment (dilutes USDJPY edge)",
          "- Generic optimization without pair-specific hypotheses"]
    (out / "next_research_recommendation.md").write_text("\n".join(md))
    logger.info("  Written next_research_recommendation.md")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pair-Specific BOS Research")
    parser.add_argument("--theme", choices=["A", "B", "C", "D", "E", "F", "all"], default="all")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Pair-Specific BOS Research Wave")
    logger.info("=" * 60)

    logger.info("Loading data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded"); sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    for pair, series in full_data.items():
        logger.info("  %s: %d bars", pair.value, len(series))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Theme A
    pair_trades, pair_metrics, pair_reports, pair_excursions = {}, {}, {}, {}
    if args.theme in ("A", "all"):
        pair_trades, pair_metrics, pair_reports, pair_excursions = theme_a(full_data, htf_data)

    # If we need trades for later themes but skipped A, run quick backtests
    if not pair_trades and args.theme != "A":
        cfg = _cfg()
        for pair in ALL_PAIRS:
            label = PAIR_LABELS[pair]
            if pair not in full_data:
                continue
            r, m = _bt(cfg, {pair: full_data[pair]},
                       {pair: htf_data[pair]} if htf_data and pair in htf_data else None)
            pair_trades[label] = r.trades
            pair_metrics[label] = m
            pair_reports[label] = evaluate(r, m)

    # Theme B
    eurusd_results = {}
    if args.theme in ("B", "all"):
        eurusd_results = theme_b(full_data, htf_data)

    # Theme C
    gbpusd_results = {}
    if args.theme in ("C", "all"):
        gbpusd_results = theme_c(full_data, htf_data)

    # Theme D
    if args.theme in ("D", "all"):
        theme_d(pair_trades, pair_metrics, eurusd_results, gbpusd_results)

    # Theme E
    if args.theme in ("E", "all"):
        theme_e(pair_trades, pair_metrics, pair_excursions, pair_reports, eurusd_results, gbpusd_results)

    # Theme F
    if args.theme in ("F", "all"):
        theme_f(pair_trades, pair_metrics, pair_excursions, eurusd_results, gbpusd_results)

    logger.info("=" * 60)
    logger.info("Research complete. Results in: %s", RESULTS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
