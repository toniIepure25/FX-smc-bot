#!/usr/bin/env python3
"""Alternative Alpha Discovery Research.

Tests non-BOS signal families on EURUSD and GBPUSD to find pair-appropriate edges.
Produces full report suite for B2-B5 themes.

Usage:
    python3 scripts/run_alpha_discovery.py
"""
from __future__ import annotations

import json
import logging
import sys
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s")
logger = logging.getLogger("alpha_discovery")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
RESULTS_DIR = PROJECT_ROOT / "results" / "alpha_discovery"

PAIR_LABELS = {TradingPair.EURUSD: "EURUSD", TradingPair.GBPUSD: "GBPUSD", TradingPair.USDJPY: "USDJPY"}
FROZEN_RISK = {"base_risk_per_trade": 0.003, "max_portfolio_risk": 0.009, "circuit_breaker_threshold": 0.125}


def _safe_div(a, b, default=0.0):
    return a / b if b else default


def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def _cfg(families: list[str]) -> AppConfig:
    c = AppConfig()
    c.alpha.enabled_families = families
    c.alpha.min_signal_score = 0.10
    c.risk.min_reward_risk_ratio = 1.5
    c.ml.enable_regime_tagging = True
    for k, v in FROZEN_RISK.items():
        setattr(c.risk, k, v)
    return c


def _bt(cfg, data, htf=None):
    e = BacktestEngine(cfg)
    r = e.run(data, htf)
    m = e.metrics(r)
    return r, m


def rolling_walk_forward(cfg, data, htf, n_folds=6):
    ref_pair = list(data.keys())[0]
    n = len(data[ref_pair])
    fold_sz = n // n_folds
    if fold_sz < 200:
        return {"n_folds": 0, "folds": [], "mean_sharpe": 0.0, "pct_positive": 0.0, "mean_pf": 0.0}
    folds = []
    for i in range(n_folds):
        s, e = i * fold_sz, min((i + 1) * fold_sz, n)
        fd = {p: sr.slice(s, e) for p, sr in data.items()}
        fh = None
        if htf:
            fh = {}
            for p, sr in htf.items():
                r = len(sr) / n
                hs, he = max(0, int(s * r)), min(len(sr), int(e * r))
                if he > hs:
                    fh[p] = sr.slice(hs, he)
        try:
            eng = BacktestEngine(cfg)
            res = eng.run(fd, fh if fh else None)
            m = eng.metrics(res)
            folds.append({"fold": i + 1, "trades": m.total_trades, "sharpe": round(m.sharpe_ratio, 3),
                          "pf": round(m.profit_factor, 3), "pnl": round(m.total_pnl, 2),
                          "wr": round(m.win_rate, 3)})
        except Exception as ex:
            folds.append({"fold": i + 1, "error": str(ex)})
    valid = [f for f in folds if "sharpe" in f and f.get("trades", 0) > 0]
    ms = float(np.mean([f["sharpe"] for f in valid])) if valid else 0.0
    pp = float(np.mean([1 if f["pnl"] > 0 else 0 for f in valid])) if valid else 0.0
    mp = float(np.mean([f["pf"] for f in valid])) if valid else 0.0
    return {"n_folds": len(folds), "folds": folds, "mean_sharpe": round(ms, 3),
            "pct_positive": round(pp, 2), "mean_pf": round(mp, 3)}


# ═══════════════════════════════════════════════════════════════════
# Hypothesis definitions
# ═══════════════════════════════════════════════════════════════════

