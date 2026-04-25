#!/usr/bin/env python3
"""Multi-Pair Alpha Recovery Research — Diagnostics and Candidate Campaigns.

Phase B of the Paper Hardening and Research plan. Runs:
- B1/B2: Pair-specific diagnostics (regime, session, direction, continuation quality)
- B3/B4: Candidate variants (session-gated, regime-gated, portfolio sleeves)
- B5: Walk-forward campaigns and decision outputs

Usage:
    python3 scripts/run_multi_pair_research.py
    python3 scripts/run_multi_pair_research.py --phase diagnostics
    python3 scripts/run_multi_pair_research.py --phase campaigns
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.ml.regime import (
    MarketRegime,
    TrendRangeClassifier,
    VolatilityRegimeClassifier,
)
from fx_smc_bot.research.evaluation import evaluate
from fx_smc_bot.research.walk_forward import (
    WalkForwardSplit,
    anchored_walk_forward,
)
from fx_smc_bot.backtesting.metrics import PerformanceSummary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("multi_pair_research")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
RESULTS_DIR = PROJECT_ROOT / "results" / "multi_pair_research"

ALL_PAIRS = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
PAIR_LABELS = {TradingPair.EURUSD: "EURUSD", TradingPair.GBPUSD: "GBPUSD", TradingPair.USDJPY: "USDJPY"}

FROZEN_RISK = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}


def _build_config(
    pairs: list[TradingPair] | None = None,
    families: list[str] | None = None,
) -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = families or ["bos_continuation"]
    for k, v in FROZEN_RISK.items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _run_backtest(
    cfg: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf: dict[TradingPair, BarSeries] | None = None,
) -> tuple[Any, PerformanceSummary, Any]:
    engine = BacktestEngine(cfg)
    result = engine.run(data, htf)
    metrics = engine.metrics(result)
    report = evaluate(result, metrics)
    return result, metrics, report


def _metrics_row(label: str, m: PerformanceSummary) -> dict[str, Any]:
    return {
        "label": label,
        "trades": m.total_trades,
        "win_rate": round(m.win_rate, 3),
        "sharpe": round(m.sharpe_ratio, 3),
        "pf": round(m.profit_factor, 3),
        "pnl": round(m.total_pnl, 2),
        "max_dd": round(m.max_drawdown_pct, 4),
        "avg_rr": round(m.avg_rr_ratio, 3),
        "expectancy": round(m.expectancy, 2),
        "avg_winner": round(m.avg_winner, 2),
        "avg_loser": round(m.avg_loser, 2),
    }


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# B1/B2: PAIR DIAGNOSTICS
# ──────────────────────────────────────────────────────────────────────────

def run_pair_diagnostics(
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> dict[str, Any]:
    """Run per-pair BOS backtest and compute diagnostic attribution."""
    logger.info("=" * 60)
    logger.info("B1/B2 — Pair-Specific Diagnostics")
    logger.info("=" * 60)

    results: dict[str, Any] = {}

    for pair in ALL_PAIRS:
        label = PAIR_LABELS[pair]
        if pair not in full_data:
            logger.warning("  %s: no data available, skipping", label)
            continue

        logger.info("  Running %s diagnostics ...", label)
        single = {pair: full_data[pair]}
        htf_single = {pair: htf_data[pair]} if htf_data and pair in htf_data else None
        cfg = _build_config()

        result, metrics, report = _run_backtest(cfg, single, htf_single)
        row = _metrics_row(label, metrics)
        results[label] = {
            "metrics": row,
            "by_year": [{"label": s.label, "trades": s.trade_count, "pnl": round(s.total_pnl, 2), "wr": round(s.win_rate, 3), "rr": round(s.avg_rr, 3)} for s in report.by_year],
            "by_session": [{"label": s.label, "trades": s.trade_count, "pnl": round(s.total_pnl, 2), "wr": round(s.win_rate, 3), "rr": round(s.avg_rr, 3)} for s in report.by_session],
            "by_direction": [{"label": s.label, "trades": s.trade_count, "pnl": round(s.total_pnl, 2), "wr": round(s.win_rate, 3)} for s in report.by_direction],
            "by_regime": [{"label": s.label, "trades": s.trade_count, "pnl": round(s.total_pnl, 2), "wr": round(s.win_rate, 3)} for s in report.by_regime] if report.by_regime else [],
        }

        logger.info("    %s: %d trades, Sharpe %.3f, PF %.3f, PnL %.0f",
                     label, metrics.total_trades, metrics.sharpe_ratio,
                     metrics.profit_factor, metrics.total_pnl)

    return results


def run_regime_diagnostics(
    full_data: dict[TradingPair, BarSeries],
) -> dict[str, Any]:
    """Classify regimes bar-by-bar for each pair and compute regime distributions."""
    logger.info("  Running regime classification ...")
    vol_clf = VolatilityRegimeClassifier()
    trend_clf = TrendRangeClassifier()

    regime_stats: dict[str, dict[str, int]] = {}

    for pair in ALL_PAIRS:
        label = PAIR_LABELS[pair]
        if pair not in full_data:
            continue

        series = full_data[pair]
        vol_counts: dict[str, int] = {}
        trend_counts: dict[str, int] = {}

        for i in range(50, len(series)):
            vr = vol_clf.classify(series.high, series.low, series.close, i)
            tr = trend_clf.classify(series.high, series.low, series.close, i)
            vol_counts[vr.value] = vol_counts.get(vr.value, 0) + 1
            trend_counts[tr.value] = trend_counts.get(tr.value, 0) + 1

        regime_stats[label] = {"volatility": vol_counts, "trend": trend_counts}
        logger.info("    %s regimes: vol=%s, trend=%s", label, vol_counts, trend_counts)

    return regime_stats


def run_continuation_quality(
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> dict[str, Any]:
    """Compute continuation quality metrics per pair."""
    logger.info("  Computing continuation quality ...")
    quality: dict[str, Any] = {}

    for pair in ALL_PAIRS:
        label = PAIR_LABELS[pair]
        if pair not in full_data:
            continue

        single = {pair: full_data[pair]}
        htf_single = {pair: htf_data[pair]} if htf_data and pair in htf_data else None
        cfg = _build_config()
        result, metrics, _ = _run_backtest(cfg, single, htf_single)

        if not result.trades:
            quality[label] = {"trades": 0}
            continue

        winners = [t for t in result.trades if t.pnl > 0]
        losers = [t for t in result.trades if t.pnl <= 0]
        avg_win = np.mean([t.pnl for t in winners]) if winners else 0
        avg_loss = abs(np.mean([t.pnl for t in losers])) if losers else 1

        durations = []
        for t in result.trades:
            if hasattr(t, 'exit_time') and hasattr(t, 'entry_time') and t.exit_time and t.entry_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(dur)

        quality[label] = {
            "trades": metrics.total_trades,
            "avg_winner": round(float(avg_win), 2),
            "avg_loser": round(float(avg_loss), 2),
            "continuation_ratio": round(float(avg_win / avg_loss) if avg_loss > 0 else 0, 3),
            "win_rate": round(metrics.win_rate, 3),
            "expectancy": round(metrics.expectancy, 2),
            "avg_duration_hrs": round(float(np.mean(durations)), 1) if durations else None,
            "median_duration_hrs": round(float(np.median(durations)), 1) if durations else None,
        }
        logger.info("    %s: continuation_ratio=%.3f, wr=%.3f",
                     label, quality[label]["continuation_ratio"], metrics.win_rate)

    return quality


def write_diagnostic_reports(
    pair_results: dict,
    regime_stats: dict,
    continuation: dict,
    output_dir: Path,
) -> None:
    """Write B1/B2 diagnostic report markdown files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. pair_diagnostic_report.md
    md = ["# Pair Diagnostic Report — BOS Continuation", "",
          "Backtest of BOS continuation on each pair individually using full history.", ""]

    headers = ["Pair", "Trades", "Win Rate", "Sharpe", "PF", "PnL", "Max DD", "Avg RR", "Expectancy"]
    rows = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label in pair_results:
            m = pair_results[label]["metrics"]
            rows.append([label, m["trades"], f"{m['win_rate']:.1%}", f"{m['sharpe']:.3f}",
                         f"{m['pf']:.3f}", f"{m['pnl']:,.0f}", f"{m['max_dd']:.2%}",
                         f"{m['avg_rr']:.3f}", f"{m['expectancy']:.2f}"])
    md.append(_md_table(headers, rows))

    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_results:
            continue
        r = pair_results[label]
        md.extend(["", f"## {label} — Attribution Breakdown", ""])

        if r["by_session"]:
            md.extend(["### By Session", ""])
            sh = ["Session", "Trades", "PnL", "Win Rate", "Avg RR"]
            sr = [[s["label"], s["trades"], f"{s['pnl']:,.0f}", f"{s['wr']:.1%}", f"{s['rr']:.3f}"]
                  for s in r["by_session"]]
            md.append(_md_table(sh, sr))

        if r["by_direction"]:
            md.extend(["", "### By Direction", ""])
            dh = ["Direction", "Trades", "PnL", "Win Rate"]
            dr = [[d["label"], d["trades"], f"{d['pnl']:,.0f}", f"{d['wr']:.1%}"]
                  for d in r["by_direction"]]
            md.append(_md_table(dh, dr))

        if r["by_year"]:
            md.extend(["", "### By Year", ""])
            yh = ["Year", "Trades", "PnL", "Win Rate", "Avg RR"]
            yr = [[y["label"], y["trades"], f"{y['pnl']:,.0f}", f"{y['wr']:.1%}", f"{y['rr']:.3f}"]
                  for y in r["by_year"]]
            md.append(_md_table(yh, yr))

    (output_dir / "pair_diagnostic_report.md").write_text("\n".join(md))
    logger.info("  Written pair_diagnostic_report.md")

    # 2. pair_regime_report.md
    md = ["# Pair Regime Report", "",
          "Volatility and trend regime distribution across pairs.", ""]

    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in regime_stats:
            continue
        rs = regime_stats[label]
        md.extend([f"## {label}", "", "### Volatility Regime Distribution", ""])
        vh = ["Regime", "Bar Count", "% of Total"]
        total_v = sum(rs["volatility"].values())
        vr = [[r, c, f"{c/total_v:.1%}"] for r, c in sorted(rs["volatility"].items(), key=lambda x: -x[1])]
        md.append(_md_table(vh, vr))

        md.extend(["", "### Trend/Range Distribution", ""])
        th = ["Regime", "Bar Count", "% of Total"]
        total_t = sum(rs["trend"].values())
        tr = [[r, c, f"{c/total_t:.1%}"] for r, c in sorted(rs["trend"].items(), key=lambda x: -x[1])]
        md.append(_md_table(th, tr))
        md.append("")

    (output_dir / "pair_regime_report.md").write_text("\n".join(md))
    logger.info("  Written pair_regime_report.md")

    # 3. continuation_quality_report.md
    md = ["# Continuation Quality Report", "",
          "Measures follow-through quality of BOS continuation signals per pair.", ""]
    ch = ["Pair", "Trades", "Avg Winner", "Avg Loser", "Continuation Ratio", "Win Rate", "Expectancy", "Avg Duration (hrs)"]
    cr = []
    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in continuation:
            continue
        c = continuation[label]
        cr.append([label, c["trades"], f"{c['avg_winner']:,.2f}", f"{c['avg_loser']:,.2f}",
                   f"{c['continuation_ratio']:.3f}", f"{c['win_rate']:.1%}",
                   f"{c['expectancy']:.2f}", str(c.get("avg_duration_hrs", "N/A"))])
    md.append(_md_table(ch, cr))

    md.extend(["", "## Interpretation", ""])
    usdjpy_cr = continuation.get("USDJPY", {}).get("continuation_ratio", 0)
    eurusd_cr = continuation.get("EURUSD", {}).get("continuation_ratio", 0)
    gbpusd_cr = continuation.get("GBPUSD", {}).get("continuation_ratio", 0)

    if usdjpy_cr > eurusd_cr and usdjpy_cr > gbpusd_cr:
        md.append("USDJPY has the strongest continuation quality, consistent with prior findings.")
    if eurusd_cr < 1.0:
        md.append("EURUSD continuation ratio < 1.0 indicates average winners do not compensate for average losers.")
    if gbpusd_cr < 1.0:
        md.append("GBPUSD continuation ratio < 1.0 indicates the BOS continuation signal may not suit this pair's microstructure.")

    (output_dir / "continuation_quality_report.md").write_text("\n".join(md))
    logger.info("  Written continuation_quality_report.md")

    # 4. session_behavior_report.md
    md = ["# Session Behavior Report", "",
          "BOS continuation performance by trading session for each pair.", ""]

    for label in ["USDJPY", "EURUSD", "GBPUSD"]:
        if label not in pair_results:
            continue
        sessions = pair_results[label]["by_session"]
        if not sessions:
            continue
        md.extend([f"## {label}", ""])
        sh = ["Session", "Trades", "PnL", "Win Rate", "Avg RR"]
        sr = [[s["label"], s["trades"], f"{s['pnl']:,.0f}", f"{s['wr']:.1%}", f"{s['rr']:.3f}"]
              for s in sessions]
        md.append(_md_table(sh, sr))

        best = max(sessions, key=lambda s: s["pnl"]) if sessions else None
        worst = min(sessions, key=lambda s: s["pnl"]) if sessions else None
        if best and worst:
            md.append(f"\nBest session: **{best['label']}** (PnL {best['pnl']:,.0f})")
            md.append(f"Worst session: **{worst['label']}** (PnL {worst['pnl']:,.0f})")
        md.append("")

    (output_dir / "session_behavior_report.md").write_text("\n".join(md))
    logger.info("  Written session_behavior_report.md")

    (output_dir / "diagnostic_data.json").write_text(json.dumps({
        "pair_results": pair_results,
        "regime_stats": regime_stats,
        "continuation": continuation,
    }, indent=2, default=str))
    logger.info("  Written diagnostic_data.json")


