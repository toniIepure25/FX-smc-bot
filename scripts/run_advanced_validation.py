#!/usr/bin/env python3
"""Advanced prop-validation suite: rolling windows, cost sensitivity,
tail risk, regime stability, PnL concentration, graceful degradation,
and rule-breach sensitivity tests.

Usage:
  python scripts/run_advanced_validation.py --data-dir data/real --output-dir results/forward_validation
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_pair_data, load_htf_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.risk.sizing import DrawdownAwareSizing

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("advanced_validation")

PAIR = TradingPair.USDJPY
TF = Timeframe.H1


def build_prop_config() -> AppConfig:
    cfg = AppConfig()
    cfg.risk.base_risk_per_trade = 0.003
    cfg.risk.max_portfolio_risk = 0.009
    cfg.risk.max_daily_drawdown = 0.02
    cfg.risk.max_weekly_drawdown = 0.04
    cfg.risk.max_concurrent_positions = 1
    cfg.risk.max_per_pair_positions = 1
    cfg.risk.max_trades_per_day = 3
    cfg.risk.max_trades_per_session = 2
    cfg.risk.daily_loss_lockout = 0.02
    cfg.risk.consecutive_loss_dampen_after = 3
    cfg.risk.consecutive_loss_dampen_factor = 0.5
    cfg.risk.circuit_breaker_threshold = 0.10
    cfg.risk.circuit_breaker_cooldown_days = 5
    cfg.risk.min_reward_risk_ratio = 1.5
    cfg.alpha.enabled_families = ["bos_continuation"]
    cfg.data.primary_pairs = [TradingPair.USDJPY]
    return cfg


def run_paper(
    data: dict[TradingPair, BarSeries],
    htf: dict[TradingPair, BarSeries] | None,
    cfg: AppConfig,
    output_dir: Path,
    label: str,
) -> dict:
    """Run a single paper replay and return summary metrics."""
    policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    runner = PaperTradingRunner(cfg, output_dir=output_dir / label, sizing_policy=policy)
    state = runner.run(data, htf)

    closed = runner._broker.all_closed_positions
    total_pnl = sum(p.pnl for p in closed)
    wins = sum(1 for p in closed if p.pnl > 0)
    losses = sum(1 for p in closed if p.pnl < 0)
    gross_profit = sum(p.pnl for p in closed if p.pnl > 0)
    gross_loss = abs(sum(p.pnl for p in closed if p.pnl < 0))

    return {
        "label": label,
        "trades": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(closed), 3) if closed else 0.0,
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "final_equity": state.equity,
        "cb_fires": runner._dd_tracker._cb_fire_count,
    }


def slice_by_date(series: BarSeries, start: datetime, end: datetime) -> BarSeries:
    """Slice a BarSeries to [start, end)."""
    import numpy as np
    start_np = np.datetime64(start, "ns")
    end_np = np.datetime64(end, "ns")
    mask = (series.timestamps >= start_np) & (series.timestamps < end_np)
    indices = np.where(mask)[0]
    if len(indices) == 0:
        return series.slice(0, 0)
    return series.slice(int(indices[0]), int(indices[-1]) + 1)


# ======================================================================
# Test implementations
# ======================================================================

def test_rolling_windows(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Split into rolling 12-month windows with 3-month stride."""
    import numpy as np
    results = []
    ts = data.timestamps
    first = ts[0].astype("datetime64[M]").astype(datetime)
    last = ts[-1].astype("datetime64[M]").astype(datetime)

    start = first
    window_months = 12
    stride_months = 3
    i = 0
    while True:
        w_start = start + timedelta(days=stride_months * 30 * i)
        w_end = w_start + timedelta(days=window_months * 30)
        if w_start >= last:
            break
        sliced = slice_by_date(data, w_start, w_end)
        if len(sliced) < 100:
            i += 1
            continue
        htf_sliced = {PAIR: htf} if htf else None
        label = f"window_{i}__{w_start.strftime('%Y%m')}_to_{w_end.strftime('%Y%m')}"
        r = run_paper({PAIR: sliced}, htf_sliced, cfg, out, label)
        results.append(r)
        i += 1

    return {"test": "rolling_windows", "windows": results}