HYPOTHESES = {
    TradingPair.EURUSD: {
        "E1_session_breakout": {"families": ["session_breakout"], "label": "Session Breakout",
                                 "rationale": "EURUSD has strong London open expansion"},
        "E2_mean_reversion": {"families": ["mean_reversion"], "label": "Mean Reversion",
                               "rationale": "EURUSD trades in tighter ranges than USDJPY"},
        "E3_momentum": {"families": ["momentum"], "label": "Momentum (Donchian)",
                         "rationale": "Channel breakout may capture EURUSD directional moves"},
        "E4_sweep_reversal": {"families": ["sweep_reversal"], "label": "Sweep Reversal",
                               "rationale": "Liquidity sweeps may be more reliable on EURUSD"},
    },
    TradingPair.GBPUSD: {
        "G1_session_breakout": {"families": ["session_breakout"], "label": "Session Breakout",
                                 "rationale": "GBPUSD has largest London session range expansion"},
        "G2_momentum": {"families": ["momentum"], "label": "Momentum (Donchian)",
                         "rationale": "GBPUSD trends aggressively when it moves"},
        "G3_mean_reversion": {"families": ["mean_reversion"], "label": "Mean Reversion",
                               "rationale": "Fade compression extremes during low-vol periods"},
    },
}

# Evaluation thresholds
PASS_SHARPE = 0.3
PASS_PF = 1.2
PASS_WF_SHARPE = 0.0
PASS_WF_PCT = 0.50
PASS_TRADES = 30


def run_hypothesis(pair, name, spec, data, htf):
    """Run a single hypothesis: full backtest + walk-forward."""
    cfg = _cfg(spec["families"])
    single = {pair: data[pair]}
    htf_s = {pair: htf[pair]} if htf and pair in htf else None

    logger.info("    Running backtest ...")
    result, metrics = _bt(cfg, single, htf_s)

    logger.info("    Running walk-forward ...")
    wf = rolling_walk_forward(cfg, single, htf_s)

    # Evaluate pass/fail
    passes = 0
    checks = {}
    checks["sharpe_pass"] = metrics.sharpe_ratio >= PASS_SHARPE
    checks["pf_pass"] = metrics.profit_factor >= PASS_PF
    checks["wf_sharpe_pass"] = wf["mean_sharpe"] > PASS_WF_SHARPE
    checks["wf_pct_pass"] = wf["pct_positive"] >= PASS_WF_PCT
    checks["trades_pass"] = metrics.total_trades >= PASS_TRADES
    passes = sum(1 for v in checks.values() if v)

    if passes >= 5:
        verdict = "PASS"
    elif passes >= 3:
        verdict = "CONDITIONAL"
    else:
        verdict = "FAIL"

    # Session decomposition
    sess_breakdown = {}
    for t in result.trades:
        s = t.session.value if t.session else "unknown"
        sess_breakdown.setdefault(s, []).append(t.pnl)

    # Direction decomposition
    longs = [t for t in result.trades if t.direction == Direction.LONG]
    shorts = [t for t in result.trades if t.direction == Direction.SHORT]

    return {
        "name": name,
        "label": spec["label"],
        "rationale": spec["rationale"],
        "pair": pair.value,
        "metrics": metrics,
        "wf": wf,
        "result": result,
        "checks": checks,
        "passes": passes,
        "verdict": verdict,
        "session_breakdown": {k: {"count": len(v), "pnl": round(sum(v), 2)} for k, v in sess_breakdown.items()},
        "long_count": len(longs),
        "long_pnl": round(sum(t.pnl for t in longs), 2),
        "short_count": len(shorts),
        "short_pnl": round(sum(t.pnl for t in shorts), 2),
    }


# ═══════════════════════════════════════════════════════════════════
# Report writers
# ═══════════════════════════════════════════════════════════════════