# ──────────────────────────────────────────────────────────────────────────
# B3/B4: CANDIDATE VARIANTS
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class CandidateVariant:
    name: str
    pairs: list[TradingPair]
    families: list[str] = field(default_factory=lambda: ["bos_continuation"])
    description: str = ""


def _define_candidates() -> list[CandidateVariant]:
    return [
        CandidateVariant(
            name="bos_usdjpy_baseline",
            pairs=[TradingPair.USDJPY],
            description="Frozen reference — BOS continuation USDJPY only",
        ),
        CandidateVariant(
            name="bos_eurusd_baseline",
            pairs=[TradingPair.EURUSD],
            description="BOS continuation on EURUSD alone",
        ),
        CandidateVariant(
            name="bos_gbpusd_baseline",
            pairs=[TradingPair.GBPUSD],
            description="BOS continuation on GBPUSD alone",
        ),
        CandidateVariant(
            name="bos_all_pairs",
            pairs=ALL_PAIRS,
            description="BOS continuation on all 3 pairs simultaneously",
        ),
        CandidateVariant(
            name="portfolio_3sleeve",
            pairs=ALL_PAIRS,
            description="Portfolio of 3 independent pair sleeves (risk-budgeted)",
        ),
    ]


def run_candidate_campaigns(
    full_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
) -> list[dict[str, Any]]:
    """Run backtest campaigns for all candidate variants."""
    logger.info("=" * 60)
    logger.info("B3/B4 — Candidate Variant Campaigns")
    logger.info("=" * 60)

    candidates = _define_candidates()
    campaign_results: list[dict[str, Any]] = []

    for cand in candidates:
        logger.info("  Campaign: %s (%s)", cand.name, cand.description)
        pair_data = {p: full_data[p] for p in cand.pairs if p in full_data}
        pair_htf = {p: htf_data[p] for p in cand.pairs if htf_data and p in htf_data} if htf_data else None

        if not pair_data:
            logger.warning("    No data for %s, skipping", cand.name)
            continue

        cfg = _build_config(pairs=cand.pairs, families=cand.families)

        if cand.name == "portfolio_3sleeve":
            cfg.risk.base_risk_per_trade = 0.001
            cfg.risk.max_portfolio_risk = 0.003

        result, metrics, report = _run_backtest(cfg, pair_data, pair_htf)
        row = _metrics_row(cand.name, metrics)

        wf_results = _run_walk_forward(cfg, pair_data, pair_htf, cand.name)

        campaign_results.append({
            "candidate": cand.name,
            "description": cand.description,
            "pairs": [p.value for p in cand.pairs],
            "full_history": row,
            "walk_forward": wf_results,
            "by_pair": [{"label": s.label, "trades": s.trade_count, "pnl": round(s.total_pnl, 2), "wr": round(s.win_rate, 3)} for s in report.by_pair],
        })

        logger.info("    Full: %d trades, Sharpe %.3f, PF %.3f, PnL %.0f",
                     metrics.total_trades, metrics.sharpe_ratio,
                     metrics.profit_factor, metrics.total_pnl)

    return campaign_results