def test_monthly_consistency(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Full run, then extract per-month stats from the journal."""
    policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    runner = PaperTradingRunner(cfg, output_dir=out / "monthly", sizing_policy=policy)
    htf_dict = {PAIR: htf} if htf else None
    runner.run({PAIR: data}, htf_dict)

    closed = runner._broker.all_closed_positions
    monthly: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for p in closed:
        if p.closed_at:
            key = p.closed_at.strftime("%Y-%m")
            monthly[key]["trades"] += 1
            monthly[key]["pnl"] += p.pnl
            if p.pnl > 0:
                monthly[key]["wins"] += 1

    months = []
    for key in sorted(monthly.keys()):
        m = monthly[key]
        m["month"] = key
        m["win_rate"] = round(m["wins"] / m["trades"], 3) if m["trades"] > 0 else 0.0
        m["pnl"] = round(m["pnl"], 2)
        months.append(m)

    negative_months = [m for m in months if m["pnl"] < 0]
    return {
        "test": "monthly_consistency",
        "months": months,
        "total_months": len(months),
        "negative_months": len(negative_months),
        "worst_month": min(months, key=lambda x: x["pnl"]) if months else None,
    }


def test_cost_sensitivity(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Re-run with spread multipliers 1x, 1.5x, 2x, 3x."""
    results = []
    for mult in [1.0, 1.5, 2.0, 3.0]:
        c = build_prop_config()
        c.execution.default_spread_pips = cfg.execution.default_spread_pips * mult
        label = f"cost_spread_{mult:.1f}x"
        htf_dict = {PAIR: htf} if htf else None
        r = run_paper({PAIR: data}, htf_dict, c, out, label)
        r["spread_mult"] = mult
        results.append(r)

    base_pnl = results[0]["total_pnl"] if results else 1.0
    for r in results:
        r["pnl_degradation_pct"] = round(1.0 - r["total_pnl"] / base_pnl, 3) if base_pnl != 0 else 0.0

    return {"test": "cost_sensitivity", "results": results}


def test_pnl_concentration(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Analyze PnL concentration: top-N trade contribution and Gini coefficient."""
    policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    runner = PaperTradingRunner(cfg, output_dir=out / "concentration", sizing_policy=policy)
    htf_dict = {PAIR: htf} if htf else None
    runner.run({PAIR: data}, htf_dict)

    closed = runner._broker.all_closed_positions
    pnls = sorted([p.pnl for p in closed], reverse=True)
    total = sum(pnls) if pnls else 1.0

    top5_pct = round(sum(pnls[:5]) / total, 3) if len(pnls) >= 5 and total != 0 else 0.0
    top10_pct = round(sum(pnls[:10]) / total, 3) if len(pnls) >= 10 and total != 0 else 0.0
    top20_pct = round(sum(pnls[:20]) / total, 3) if len(pnls) >= 20 and total != 0 else 0.0

    # Gini coefficient on absolute PnL
    abs_pnls = sorted([abs(p) for p in pnls])
    n = len(abs_pnls)
    if n > 0 and sum(abs_pnls) > 0:
        gini = sum((2 * i - n - 1) * v for i, v in enumerate(abs_pnls, 1)) / (n * sum(abs_pnls))
    else:
        gini = 0.0

    return {
        "test": "pnl_concentration",
        "total_trades": len(pnls),
        "total_pnl": round(total, 2),
        "top5_pct": top5_pct,
        "top10_pct": top10_pct,
        "top20_pct": top20_pct,
        "gini_coefficient": round(gini, 3),
    }


def test_entry_clustering(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Analyze time distribution of entries: session, day-of-week, hour."""
    policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    runner = PaperTradingRunner(cfg, output_dir=out / "clustering", sizing_policy=policy)
    htf_dict = {PAIR: htf} if htf else None
    runner.run({PAIR: data}, htf_dict)

    closed = runner._broker.all_closed_positions
    hours: dict[int, int] = defaultdict(int)
    days: dict[int, int] = defaultdict(int)
    for p in closed:
        if p.opened_at:
            hours[p.opened_at.hour] += 1
            days[p.opened_at.weekday()] += 1

    total = len(closed) or 1
    hour_fracs = [hours.get(h, 0) / total for h in range(24)]
    hhi = sum(f ** 2 for f in hour_fracs)

    return {
        "test": "entry_clustering",
        "total_entries": len(closed),
        "by_hour": dict(sorted(hours.items())),
        "by_day_of_week": dict(sorted(days.items())),
        "herfindahl_index_hourly": round(hhi, 4),
        "cluster_assessment": "concentrated" if hhi > 0.15 else "distributed",
    }


def test_signal_drought(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Measure longest gaps between entries in historical data."""
    policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    runner = PaperTradingRunner(cfg, output_dir=out / "drought", sizing_policy=policy)
    htf_dict = {PAIR: htf} if htf else None
    runner.run({PAIR: data}, htf_dict)

    closed = runner._broker.all_closed_positions
    entry_times = sorted([p.opened_at for p in closed if p.opened_at])
    gaps = []
    for i in range(1, len(entry_times)):
        gap_hours = (entry_times[i] - entry_times[i - 1]).total_seconds() / 3600
        gaps.append(gap_hours)

    if not gaps:
        return {"test": "signal_drought", "status": "no_data"}

    return {
        "test": "signal_drought",
        "total_entries": len(entry_times),
        "max_gap_hours": round(max(gaps), 1),
        "avg_gap_hours": round(sum(gaps) / len(gaps), 1),
        "median_gap_hours": round(sorted(gaps)[len(gaps) // 2], 1),
        "p95_gap_hours": round(sorted(gaps)[int(len(gaps) * 0.95)], 1),
        "gaps_over_48h": sum(1 for g in gaps if g > 48),
        "gaps_over_72h": sum(1 for g in gaps if g > 72),
    }


def test_graceful_degradation(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Run with every Nth bar skipped to simulate feed delays."""
    import numpy as np
    results = []
    for skip in [0, 2, 5, 10]:
        if skip == 0:
            sliced = data
        else:
            indices = list(range(0, len(data), 1))
            keep = [i for i in indices if i % (skip + 1) != skip]
            sliced = BarSeries(
                pair=data.pair, timeframe=data.timeframe,
                timestamps=data.timestamps[keep],
                open=data.open[keep], high=data.high[keep],
                low=data.low[keep], close=data.close[keep],
                volume=data.volume[keep] if data.volume is not None else None,
                spread=data.spread[keep] if data.spread is not None else None,
            )
        label = f"degradation_skip_{skip}"
        htf_dict = {PAIR: htf} if htf else None
        r = run_paper({PAIR: sliced}, htf_dict, cfg, out, label)
        r["skip_rate"] = skip
        r["bars_used"] = len(sliced)
        results.append(r)

    return {"test": "graceful_degradation", "results": results}


def test_rule_breach_sensitivity(data: BarSeries, htf: BarSeries | None, cfg: AppConfig, out: Path) -> dict:
    """Tighten each constraint by 20% individually."""
    results = []
    htf_dict = {PAIR: htf} if htf else None

    # Baseline
    r = run_paper({PAIR: data}, htf_dict, cfg, out, "rule_baseline")
    results.append(r)

    # Max trades/day: 3 -> 2
    c = build_prop_config()
    c.risk.max_trades_per_day = 2
    r = run_paper({PAIR: data}, htf_dict, c, out, "rule_max_trades_2")
    r["constraint"] = "max_trades_per_day=2"
    results.append(r)

    # Daily lockout: 2% -> 1.5%
    c = build_prop_config()
    c.risk.daily_loss_lockout = 0.015
    r = run_paper({PAIR: data}, htf_dict, c, out, "rule_lockout_1.5pct")
    r["constraint"] = "daily_lockout=1.5%"
    results.append(r)

    # CB threshold: 10% -> 8%
    c = build_prop_config()
    c.risk.circuit_breaker_threshold = 0.08
    r = run_paper({PAIR: data}, htf_dict, c, out, "rule_cb_8pct")
    r["constraint"] = "cb_threshold=8%"
    results.append(r)

    # Risk per trade: 0.3% -> 0.24%
    c = build_prop_config()
    c.risk.base_risk_per_trade = 0.0024
    r = run_paper({PAIR: data}, htf_dict, c, out, "rule_risk_0.24pct")
    r["constraint"] = "risk_per_trade=0.24%"
    results.append(r)

    return {"test": "rule_breach_sensitivity", "results": results}


# ======================================================================
# Main
# ======================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced prop-validation suite")
    parser.add_argument("--data-dir", type=str, default="data/real")
    parser.add_argument("--output-dir", type=str, default="results/forward_validation")
    args = parser.parse_args()

    cfg = build_prop_config()
    cfg.data.root_dir = Path(args.data_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    logger.info("Loading USDJPY H1 data from %s", args.data_dir)
    all_data = load_pair_data(args.data_dir, pairs=[PAIR], timeframe=TF)
    if PAIR not in all_data:
        logger.error("No data found for %s", PAIR.value)
        sys.exit(1)
    data = all_data[PAIR]
    logger.info("Loaded %d bars", len(data))

    htf = None
    try:
        htf_dict = load_htf_data(all_data, htf_timeframe=Timeframe.H4, data_dir=args.data_dir)
        htf = htf_dict.get(PAIR)
    except Exception:
        logger.info("No HTF data — running without")

    all_results: dict[str, dict] = {}

    tests = [
        ("rolling_windows", test_rolling_windows),
        ("monthly_consistency", test_monthly_consistency),
        ("cost_sensitivity", test_cost_sensitivity),
        ("pnl_concentration", test_pnl_concentration),
        ("entry_clustering", test_entry_clustering),
        ("signal_drought", test_signal_drought),
        ("graceful_degradation", test_graceful_degradation),
        ("rule_breach_sensitivity", test_rule_breach_sensitivity),
    ]

    for name, fn in tests:
        logger.info("=" * 60)
        logger.info("Running test: %s", name)
        logger.info("=" * 60)
        try:
            result = fn(data, htf, cfg, out)
            all_results[name] = result
            with open(out / f"test_{name}.json", "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info("Test %s complete", name)
        except Exception:
            logger.exception("Test %s FAILED", name)
            all_results[name] = {"test": name, "status": "error"}

    # Write combined manifest
    with open(out / "advanced_validation_manifest.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    logger.info("All tests complete. Results in %s", out)


if __name__ == "__main__":
    main()