def write_eurusd_reports(results: list[dict]):
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- eurusd_candidate_matrix.md ---
    md = ["# EURUSD Candidate Matrix", "",
          "Alternative alpha families tested for EURUSD edge recovery.", ""]
    h = ["ID", "Family", "Trades", "Sharpe", "PF", "WR", "WF Sharpe", "WF % Pos", "Checks Passed", "Verdict"]
    rows = []
    for r in sorted(results, key=lambda x: -x["metrics"].sharpe_ratio):
        m = r["metrics"]
        wf = r["wf"]
        rows.append([r["name"], r["label"], m.total_trades, f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                     f"{m.win_rate:.1%}", f"{wf['mean_sharpe']:.3f}", f"{wf['pct_positive']:.0%}",
                     f"{r['passes']}/5", r["verdict"]])
    md.append(_md_table(h, rows))
    (out / "eurusd_candidate_matrix.md").write_text("\n".join(md))

    # --- eurusd_alpha_discovery_report.md ---
    md = ["# EURUSD Alpha Discovery Report", "",
          "Detailed results from alternative alpha family experiments.", ""]
    for r in results:
        m = r["metrics"]
        wf = r["wf"]
        md.append(f"## {r['name']}: {r['label']}\n")
        md.append(f"**Hypothesis**: {r['rationale']}\n")
        md.append(f"**Verdict**: **{r['verdict']}** ({r['passes']}/5 criteria passed)\n")
        md.append(f"| Metric | Value | Threshold | Pass? |")
        md.append(f"|---|---|---|---|")
        md.append(f"| Sharpe | {m.sharpe_ratio:.3f} | >= 0.3 | {'YES' if r['checks']['sharpe_pass'] else 'NO'} |")
        md.append(f"| PF | {m.profit_factor:.3f} | >= 1.2 | {'YES' if r['checks']['pf_pass'] else 'NO'} |")
        md.append(f"| WF Sharpe | {wf['mean_sharpe']:.3f} | > 0 | {'YES' if r['checks']['wf_sharpe_pass'] else 'NO'} |")
        md.append(f"| WF % Pos | {wf['pct_positive']:.0%} | >= 50% | {'YES' if r['checks']['wf_pct_pass'] else 'NO'} |")
        md.append(f"| Trades | {m.total_trades} | >= 30 | {'YES' if r['checks']['trades_pass'] else 'NO'} |")
        md.append(f"\n- Total PnL: {m.total_pnl:,.0f}")
        md.append(f"- Max DD: {m.max_drawdown_pct:.2%}")
        md.append(f"- Longs: {r['long_count']} ({r['long_pnl']:,.0f}), Shorts: {r['short_count']} ({r['short_pnl']:,.0f})")

        # Session breakdown
        md.append(f"\n### Session Breakdown\n")
        for sess, info in sorted(r["session_breakdown"].items(), key=lambda x: -x[1]["pnl"]):
            md.append(f"- {sess}: {info['count']} trades, PnL {info['pnl']:,.0f}")
        md.append("")

    (out / "eurusd_alpha_discovery_report.md").write_text("\n".join(md))

    # --- eurusd_oos_results.md ---
    md = ["# EURUSD OOS (Walk-Forward) Results", ""]
    for r in results:
        wf = r["wf"]
        md.append(f"## {r['name']}\n")
        if wf["folds"]:
            fh = ["Fold", "Trades", "Sharpe", "PF", "PnL", "WR"]
            fr = []
            for f in wf["folds"]:
                if "error" in f:
                    fr.append([f["fold"], "-", "-", "-", f["error"], "-"])
                else:
                    fr.append([f["fold"], f["trades"], f["sharpe"], f["pf"], f"{f['pnl']:,.0f}", f"{f['wr']:.1%}"])
            md.append(_md_table(fh, fr))
        md.append(f"\n- Mean Sharpe: {wf['mean_sharpe']:.3f}")
        md.append(f"- % Positive: {wf['pct_positive']:.0%}")
        md.append(f"- Mean PF: {wf['mean_pf']:.3f}\n")
    (out / "eurusd_oos_results.md").write_text("\n".join(md))

    # --- eurusd_next_steps.md ---
    any_pass = any(r["verdict"] in ("PASS", "CONDITIONAL") for r in results)
    best = max(results, key=lambda r: r["metrics"].sharpe_ratio) if results else None

    md = ["# EURUSD Next Steps", ""]
    if any_pass:
        passing = [r for r in results if r["verdict"] in ("PASS", "CONDITIONAL")]
        md.append("## Viable Directions Found\n")
        for r in passing:
            md.append(f"- **{r['label']}** ({r['name']}): Sharpe {r['metrics'].sharpe_ratio:.3f}, "
                      f"verdict {r['verdict']}")
        md.append(f"\n## Recommended Next Steps\n")
        md.append(f"1. Deep dive on {passing[0]['label']} for EURUSD")
        md.append(f"2. Parameter sensitivity analysis")
        md.append(f"3. Regime-conditional gating")
        md.append(f"4. Paper validation if results hold")
    else:
        md.append("## No Viable Alternative Found\n")
        md.append("None of the tested alpha families passed the minimum criteria for EURUSD.")
        if best:
            md.append(f"\nBest performer was **{best['label']}** (Sharpe {best['metrics'].sharpe_ratio:.3f}) "
                      f"but this fails the minimum Sharpe threshold of 0.3.")
        md.append(f"\n## Recommended Next Steps\n")
        md.append("1. **Deprioritize EURUSD** for current deployment")
        md.append("2. Consider higher-timeframe analysis (H4 or Daily)")
        md.append("3. Consider different market structure definitions")
        md.append("4. Revisit if new signal concepts emerge from external research")

    (out / "eurusd_next_steps.md").write_text("\n".join(md))
    logger.info("  Written EURUSD reports (4 files)")