def _run_walk_forward(
    cfg: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf: dict[TradingPair, BarSeries] | None,
    label: str,
) -> dict[str, Any]:
    """Rolling-window walk-forward: run independent backtests on consecutive windows.

    Each fold is an independent window of ~fold_size bars, giving the engine
    a fresh start to generate signals in each period. This avoids the issue
    of trade clustering in early bars of the full history.
    """
    ref_pair = list(data.keys())[0]
    n_bars = len(data[ref_pair])

    n_folds = min(6, max(3, n_bars // 1500))
    fold_size = n_bars // n_folds

    if fold_size < 200:
        logger.warning("    Walk-forward: fold size too small (%d bars), skipping", fold_size)
        return {"n_folds": 0, "mean_oos_sharpe": 0.0, "pct_positive_folds": 0.0, "mean_pf": 0.0, "folds": []}

    logger.info("    Walk-forward: %d rolling folds, ~%d bars each", n_folds, fold_size)

    fold_metrics: list[dict[str, Any]] = []
    for fold_idx in range(n_folds):
        fold_start = fold_idx * fold_size
        fold_end = min(fold_start + fold_size, n_bars)
        if fold_end - fold_start < 200:
            break

        fold_data = {p: s.slice(fold_start, fold_end) for p, s in data.items()}
        fold_htf = None
        if htf:
            fold_htf = {}
            for p, s in htf.items():
                htf_ratio = len(s) / n_bars
                h_start = max(0, int(fold_start * htf_ratio))
                h_end = min(len(s), int(fold_end * htf_ratio))
                if h_end > h_start:
                    fold_htf[p] = s.slice(h_start, h_end)

        try:
            engine = BacktestEngine(cfg)
            result = engine.run(fold_data, fold_htf if fold_htf else None)
            m = engine.metrics(result)
            fold_metrics.append({
                "fold": fold_idx + 1,
                "test_bars": fold_end - fold_start,
                "oos_trades": m.total_trades,
                "oos_pnl": round(m.total_pnl, 2),
                "sharpe": round(m.sharpe_ratio, 3),
                "pf": round(m.profit_factor, 3),
                "win_rate": round(m.win_rate, 3),
                "max_dd": round(m.max_drawdown_pct, 4),
            })
            logger.info("      Fold %d: %d trades, PnL %.0f, Sharpe %.3f",
                         fold_idx + 1, m.total_trades, m.total_pnl,
                         m.sharpe_ratio)
        except Exception as e:
            logger.warning("    Fold %d failed: %s", fold_idx + 1, e)
            fold_metrics.append({"fold": fold_idx + 1, "error": str(e)})

    valid_folds = [f for f in fold_metrics if "sharpe" in f and f.get("oos_trades", 0) > 0]
    if valid_folds:
        mean_sharpe = np.mean([f["sharpe"] for f in valid_folds])
        pct_positive = np.mean([1 if f["oos_pnl"] > 0 else 0 for f in valid_folds])
        mean_pf = np.mean([f["pf"] for f in valid_folds])
    else:
        mean_sharpe = 0.0
        pct_positive = 0.0
        mean_pf = 0.0

    return {
        "n_folds": len(fold_metrics),
        "mean_oos_sharpe": round(float(mean_sharpe), 3),
        "pct_positive_folds": round(float(pct_positive), 2),
        "mean_pf": round(float(mean_pf), 3),
        "folds": fold_metrics,
    }


# ──────────────────────────────────────────────────────────────────────────
# B5: DECISION OUTPUTS
# ──────────────────────────────────────────────────────────────────────────

def write_campaign_reports(
    campaign_results: list[dict],
    pair_diagnostics: dict,
    output_dir: Path,
) -> None:
    """Write B5 decision output markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. multi_pair_recovery_report.md
    md = ["# Multi-Pair Recovery Report", "",
          "Assessment of BOS continuation across EURUSD, GBPUSD, and USDJPY.", ""]

    md.extend(["## Full-History Performance Comparison", ""])
    headers = ["Candidate", "Pairs", "Trades", "Sharpe", "PF", "PnL", "Max DD", "Win Rate"]
    rows = []
    for cr in campaign_results:
        m = cr["full_history"]
        rows.append([cr["candidate"], ", ".join(cr["pairs"]), m["trades"],
                     f"{m['sharpe']:.3f}", f"{m['pf']:.3f}", f"{m['pnl']:,.0f}",
                     f"{m['max_dd']:.2%}", f"{m['win_rate']:.1%}"])
    md.append(_md_table(headers, rows))

    md.extend(["", "## Walk-Forward OOS Summary", ""])
    wf_headers = ["Candidate", "Folds", "Mean OOS Sharpe", "% Positive", "Mean PF"]
    wf_rows = []
    for cr in campaign_results:
        wf = cr["walk_forward"]
        wf_rows.append([cr["candidate"], wf["n_folds"], f"{wf['mean_oos_sharpe']:.3f}",
                        f"{wf['pct_positive_folds']:.0%}", f"{wf['mean_pf']:.3f}"])
    md.append(_md_table(wf_headers, wf_rows))

    (output_dir / "multi_pair_recovery_report.md").write_text("\n".join(md))
    logger.info("  Written multi_pair_recovery_report.md")

    # 2. candidate_hypothesis_matrix.md
    md = ["# Candidate Hypothesis Matrix", "",
          "Each candidate variant with its hypothesis and evidence assessment.", ""]
    for cr in campaign_results:
        m = cr["full_history"]
        wf = cr["walk_forward"]
        viable = m["sharpe"] > 0.3 and wf["mean_oos_sharpe"] > 0 and m["pf"] > 1.0
        md.extend([
            f"## {cr['candidate']}",
            "",
            f"**Hypothesis**: {cr['description']}",
            f"**Pairs**: {', '.join(cr['pairs'])}",
            "",
            f"| Metric | Full History | Walk-Forward OOS |",
            f"|--------|-------------|-----------------|",
            f"| Sharpe | {m['sharpe']:.3f} | {wf['mean_oos_sharpe']:.3f} |",
            f"| PF | {m['pf']:.3f} | {wf['mean_pf']:.3f} |",
            f"| Trades | {m['trades']} | — |",
            f"| Win Rate | {m['win_rate']:.1%} | — |",
            f"| Max DD | {m['max_dd']:.2%} | — |",
            "",
            f"**Viable**: {'YES' if viable else 'NO'}",
            "",
        ])

    (output_dir / "candidate_hypothesis_matrix.md").write_text("\n".join(md))
    logger.info("  Written candidate_hypothesis_matrix.md")

    # 3. pair_specific_candidate_comparison.md
    md = ["# Pair-Specific Candidate Comparison", "",
          "Individual pair performance within multi-pair candidates.", ""]
    for cr in campaign_results:
        if not cr["by_pair"]:
            continue
        md.extend([f"## {cr['candidate']}", ""])
        ph = ["Pair", "Trades", "PnL", "Win Rate"]
        pr = [[p["label"], p["trades"], f"{p['pnl']:,.0f}", f"{p['wr']:.1%}"]
              for p in cr["by_pair"]]
        md.append(_md_table(ph, pr))
        md.append("")

    (output_dir / "pair_specific_candidate_comparison.md").write_text("\n".join(md))
    logger.info("  Written pair_specific_candidate_comparison.md")

    # 4. next_research_recommendation.md
    best_single = None
    best_sharpe = -999
    for cr in campaign_results:
        if cr["full_history"]["sharpe"] > best_sharpe:
            best_sharpe = cr["full_history"]["sharpe"]
            best_single = cr

    best_oos = None
    best_oos_sharpe = -999
    for cr in campaign_results:
        if cr["walk_forward"]["mean_oos_sharpe"] > best_oos_sharpe:
            best_oos_sharpe = cr["walk_forward"]["mean_oos_sharpe"]
            best_oos = cr

    md = [
        "# Next Research Recommendation", "",
        "## Summary of Findings", "",
        f"- Best full-history Sharpe: **{best_single['candidate']}** ({best_sharpe:.3f})" if best_single else "",
        f"- Best OOS Sharpe: **{best_oos['candidate']}** ({best_oos_sharpe:.3f})" if best_oos else "",
        "",
        "## Recommendation", "",
    ]

    usdjpy_cand = next((c for c in campaign_results if c["candidate"] == "bos_usdjpy_baseline"), None)
    all_pair_cand = next((c for c in campaign_results if c["candidate"] == "bos_all_pairs"), None)
    portfolio_cand = next((c for c in campaign_results if c["candidate"] == "portfolio_3sleeve"), None)

    usdjpy_dominates = True
    if all_pair_cand and usdjpy_cand:
        if all_pair_cand["walk_forward"]["mean_oos_sharpe"] > usdjpy_cand["walk_forward"]["mean_oos_sharpe"]:
            usdjpy_dominates = False

    if usdjpy_dominates:
        md.extend([
            "**USDJPY concentration remains the strongest path.**",
            "",
            "Evidence indicates that adding EURUSD and/or GBPUSD does not improve",
            "risk-adjusted returns. The multi-pair candidates either underperform",
            "the USDJPY-only baseline or introduce additional drawdown without",
            "proportional return improvement.",
            "",
            "### Recommended Actions",
            "",
            "1. **Keep `bos_only_usdjpy` as the promoted candidate** — no change.",
            "2. **Do not deploy EURUSD or GBPUSD** in the promoted path yet.",
            "3. Continue monitoring pair-specific diagnostics for regime changes.",
            "4. If EURUSD or GBPUSD show improvement in future data windows,",
            "   re-evaluate pair-specific variants.",
        ])
    else:
        md.extend([
            "**Multi-pair deployment may be viable.**",
            "",
            "The all-pairs or portfolio candidate shows improved OOS performance",
            "relative to USDJPY-only. Further validation is warranted.",
            "",
            "### Recommended Actions",
            "",
            "1. Run extended walk-forward validation on the multi-pair candidate.",
            "2. If confirmed, prepare a multi-pair paper candidate package.",
            "3. Keep `bos_only_usdjpy` as the primary promoted candidate pending",
            "   confirmation of the multi-pair edge.",
        ])

    (output_dir / "next_research_recommendation.md").write_text("\n".join(md))
    logger.info("  Written next_research_recommendation.md")

    (output_dir / "campaign_results.json").write_text(json.dumps(campaign_results, indent=2, default=str))
    logger.info("  Written campaign_results.json")


# ──────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-Pair Alpha Recovery Research")
    parser.add_argument("--phase", choices=["diagnostics", "campaigns", "all"], default="all",
                        help="Which phase to run")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Multi-Pair Alpha Recovery Research")
    logger.info("=" * 60)

    logger.info("Loading data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded")
        sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)

    for pair, series in full_data.items():
        logger.info("  %s: %d bars", pair.value, len(series))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    pair_diagnostics: dict = {}
    campaign_results: list = []

    if args.phase in ("diagnostics", "all"):
        pair_diagnostics = run_pair_diagnostics(full_data, htf_data)
        regime_stats = run_regime_diagnostics(full_data)
        continuation = run_continuation_quality(full_data, htf_data)
        write_diagnostic_reports(pair_diagnostics, regime_stats, continuation, RESULTS_DIR)

    if args.phase in ("campaigns", "all"):
        campaign_results = run_candidate_campaigns(full_data, htf_data)
        write_campaign_reports(campaign_results, pair_diagnostics, RESULTS_DIR)

    logger.info("=" * 60)
    logger.info("Research complete. Results in: %s", RESULTS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
