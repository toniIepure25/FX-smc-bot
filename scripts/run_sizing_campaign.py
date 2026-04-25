#!/usr/bin/env python3
"""Multi-Model Sizing Campaign — Capital Deployment Hardening Wave.

Runs bos_only_usdjpy over the full available data under 7 different sizing
policies, collects per-model metrics, and generates comparative reports.

Usage:
    python3 scripts/run_sizing_campaign.py
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.risk.sizing import (
    ALL_SIZING_POLICIES,
    SizingPolicy,
    CappedCompounding,
    DrawdownAwareSizing,
    FixedInitial,
    FullCompounding,
    HybridPropSizing,
    SteppedCompounding,
    VolatilityScaledSizing,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("sizing_campaign")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
RESULTS_DIR = PROJECT_ROOT / "results" / "capital_deployment"

CANDIDATE = "bos_only_usdjpy"
FAMILIES = ["bos_continuation"]
INITIAL_EQUITY = 100_000.0

PROP_RISK = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "max_daily_drawdown": 0.02,
    "max_weekly_drawdown": 0.04,
    "max_concurrent_positions": 1,
    "max_per_pair_positions": 1,
    "max_trades_per_day": 3,
    "max_trades_per_session": 2,
    "daily_loss_lockout": 0.02,
    "consecutive_loss_dampen_after": 3,
    "consecutive_loss_dampen_factor": 0.5,
    "circuit_breaker_threshold": 0.12,
}

POLICIES: dict[str, SizingPolicy] = {
    "full_compounding": FullCompounding(),
    "fixed_initial": FixedInitial(),
    "capped_3x": CappedCompounding(cap_multiple=3.0),
    "stepped": SteppedCompounding(),
    "drawdown_aware": DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25),
    "volatility_scaled": VolatilityScaledSizing(),
    "hybrid_prop": HybridPropSizing(cap_multiple=2.0, dd_reduction_rate=0.5),
}


def _build_config() -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = list(FAMILIES)
    cfg.ml.enable_regime_tagging = True
    for k, v in PROP_RISK.items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _sd(a: float, b: float, d: float = 0.0) -> float:
    return a / b if b else d


def _tbl(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Per-run metrics extraction
# ─────────────────────────────────────────────────────────────────────

def extract_metrics(
    events: list[dict],
    final_equity: float,
    final_state_str: str,
    bars_processed: int,
) -> dict[str, Any]:
    """Extract comprehensive metrics from a journal event stream."""
    fills = [e for e in events if e.get("event_type") == "fill"]
    entries = [f for f in fills if f.get("data", {}).get("reason") == "market_open"]
    tp_fills = [f for f in fills if f.get("data", {}).get("reason") == "take_profit_hit"]
    sl_fills = [f for f in fills if f.get("data", {}).get("reason") == "stop_loss_hit"]
    transitions = [e for e in events if e.get("event_type") == "state_transition"]
    daily_sums = [e for e in events if e.get("event_type") == "daily_summary"]

    total_trades = len(tp_fills) + len(sl_fills)
    wins = len(tp_fills)
    wr = _sd(wins, total_trades)
    total_pnl = final_equity - INITIAL_EQUITY
    ret_pct = _sd(total_pnl, INITIAL_EQUITY)

    lockouts = [t for t in transitions if t.get("data", {}).get("new") == "locked"]
    throttles = [t for t in transitions if t.get("data", {}).get("new") == "throttled"]
    stopped = [t for t in transitions if t.get("data", {}).get("new") == "stopped"]
    circuit_breaker_fired = len(stopped) > 0

    # Equity path from daily summaries
    eq_series = sorted(
        [(d.get("timestamp", ""), d.get("data", {}).get("equity", INITIAL_EQUITY))
         for d in daily_sums if "equity" in d.get("data", {})],
        key=lambda x: x[0],
    )
    eq_vals = [v for _, v in eq_series]

    hwm = INITIAL_EQUITY
    worst_trail_dd = 0.0
    worst_abs_dd = 0.0
    for eq in eq_vals:
        hwm = max(hwm, eq)
        trail = _sd(hwm - eq, hwm)
        worst_trail_dd = max(worst_trail_dd, trail)
        if eq < INITIAL_EQUITY:
            worst_abs_dd = max(worst_abs_dd, _sd(INITIAL_EQUITY - eq, INITIAL_EQUITY))

    peak_eq = max(eq_vals) if eq_vals else INITIAL_EQUITY

    # Monthly buckets
    monthly_pnls: dict[str, float] = {}
    monthly_trades: dict[str, int] = defaultdict(int)
    monthly_eq: dict[str, list[float]] = defaultdict(list)
    for ts_str, eq in eq_series:
        month = ts_str[:7]
        monthly_eq[month].append(eq)
    for month, eqs in sorted(monthly_eq.items()):
        monthly_pnls[month] = eqs[-1] - eqs[0] if len(eqs) >= 2 else 0

    for f in tp_fills + sl_fills:
        ts = f.get("timestamp", "")[:7]
        if ts:
            monthly_trades[ts] += 1

    positive_months = sum(1 for v in monthly_pnls.values() if v > 0)
    total_months = len(monthly_pnls) if monthly_pnls else 1

    # Loss streaks
    outcomes = []
    for f in sorted(fills, key=lambda x: x.get("timestamp", "")):
        r = f.get("data", {}).get("reason", "")
        if r == "take_profit_hit":
            outcomes.append(1)
        elif r == "stop_loss_hit":
            outcomes.append(0)
    max_loss_streak = 0
    cur = 0
    for o in outcomes:
        if o == 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0

    # Max daily entries
    daily_entries: dict[str, int] = defaultdict(int)
    for f in entries:
        daily_entries[f.get("timestamp", "")[:10]] += 1
    max_daily = max(daily_entries.values(), default=0)
    days_over_limit = sum(1 for v in daily_entries.values() if v > PROP_RISK["max_trades_per_day"])

    # Active vs stopped months
    active_months_set = set()
    for f in entries:
        ts = f.get("timestamp", "")[:7]
        if ts:
            active_months_set.add(ts)
    active_months = len(active_months_set)

    # PnL concentration
    sorted_monthly = sorted(monthly_pnls.values(), reverse=True)
    top3_pnl = sum(sorted_monthly[:3])
    pnl_concentration = _sd(top3_pnl, total_pnl) if total_pnl > 0 else 0

    # Monthly Sharpe approximation
    mp_list = list(monthly_pnls.values())
    if len(mp_list) >= 2:
        mean_m = sum(mp_list) / len(mp_list)
        std_m = (sum((p - mean_m) ** 2 for p in mp_list) / (len(mp_list) - 1)) ** 0.5
        monthly_sharpe = _sd(mean_m, std_m) * (12 ** 0.5)
    else:
        monthly_sharpe = 0.0

    # Worst monthly loss
    worst_month_pnl = min(monthly_pnls.values()) if monthly_pnls else 0
    worst_month_label = ""
    for m, p in monthly_pnls.items():
        if p == worst_month_pnl:
            worst_month_label = m
            break

    # Best monthly gain
    best_month_pnl = max(monthly_pnls.values()) if monthly_pnls else 0
    best_month_label = ""
    for m, p in monthly_pnls.items():
        if p == best_month_pnl:
            best_month_label = m
            break

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": total_trades - wins,
        "win_rate": round(wr, 4),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(ret_pct, 4),
        "final_equity": round(final_equity, 2),
        "peak_equity": round(peak_eq, 2),
        "trail_dd_from_hwm": round(worst_trail_dd, 4),
        "abs_dd": round(worst_abs_dd, 4),
        "circuit_breaker_fired": circuit_breaker_fired,
        "final_state": final_state_str,
        "survived": not circuit_breaker_fired and final_state_str != "stopped",
        "lockout_events": len(lockouts),
        "throttle_events": len(throttles),
        "max_loss_streak": max_loss_streak,
        "max_daily_entries": max_daily,
        "days_over_trade_limit": days_over_limit,
        "active_months": active_months,
        "total_months": total_months,
        "positive_months": positive_months,
        "positive_month_ratio": round(_sd(positive_months, total_months), 2),
        "pnl_concentration_top3": round(pnl_concentration, 2),
        "monthly_sharpe_ann": round(monthly_sharpe, 2),
        "worst_month": {"label": worst_month_label, "pnl": round(worst_month_pnl, 2)},
        "best_month": {"label": best_month_label, "pnl": round(best_month_pnl, 2)},
        "monthly_pnls": {k: round(v, 2) for k, v in monthly_pnls.items()},
        "monthly_trades": dict(monthly_trades),
        "bars_processed": bars_processed,
    }


# ─────────────────────────────────────────────────────────────────────
# Campaign runner
# ─────────────────────────────────────────────────────────────────────

def run_campaign() -> dict[str, dict[str, Any]]:
    logger.info("=" * 70)
    logger.info("Capital Deployment Sizing Campaign")
    logger.info("=" * 70)

    logger.info("Loading data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    pair_enum = TradingPair.USDJPY
    series = full_data[pair_enum]

    window = {pair_enum: series}
    htf_window = None
    if htf_data and pair_enum in htf_data:
        htf_window = {pair_enum: htf_data[pair_enum]}

    first_ts = series.timestamps[0].astype("datetime64[us]").item()
    last_ts = series.timestamps[-1].astype("datetime64[us]").item()
    logger.info("  Data: %d bars, %s to %s", len(series), first_ts, last_ts)

    all_results: dict[str, dict[str, Any]] = {}

    for policy_name, policy in POLICIES.items():
        logger.info("-" * 60)
        logger.info("Running model: %s", policy_name)
        logger.info("-" * 60)

        cfg = _build_config()
        run_dir = RESULTS_DIR / "campaign_runs" / policy_name
        run_dir.mkdir(parents=True, exist_ok=True)

        runner = PaperTradingRunner(cfg, output_dir=run_dir, sizing_policy=policy)
        final_state = runner.run(window, htf_window)

        journals = list(run_dir.glob("*/journal.jsonl"))
        events: list[dict] = []
        if journals:
            with open(sorted(journals)[-1]) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))

        metrics = extract_metrics(
            events,
            float(final_state.equity),
            final_state.operational_state,
            int(final_state.bars_processed),
        )
        metrics["policy"] = policy_name
        metrics["policy_params"] = _policy_params(policy)
        all_results[policy_name] = metrics

        logger.info(
            "  %s: equity=%.0f trades=%d trail_dd=%.2f%% survived=%s",
            policy_name, metrics["final_equity"], metrics["total_trades"],
            metrics["trail_dd_from_hwm"] * 100, metrics["survived"],
        )

    return all_results


def _policy_params(policy: SizingPolicy) -> dict[str, Any]:
    if isinstance(policy, CappedCompounding):
        return {"cap_multiple": policy.cap_multiple}
    if isinstance(policy, DrawdownAwareSizing):
        return {"max_dd": policy.max_dd, "min_scale": policy.min_scale}
    if isinstance(policy, HybridPropSizing):
        return {"cap_multiple": policy.cap_multiple, "dd_reduction_rate": policy.dd_reduction_rate}
    return {}


# ─────────────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────────────

def write_reports(results: dict[str, dict[str, Any]]) -> None:
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # ─── sizing_model_results.json ───
    (out / "sizing_model_results.json").write_text(json.dumps(results, indent=2))
    logger.info("Written sizing_model_results.json")

    # Sort by a composite score for ranking
    def score(m: dict) -> float:
        s = 0.0
        if m["survived"]:
            s += 40
        s += min(20, m["return_pct"] * 10)
        s += min(15, max(0, (0.12 - m["trail_dd_from_hwm"]) * 100))
        s += min(10, m["positive_month_ratio"] * 10)
        s += min(10, max(0, m["monthly_sharpe_ann"] * 2))
        s -= m["days_over_trade_limit"] * 0.5
        return s

    ranked = sorted(results.items(), key=lambda x: score(x[1]), reverse=True)

    # ─── sizing_model_campaign_report.md ───
    headers = [
        "Model", "Trades", "WR", "Return", "Final Eq", "Trail DD",
        "CB Fired", "Survived", "Pos Mo%", "Max Streak", "Max Daily",
    ]
    rows = []
    for name, m in ranked:
        rows.append([
            name,
            m["total_trades"],
            f"{m['win_rate']:.0%}",
            f"{m['return_pct']:.1%}",
            f"{m['final_equity']:,.0f}",
            f"{m['trail_dd_from_hwm']:.2%}",
            "YES" if m["circuit_breaker_fired"] else "no",
            "YES" if m["survived"] else "**NO**",
            f"{m['positive_month_ratio']:.0%}",
            m["max_loss_streak"],
            m["max_daily_entries"],
        ])

    md = [
        "# Sizing Model Campaign Report",
        "",
        f"**Candidate**: {CANDIDATE}",
        f"**Models tested**: {len(results)}",
        f"**Data window**: full USDJPY H1 dataset",
        "",
        "## Side-by-Side Comparison",
        "",
        _tbl(headers, rows),
        "",
        "## Rankings (by composite score)",
        "",
    ]
    for i, (name, m) in enumerate(ranked, 1):
        s = score(m)
        md.append(f"{i}. **{name}** — score {s:.1f} | return {m['return_pct']:.1%} | trail DD {m['trail_dd_from_hwm']:.2%} | survived={m['survived']}")
    (out / "sizing_model_campaign_report.md").write_text("\n".join(md))
    logger.info("Written sizing_model_campaign_report.md")

    # ─── monthly_comparison_by_model.md ───
    all_months = sorted({m for res in results.values() for m in res.get("monthly_pnls", {})})
    md = ["# Monthly Comparison by Model", ""]
    if all_months:
        h = ["Month"] + [name for name, _ in ranked]
        r = []
        for month in all_months:
            row = [month]
            for name, m in ranked:
                pnl = m.get("monthly_pnls", {}).get(month, 0)
                row.append(f"{pnl:,.0f}")
            r.append(row)
        md.append(_tbl(h, r))
    (out / "monthly_comparison_by_model.md").write_text("\n".join(md))
    logger.info("Written monthly_comparison_by_model.md")

    # ─── quarterly_comparison_by_model.md ───
    def _to_quarter(month_str: str) -> str:
        m = int(month_str[5:7])
        q = (m - 1) // 3 + 1
        return f"{month_str[:4]}-Q{q}"

    all_quarters = sorted({_to_quarter(m) for m in all_months})
    md = ["# Quarterly Comparison by Model", ""]
    if all_quarters:
        h = ["Quarter"] + [name for name, _ in ranked]
        r = []
        for qtr in all_quarters:
            row = [qtr]
            for name, m in ranked:
                q_pnl = sum(
                    v for k, v in m.get("monthly_pnls", {}).items()
                    if _to_quarter(k) == qtr
                )
                row.append(f"{q_pnl:,.0f}")
            r.append(row)
        md.append(_tbl(h, r))
    (out / "quarterly_comparison_by_model.md").write_text("\n".join(md))
    logger.info("Written quarterly_comparison_by_model.md")

    # ─── long_horizon_survival_report.md ───
    survivors = [(n, m) for n, m in ranked if m["survived"]]
    failed = [(n, m) for n, m in ranked if not m["survived"]]

    md = [
        "# Long-Horizon Survival Report",
        "",
        f"**Models tested**: {len(results)}",
        f"**Survived**: {len(survivors)}",
        f"**Failed (circuit breaker)**: {len(failed)}",
        "",
        "## Survivors",
        "",
    ]
    if survivors:
        md.append(_tbl(
            ["Model", "Return", "Trail DD", "Final Equity", "Active Months", "Trades"],
            [[n, f"{m['return_pct']:.1%}", f"{m['trail_dd_from_hwm']:.2%}",
              f"{m['final_equity']:,.0f}", m["active_months"], m["total_trades"]]
             for n, m in survivors],
        ))
    else:
        md.append("*No models survived the full horizon.*")

    md.extend(["", "## Failed (Circuit Breaker Triggered)", ""])
    if failed:
        md.append(_tbl(
            ["Model", "Peak Equity", "Trail DD", "Final State", "Active Months"],
            [[n, f"{m['peak_equity']:,.0f}", f"{m['trail_dd_from_hwm']:.2%}",
              m["final_state"], m["active_months"]]
             for n, m in failed],
        ))
    else:
        md.append("*All models survived.*")

    md.extend([
        "",
        "## Key Finding",
        "",
    ])
    if survivors:
        best = survivors[0]
        md.append(
            f"The strongest survivor is **{best[0]}** with {best[1]['return_pct']:.1%} return "
            f"and {best[1]['trail_dd_from_hwm']:.2%} trailing DD."
        )
    else:
        md.append("No sizing model survived the full horizon. The strategy requires fundamental rework.")

    (out / "long_horizon_survival_report.md").write_text("\n".join(md))
    logger.info("Written long_horizon_survival_report.md")


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    results = run_campaign()
    write_reports(results)
    logger.info("=" * 70)
    logger.info("Campaign complete. All artifacts in: %s", RESULTS_DIR)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