def write_gbpusd_reports(results: list[dict]):
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- gbpusd_candidate_matrix.md ---
    md = ["# GBPUSD Candidate Matrix", ""]
    h = ["ID", "Family", "Trades", "Sharpe", "PF", "WR", "WF Sharpe", "WF % Pos", "Checks Passed", "Verdict"]
    rows = []
    for r in sorted(results, key=lambda x: -x["metrics"].sharpe_ratio):
        m = r["metrics"]
        wf = r["wf"]
        rows.append([r["name"], r["label"], m.total_trades, f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                     f"{m.win_rate:.1%}", f"{wf['mean_sharpe']:.3f}", f"{wf['pct_positive']:.0%}",
                     f"{r['passes']}/5", r["verdict"]])
    md.append(_md_table(h, rows))
    (out / "gbpusd_candidate_matrix.md").write_text("\n".join(md))

    # --- gbpusd_alpha_discovery_report.md ---
    md = ["# GBPUSD Alpha Discovery Report", ""]
    for r in results:
        m = r["metrics"]
        wf = r["wf"]
        md.append(f"## {r['name']}: {r['label']}\n")
        md.append(f"**Hypothesis**: {r['rationale']}")
        md.append(f"\n**Verdict**: **{r['verdict']}** ({r['passes']}/5 criteria passed)\n")
        md.append(f"- Sharpe: {m.sharpe_ratio:.3f}, PF: {m.profit_factor:.3f}, Trades: {m.total_trades}")
        md.append(f"- WF Sharpe: {wf['mean_sharpe']:.3f}, WF % Pos: {wf['pct_positive']:.0%}")
        md.append(f"- Total PnL: {m.total_pnl:,.0f}, Max DD: {m.max_drawdown_pct:.2%}\n")
    (out / "gbpusd_alpha_discovery_report.md").write_text("\n".join(md))

    # --- gbpusd_decision_update.md ---
    any_pass = any(r["verdict"] in ("PASS", "CONDITIONAL") for r in results)
    md = ["# GBPUSD Decision Update", ""]
    if any_pass:
        passing = [r for r in results if r["verdict"] in ("PASS", "CONDITIONAL")]
        md.append("## Decision: CONTINUE LIMITED RESEARCH\n")
        for r in passing:
            md.append(f"- **{r['label']}** shows promise (Sharpe {r['metrics'].sharpe_ratio:.3f})")
        md.append("\nRecommend one focused deep-dive on the best variant before final decision.")
    else:
        md.append("## Decision: DEPRIORITIZE GBPUSD\n")
        md.append("No alternative alpha family produced viable results for GBPUSD.")
        md.append("Both BOS continuation (previous research) and all alternative families tested")
        md.append("(session breakout, momentum, mean reversion) fail to generate consistent edge.\n")
        md.append("### Rationale\n")
        for r in results:
            md.append(f"- {r['label']}: Sharpe {r['metrics'].sharpe_ratio:.3f}, "
                      f"PF {r['metrics'].profit_factor:.3f} — **{r['verdict']}**")
        md.append("\n### Recommendation\n")
        md.append("1. Abandon GBPUSD for current strategy generation")
        md.append("2. Do not allocate further research budget")
        md.append("3. Revisit only with fundamentally new signal concepts or data sources")

    (out / "gbpusd_decision_update.md").write_text("\n".join(md))
    logger.info("  Written GBPUSD reports (3 files)")


