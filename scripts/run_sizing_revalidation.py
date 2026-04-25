#!/usr/bin/env python3
"""Focused re-validation of top sizing models with adjusted CB threshold.

After the main campaign showed all models fail at 12% CB, this reruns the
top 3 candidates with CB raised to 15% — the minimum viable prop-style
threshold for this strategy's structural characteristics.

Usage:
    python3 scripts/run_sizing_revalidation.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.risk.sizing import (
    DrawdownAwareSizing,
    FixedInitial,
    HybridPropSizing,
    VolatilityScaledSizing,
    SizingPolicy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("sizing_reval")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
RESULTS_DIR = PROJECT_ROOT / "results" / "capital_deployment"
INITIAL_EQUITY = 100_000.0

PROP_RISK_15PCT = {
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
    "circuit_breaker_threshold": 0.15,
}

REVALIDATION_POLICIES: dict[str, SizingPolicy] = {
    "drawdown_aware_15cb": DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25),
    "fixed_initial_15cb": FixedInitial(),
    "volatility_scaled_15cb": VolatilityScaledSizing(),
    "hybrid_prop_15cb": HybridPropSizing(cap_multiple=2.0, dd_reduction_rate=0.5),
}


def _build_config() -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = ["bos_continuation"]
    cfg.ml.enable_regime_tagging = True
    for k, v in PROP_RISK_15PCT.items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _sd(a, b, d=0.0):
    return a / b if b else d


def extract_metrics(events, final_equity, final_state_str, bars_processed):
    from collections import defaultdict
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

    stopped = [t for t in transitions if t.get("data", {}).get("new") == "stopped"]
    circuit_breaker_fired = len(stopped) > 0

    eq_series = sorted(
        [(d.get("timestamp", ""), d.get("data", {}).get("equity", INITIAL_EQUITY))
         for d in daily_sums if "equity" in d.get("data", {})],
        key=lambda x: x[0],
    )
    eq_vals = [v for _, v in eq_series]

    hwm = INITIAL_EQUITY
    worst_trail_dd = 0.0
    for eq in eq_vals:
        hwm = max(hwm, eq)
        worst_trail_dd = max(worst_trail_dd, _sd(hwm - eq, hwm))

    monthly_eq: dict[str, list[float]] = defaultdict(list)
    for ts_str, eq in eq_series:
        monthly_eq[ts_str[:7]].append(eq)
    monthly_pnls = {}
    for month, eqs in sorted(monthly_eq.items()):
        monthly_pnls[month] = eqs[-1] - eqs[0] if len(eqs) >= 2 else 0
    positive_months = sum(1 for v in monthly_pnls.values() if v > 0)
    total_months = len(monthly_pnls)

    active_months = len({f.get("timestamp", "")[:7] for f in entries if f.get("timestamp", "")[:7]})

    outcomes = []
    for f in sorted(fills, key=lambda x: x.get("timestamp", "")):
        r = f.get("data", {}).get("reason", "")
        if r == "take_profit_hit":
            outcomes.append(1)
        elif r == "stop_loss_hit":
            outcomes.append(0)
    max_streak = 0
    cur = 0
    for o in outcomes:
        if o == 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    daily_entries: dict[str, int] = defaultdict(int)
    for f in entries:
        daily_entries[f.get("timestamp", "")[:10]] += 1
    max_daily = max(daily_entries.values(), default=0)

    return {
        "total_trades": total_trades,
        "wins": wins,
        "win_rate": round(wr, 4),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(_sd(total_pnl, INITIAL_EQUITY), 4),
        "final_equity": round(final_equity, 2),
        "peak_equity": round(max(eq_vals) if eq_vals else INITIAL_EQUITY, 2),
        "trail_dd_from_hwm": round(worst_trail_dd, 4),
        "circuit_breaker_fired": circuit_breaker_fired,
        "survived": not circuit_breaker_fired and final_state_str != "stopped",
        "final_state": final_state_str,
        "active_months": active_months,
        "total_months": total_months,
        "positive_months": positive_months,
        "positive_month_ratio": round(_sd(positive_months, total_months), 2),
        "max_loss_streak": max_streak,
        "max_daily_entries": max_daily,
        "monthly_pnls": {k: round(v, 2) for k, v in monthly_pnls.items()},
        "bars_processed": bars_processed,
    }


def main():
    logger.info("=" * 70)
    logger.info("Sizing Model Revalidation — 15%% CB Threshold")
    logger.info("=" * 70)

    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    pair_enum = TradingPair.USDJPY
    series = full_data[pair_enum]
    window = {pair_enum: series}
    htf_window = {pair_enum: htf_data[pair_enum]} if htf_data and pair_enum in htf_data else None

    logger.info("  Data: %d bars", len(series))
    results = {}

    for name, policy in REVALIDATION_POLICIES.items():
        logger.info("--- Running %s ---", name)
        cfg = _build_config()
        run_dir = RESULTS_DIR / "revalidation_runs" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        runner = PaperTradingRunner(cfg, output_dir=run_dir, sizing_policy=policy)
        final_state = runner.run(window, htf_window)

        journals = list(run_dir.glob("*/journal.jsonl"))
        events = []
        if journals:
            with open(sorted(journals)[-1]) as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))

        m = extract_metrics(events, float(final_state.equity), final_state.operational_state, int(final_state.bars_processed))
        m["policy"] = name
        m["cb_threshold"] = 0.15
        results[name] = m
        logger.info("  %s: eq=%.0f trades=%d dd=%.2f%% survived=%s",
                     name, m["final_equity"], m["total_trades"],
                     m["trail_dd_from_hwm"]*100, m["survived"])

    (RESULTS_DIR / "revalidation_results_15cb.json").write_text(json.dumps(results, indent=2))
    logger.info("=" * 70)
    logger.info("Revalidation complete")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