def write_campaign_reports(eur_results, gbp_results):
    """B4/B5 combined analytics and decision reports."""
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    all_results = eur_results + gbp_results

    # --- advanced_quant_analytics_report.md ---
    md = ["# Advanced Quant Analytics Report", "",
          "Cross-family, cross-pair analytics for alternative alpha discovery.", ""]

    md.append("## Family Comparison Across Pairs\n")
    family_map: dict[str, list[dict]] = {}
    for r in all_results:
        family_map.setdefault(r["label"], []).append(r)

    for family, items in sorted(family_map.items()):
        md.append(f"### {family}\n")
        fh = ["Pair", "Trades", "Sharpe", "PF", "WF Sharpe", "Verdict"]
        fr = []
        for r in items:
            m = r["metrics"]
            wf = r["wf"]
            fr.append([r["pair"], m.total_trades, f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                       f"{wf['mean_sharpe']:.3f}", r["verdict"]])
        md.append(_md_table(fh, fr))
        md.append("")

    # Capital efficiency
    md.append("## Capital Efficiency Ranking\n")
    ch = ["Candidate", "Pair", "Return/DD Ratio", "Sharpe", "Composite"]
    cr = []
    for r in sorted(all_results, key=lambda x: -x["metrics"].sharpe_ratio):
        m = r["metrics"]
        ret_dd = _safe_div(m.annualized_return, m.max_drawdown_pct)
        composite = min(40, max(0, m.sharpe_ratio * 20)) + min(20, max(0, (m.profit_factor - 1) * 10))
        cr.append([r["name"], r["pair"], f"{ret_dd:.2f}", f"{m.sharpe_ratio:.3f}", f"{composite:.1f}"])
    md.append(_md_table(ch, cr))

    (out / "advanced_quant_analytics_report.md").write_text("\n".join(md))

    # --- sleeve_scorecards.md ---
    md = ["# Sleeve Scorecards", "",
          "Deployment readiness scoring for all tested candidates.", ""]
    sh = ["Candidate", "Pair", "Family", "Sharpe", "PF", "WR", "WF Sharpe", "Score", "Readiness"]
    sr = []
    for r in sorted(all_results, key=lambda x: -x["metrics"].sharpe_ratio):
        m = r["metrics"]
        wf = r["wf"]
        sc = (min(40, max(0, m.sharpe_ratio * 20)) + min(20, max(0, (m.profit_factor - 1) * 10)) +
              min(15, max(0, (m.win_rate - 0.2) * 50)) + min(15, max(0, (0.15 - m.max_drawdown_pct) * 100)) +
              min(10, max(0, m.total_trades / 50)))
        readiness = "READY" if sc >= 60 else "CONDITIONAL" if sc >= 35 else "NOT READY"
        sr.append([r["name"], r["pair"], r["label"], f"{m.sharpe_ratio:.3f}", f"{m.profit_factor:.3f}",
                   f"{m.win_rate:.1%}", f"{wf['mean_sharpe']:.3f}", f"{sc:.1f}/100", readiness])
    md.append(_md_table(sh, sr))
    (out / "sleeve_scorecards.md").write_text("\n".join(md))

    # --- regime_edge_maps.md ---
    md = ["# Regime Edge Maps", "",
          "Where does each candidate family find edge across regimes?", ""]
    for r in all_results:
        if not r["result"].trades:
            continue
        md.append(f"## {r['name']} ({r['pair']})\n")
        regime_groups: dict[str, list] = {}
        for t in r["result"].trades:
            rg = t.regime or "unknown"
            regime_groups.setdefault(rg, []).append(t)
        rh = ["Regime", "Trades", "Win Rate", "PnL", "Avg PnL"]
        rr = []
        for rn, grp in sorted(regime_groups.items(), key=lambda x: -sum(t.pnl for t in x[1])):
            wr = _safe_div(sum(1 for t in grp if t.pnl > 0), len(grp))
            pnl = sum(t.pnl for t in grp)
            rr.append([rn, len(grp), f"{wr:.1%}", f"{pnl:,.0f}", f"{_safe_div(pnl, len(grp)):,.2f}"])
        md.append(_md_table(rh, rr))
        md.append("")
    (out / "regime_edge_maps.md").write_text("\n".join(md))

    # --- candidate_quality_metrics.md ---
    md = ["# Candidate Quality Metrics", "",
          "Detailed quality assessment per candidate.", ""]
    for r in sorted(all_results, key=lambda x: -x["metrics"].sharpe_ratio):
        m = r["metrics"]
        wf = r["wf"]
        md.append(f"## {r['name']} ({r['pair']} — {r['label']})\n")
        md.append(f"| Metric | Value |")
        md.append(f"|---|---|")
        md.append(f"| Sharpe | {m.sharpe_ratio:.3f} |")
        md.append(f"| Sortino | {m.sortino_ratio:.3f} |")
        md.append(f"| Calmar | {m.calmar_ratio:.3f} |")
        md.append(f"| PF | {m.profit_factor:.3f} |")
        md.append(f"| Win Rate | {m.win_rate:.1%} |")
        md.append(f"| Avg Winner | {m.avg_winner:,.2f} |")
        md.append(f"| Avg Loser | {m.avg_loser:,.2f} |")
        md.append(f"| Expectancy | {m.expectancy:,.2f} |")
        md.append(f"| Max DD | {m.max_drawdown_pct:.2%} |")
        md.append(f"| Total Trades | {m.total_trades} |")
        md.append(f"| WF Mean Sharpe | {wf['mean_sharpe']:.3f} |")
        md.append(f"| WF % Positive | {wf['pct_positive']:.0%} |")
        cont_ratio = _safe_div(m.avg_winner, abs(m.avg_loser))
        md.append(f"| Continuation Ratio | {cont_ratio:.2f} |")
        md.append(f"| Verdict | **{r['verdict']}** |")
        md.append("")
    (out / "candidate_quality_metrics.md").write_text("\n".join(md))

    # --- alpha_discovery_campaign_report.md ---
    md = ["# Alpha Discovery Campaign Report", "",
          "Summary of the complete alternative alpha discovery campaign.", ""]

    eur_any = any(r["verdict"] in ("PASS", "CONDITIONAL") for r in eur_results)
    gbp_any = any(r["verdict"] in ("PASS", "CONDITIONAL") for r in gbp_results)

    md.append("## Campaign Summary\n")
    md.append(f"- Total hypotheses tested: {len(all_results)}")
    md.append(f"- EURUSD hypotheses: {len(eur_results)} (any viable: {'YES' if eur_any else 'NO'})")
    md.append(f"- GBPUSD hypotheses: {len(gbp_results)} (any viable: {'YES' if gbp_any else 'NO'})")
    pass_count = sum(1 for r in all_results if r["verdict"] == "PASS")
    cond_count = sum(1 for r in all_results if r["verdict"] == "CONDITIONAL")
    fail_count = sum(1 for r in all_results if r["verdict"] == "FAIL")
    md.append(f"- PASS: {pass_count}, CONDITIONAL: {cond_count}, FAIL: {fail_count}\n")

    md.append("## Full Results\n")
    rh = ["Rank", "Candidate", "Pair", "Family", "Sharpe", "PF", "WF Sharpe", "Verdict"]
    rr = []
    for i, r in enumerate(sorted(all_results, key=lambda x: -x["metrics"].sharpe_ratio)):
        m = r["metrics"]
        wf = r["wf"]
        rr.append([i + 1, r["name"], r["pair"], r["label"], f"{m.sharpe_ratio:.3f}",
                   f"{m.profit_factor:.3f}", f"{wf['mean_sharpe']:.3f}", r["verdict"]])
    md.append(_md_table(rh, rr))
    (out / "alpha_discovery_campaign_report.md").write_text("\n".join(md))

    # --- eurusd_gbpusd_candidate_ranking.md ---
    md = ["# EURUSD / GBPUSD Candidate Ranking", "",
          "Combined ranking of all alternative alpha candidates for non-USDJPY pairs.", ""]
    md.append(_md_table(rh, rr))
    (out / "eurusd_gbpusd_candidate_ranking.md").write_text("\n".join(md))

    # --- next_generation_sleeve_report.md ---
    md = ["# Next-Generation Sleeve Report", "",
          "Assessment of future multi-pair portfolio potential.", ""]
    md.append("## Current State\n")
    md.append("- **USDJPY**: BOS continuation — PROMOTED (Sharpe 1.49, composite 75.6/100)")
    md.append(f"- **EURUSD**: {'Has viable alternative directions' if eur_any else 'No viable alpha family found'}")
    md.append(f"- **GBPUSD**: {'Has viable alternative directions' if gbp_any else 'No viable alpha family found — DEPRIORITIZE'}\n")

    md.append("## Future Multi-Pair Portfolio Architecture\n")
    if eur_any:
        best_eur = max(eur_results, key=lambda r: r["metrics"].sharpe_ratio)
        md.append(f"### USDJPY + EURUSD (2-sleeve portfolio)")
        md.append(f"- USDJPY sleeve: BOS continuation (primary, 60-70% risk budget)")
        md.append(f"- EURUSD sleeve: {best_eur['label']} (secondary, 30-40% risk budget)")
        md.append(f"- Combined portfolio potential: diversified alpha, reduced single-pair risk\n")
    else:
        md.append("### USDJPY only (single-sleeve)")
        md.append("- No viable second sleeve identified")
        md.append("- Single-pair concentration remains the primary structural risk\n")

    md.append("## Realistic Timeline\n")
    if eur_any:
        md.append("1. Paper validate USDJPY BOS (current)")
        md.append(f"2. Deep-dive {max(eur_results, key=lambda r: r['metrics'].sharpe_ratio)['label']} for EURUSD")
        md.append("3. If confirmed: paper validate EURUSD sleeve")
        md.append("4. If both pass: deploy 2-sleeve portfolio")
    else:
        md.append("1. Paper validate USDJPY BOS (current)")
        md.append("2. Deploy USDJPY as single-pair strategy")
        md.append("3. Continue EURUSD alpha research in background")
        md.append("4. Revisit multi-pair when new signal concepts emerge")

    (out / "next_generation_sleeve_report.md").write_text("\n".join(md))

    # --- future_multi_pair_portfolio_notes.md ---
    md = ["# Future Multi-Pair Portfolio Notes", "",
          "Design considerations for eventual multi-pair deployment.", "",
          "## Current Evidence\n",
          "- USDJPY BOS continuation is the only confirmed edge",
          f"- EURUSD: {'some alternative families show promise' if eur_any else 'no confirmed alternative edge'}",
          f"- GBPUSD: {'limited promise' if gbp_any else 'no edge under any tested family'}\n",
          "## Portfolio Design Principles\n",
          "1. **Sleeve-based**: Each pair gets its own alpha family, not a cloned strategy",
          "2. **Risk-budgeted**: Risk allocation proportional to sleeve quality score",
          "3. **Independent monitoring**: Each sleeve tracked separately for invalidation",
          "4. **Correlation-aware**: Monitor JPY/EUR/GBP correlation to avoid hidden concentration",
          "5. **Additive-only**: Add sleeves only when they pass independent validation\n",
          "## Risk Budget Template\n",
          "| Sleeve | Pair | Family | Risk Share | Min Score for Activation |",
          "|---|---|---|---|---|",
          "| Primary | USDJPY | BOS Continuation | 60-70% | 60/100 |",
          f"| Secondary | EURUSD | {'TBD' if not eur_any else max(eur_results, key=lambda r: r['metrics'].sharpe_ratio)['label']} | 20-30% | 45/100 |",
          "| Tertiary | GBPUSD | TBD | 10-20% | 50/100 |"]
    (out / "future_multi_pair_portfolio_notes.md").write_text("\n".join(md))

    # --- next_research_recommendation.md ---
    md = ["# Next Research Recommendation", "",
          "## What Was Learned\n",
          f"1. Tested {len(all_results)} alternative alpha hypotheses across EURUSD and GBPUSD",
          f"2. EURUSD: {'found viable alternative' if eur_any else 'no alternative alpha family produces sufficient edge'}",
          f"3. GBPUSD: {'some promise found' if gbp_any else 'no alpha family works — deprioritize'}",
          "4. BOS continuation remains USDJPY-specific; forcing it on other pairs does not work",
          "5. Session breakout, momentum, mean reversion, and sweep reversal were all tested\n",
          "## Recommendations\n"]

    if eur_any:
        best = max(eur_results, key=lambda r: r["metrics"].sharpe_ratio)
        md.append(f"### EURUSD: CONTINUE with {best['label']}")
        md.append(f"- Best variant: {best['name']} (Sharpe {best['metrics'].sharpe_ratio:.3f})")
        md.append(f"- Next step: deep parameter exploration and regime gating")
    else:
        md.append("### EURUSD: DEPRIORITIZE for now")
        md.append("- No tested family meets minimum criteria")
        md.append("- Revisit with fundamentally new concepts (e.g., order flow, DOM-based)")

    if gbp_any:
        best_g = max(gbp_results, key=lambda r: r["metrics"].sharpe_ratio)
        md.append(f"\n### GBPUSD: LIMITED RESEARCH on {best_g['label']}")
    else:
        md.append("\n### GBPUSD: DEPRIORITIZE")
        md.append("- All tested families fail on GBPUSD")
        md.append("- No further research budget until new concepts available")

    md.extend(["\n### USDJPY: CONTINUE promoted path",
               "- BOS continuation remains the primary edge",
               "- Proceed with prop-constrained paper validation",
               "\n## What to Abandon\n",
               "- Cloned-strategy multi-pair deployment",
               "- BOS continuation on EURUSD and GBPUSD",
               f"{'- GBPUSD under any current signal family' if not gbp_any else ''}",
               "- Large-scale parameter sweeps without pair-specific hypotheses"])

    (out / "next_research_recommendation.md").write_text("\n".join(md))
    logger.info("  Written campaign reports (7 files)")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("Alternative Alpha Discovery Research")
    logger.info("=" * 60)

    logger.info("Loading data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    for pair, series in full_data.items():
        logger.info("  %s: %d bars", pair.value, len(series))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # === EURUSD ===
    logger.info("=" * 60)
    logger.info("EURUSD Alpha Discovery (4 hypotheses)")
    logger.info("=" * 60)
    eur_results = []
    for name, spec in HYPOTHESES[TradingPair.EURUSD].items():
        logger.info("  [%s] %s", name, spec["label"])
        r = run_hypothesis(TradingPair.EURUSD, name, spec, full_data, htf_data)
        eur_results.append(r)
        logger.info("    → %d trades, Sharpe %.3f, PF %.3f, WF %.3f → %s",
                     r["metrics"].total_trades, r["metrics"].sharpe_ratio, r["metrics"].profit_factor,
                     r["wf"]["mean_sharpe"], r["verdict"])

    write_eurusd_reports(eur_results)

    # === GBPUSD ===
    logger.info("=" * 60)
    logger.info("GBPUSD Alpha Discovery (3 hypotheses)")
    logger.info("=" * 60)
    gbp_results = []
    for name, spec in HYPOTHESES[TradingPair.GBPUSD].items():
        logger.info("  [%s] %s", name, spec["label"])
        r = run_hypothesis(TradingPair.GBPUSD, name, spec, full_data, htf_data)
        gbp_results.append(r)
        logger.info("    → %d trades, Sharpe %.3f, PF %.3f, WF %.3f → %s",
                     r["metrics"].total_trades, r["metrics"].sharpe_ratio, r["metrics"].profit_factor,
                     r["wf"]["mean_sharpe"], r["verdict"])

    write_gbpusd_reports(gbp_results)

    # === Combined B4/B5 ===
    logger.info("=" * 60)
    logger.info("Writing campaign analytics and decision outputs")
    logger.info("=" * 60)
    write_campaign_reports(eur_results, gbp_results)

    logger.info("=" * 60)
    logger.info("Alpha discovery complete. Results in: %s", RESULTS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
