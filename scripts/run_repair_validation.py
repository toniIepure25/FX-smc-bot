#!/usr/bin/env python3
"""Repair validation: re-run 14-day near-live simulation with fixed
ForwardPaperRunner, run PaperTradingRunner on the same data, and
produce a detailed parity comparison.

Themes B, C, D of the forward-runner repair wave.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_pair_data, load_htf_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.providers.live_feed import ReplayFeedProvider
from fx_smc_bot.live.alerts import AlertRouter, FileAlertSink, LogAlertSink
from fx_smc_bot.live.drift_detector import BaselineProfile
from fx_smc_bot.live.forward_runner import ForwardPaperRunner
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.risk.sizing import DrawdownAwareSizing

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("repair_validation")

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


def slice_by_date(series: BarSeries, start: datetime, end: datetime) -> BarSeries:
    start_np = np.datetime64(start, "ns")
    end_np = np.datetime64(end, "ns")
    mask = (series.timestamps >= start_np) & (series.timestamps < end_np)
    indices = np.where(mask)[0]
    if len(indices) == 0:
        raise ValueError(f"No bars in [{start}, {end})")
    return series.slice(int(indices[0]), int(indices[-1]) + 1)


def extract_trade_stats(closed_positions):
    if not closed_positions:
        return {"trades": 0, "pnl": 0, "win_rate": 0, "profit_factor": 0}
    total_pnl = sum(p.pnl for p in closed_positions)
    wins = sum(1 for p in closed_positions if p.pnl > 0)
    gross_profit = sum(p.pnl for p in closed_positions if p.pnl > 0)
    gross_loss = abs(sum(p.pnl for p in closed_positions if p.pnl < 0))
    return {
        "trades": len(closed_positions),
        "wins": wins,
        "losses": len(closed_positions) - wins,
        "pnl": round(total_pnl, 2),
        "win_rate": round(wins / len(closed_positions), 3),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
    }


def main():
    out = Path("results/repair_validation")
    out.mkdir(parents=True, exist_ok=True)
    cfg = build_prop_config()

    logger.info("Loading data...")
    all_data = load_pair_data("data/real", pairs=[PAIR], timeframe=TF)
    full_series = all_data[PAIR]
    htf_dict = load_htf_data(all_data, htf_timeframe=Timeframe.H4, data_dir="data/real")
    htf_series = htf_dict.get(PAIR)
    logger.info("H1: %d bars, H4: %d bars", len(full_series), len(htf_series) if htf_series else 0)

    last_ts = full_series.timestamps[-1].astype("datetime64[us]").astype(datetime)
    window_start = last_ts - timedelta(days=14)
    warmup_start = window_start - timedelta(days=30)
    warmup_data = slice_by_date(full_series, warmup_start, last_ts + timedelta(hours=1))
    logger.info("Window: %s to %s (%d bars, %d warmup)",
                window_start, last_ts, len(warmup_data),
                len(warmup_data) - len(slice_by_date(full_series, window_start, last_ts + timedelta(hours=1))))

    # ================================================================
    # RUN 1: Fixed ForwardPaperRunner
    # ================================================================
    logger.info("=" * 60)
    logger.info("RUN 1: ForwardPaperRunner (FIXED)")
    logger.info("=" * 60)

    feed = ReplayFeedProvider(warmup_data)
    htf_feed = ReplayFeedProvider(htf_series) if htf_series else None

    alert_router = AlertRouter(sinks=[
        LogAlertSink(),
        FileAlertSink(out / "forward_alerts.jsonl"),
    ])
    sizing = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    baseline = BaselineProfile(win_rate=0.57, avg_rr=1.5, profit_factor=1.8)

    fwd_runner = ForwardPaperRunner(
        config=cfg, feed=feed, output_dir=out / "forward_run",
        alert_sink=alert_router, sizing_policy=sizing,
        baseline_profile=baseline, htf_feed=htf_feed,
    )

    logger.info("Starting ForwardPaperRunner: %s", fwd_runner.run_id)
    fwd_runner.start()

    fwd_closed = fwd_runner._broker.all_closed_positions
    fwd_stats = extract_trade_stats(fwd_closed)
    fwd_stats["bars_processed"] = fwd_runner._bars_processed
    fwd_stats["final_equity"] = fwd_runner._broker.get_account().equity
    fwd_stats["cb_fires"] = fwd_runner._dd_tracker._cb_fire_count
    fwd_stats["operational_state"] = fwd_runner._dd_tracker.operational_state.value
    fwd_stats["run_id"] = fwd_runner.run_id

    logger.info("ForwardPaperRunner: %d trades, PnL=%.2f, WR=%.3f, PF=%.2f",
                fwd_stats["trades"], fwd_stats["pnl"], fwd_stats["win_rate"], fwd_stats["profit_factor"])

    # ================================================================
    # RUN 2: PaperTradingRunner (baseline comparison)
    # ================================================================
    logger.info("=" * 60)
    logger.info("RUN 2: PaperTradingRunner (baseline)")
    logger.info("=" * 60)

    sizing2 = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    paper_runner = PaperTradingRunner(cfg, output_dir=out / "paper_run", sizing_policy=sizing2)
    paper_runner.run({PAIR: warmup_data}, {PAIR: htf_series} if htf_series else None)

    paper_closed = paper_runner._broker.all_closed_positions
    paper_stats = extract_trade_stats(paper_closed)
    paper_stats["bars_processed"] = paper_runner._bars_processed
    paper_stats["final_equity"] = paper_runner._broker.get_account().equity
    paper_stats["cb_fires"] = paper_runner._dd_tracker._cb_fire_count

    logger.info("PaperTradingRunner: %d trades, PnL=%.2f, WR=%.3f, PF=%.2f",
                paper_stats["trades"], paper_stats["pnl"], paper_stats["win_rate"], paper_stats["profit_factor"])

    # ================================================================
    # PARITY COMPARISON
    # ================================================================
    logger.info("=" * 60)
    logger.info("PARITY COMPARISON")
    logger.info("=" * 60)

    comparison = {
        "forward_runner": fwd_stats,
        "paper_runner": paper_stats,
        "parity": {
            "trade_count_match": fwd_stats["trades"] == paper_stats["trades"],
            "trade_count_diff": fwd_stats["trades"] - paper_stats["trades"],
            "trade_count_diff_pct": round(abs(fwd_stats["trades"] - paper_stats["trades"]) / max(paper_stats["trades"], 1) * 100, 1),
            "pnl_diff": round(fwd_stats["pnl"] - paper_stats["pnl"], 2),
            "pnl_diff_pct": round(abs(fwd_stats["pnl"] - paper_stats["pnl"]) / max(abs(paper_stats["pnl"]), 1) * 100, 1),
            "win_rate_diff": round(abs(fwd_stats["win_rate"] - paper_stats["win_rate"]), 3),
            "equity_diff": round(fwd_stats["final_equity"] - paper_stats["final_equity"], 2),
        },
    }

    # Per-trade comparison (match by timestamp where possible)
    fwd_by_time = {}
    for p in fwd_closed:
        if p.opened_at:
            fwd_by_time[p.opened_at] = {"dir": p.direction.value, "pnl": round(p.pnl, 2), "entry": p.entry_price}
    paper_by_time = {}
    for p in paper_closed:
        if p.opened_at:
            paper_by_time[p.opened_at] = {"dir": p.direction.value, "pnl": round(p.pnl, 2), "entry": p.entry_price}

    matched = 0
    fwd_only = 0
    paper_only = 0
    for t in set(list(fwd_by_time.keys()) + list(paper_by_time.keys())):
        if t in fwd_by_time and t in paper_by_time:
            matched += 1
        elif t in fwd_by_time:
            fwd_only += 1
        else:
            paper_only += 1

    comparison["trade_matching"] = {
        "matched_by_timestamp": matched,
        "forward_only": fwd_only,
        "paper_only": paper_only,
        "match_rate": round(matched / max(matched + fwd_only + paper_only, 1), 3),
    }

    # Daily trade count comparison
    fwd_daily = defaultdict(int)
    paper_daily = defaultdict(int)
    for p in fwd_closed:
        if p.opened_at:
            fwd_daily[p.opened_at.strftime("%Y-%m-%d")] += 1
    for p in paper_closed:
        if p.opened_at:
            paper_daily[p.opened_at.strftime("%Y-%m-%d")] += 1
    all_days = sorted(set(list(fwd_daily.keys()) + list(paper_daily.keys())))
    daily_comparison = []
    for d in all_days:
        daily_comparison.append({
            "date": d,
            "forward": fwd_daily.get(d, 0),
            "paper": paper_daily.get(d, 0),
            "diff": fwd_daily.get(d, 0) - paper_daily.get(d, 0),
        })
    comparison["daily_trade_comparison"] = daily_comparison

    # Assessment
    trades_close = comparison["parity"]["trade_count_diff_pct"] < 20
    pnl_close = comparison["parity"]["pnl_diff_pct"] < 30
    wr_close = comparison["parity"]["win_rate_diff"] < 0.10
    signal_alive = fwd_stats["trades"] > 0

    comparison["assessment"] = {
        "signal_generation_restored": signal_alive,
        "trade_count_within_20pct": trades_close,
        "pnl_within_30pct": pnl_close,
        "win_rate_within_10pp": wr_close,
        "overall_parity": "acceptable" if (signal_alive and trades_close and wr_close) else "needs_investigation",
        "forward_runner_operational": signal_alive,
    }

    with open(out / "parity_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2, default=str)

    # Session manifest
    manifest = {
        "type": "repair_validation",
        "date": datetime.utcnow().isoformat(),
        "window": {"start": window_start.isoformat(), "end": last_ts.isoformat()},
        "warmup_bars": len(warmup_data) - len(slice_by_date(full_series, window_start, last_ts + timedelta(hours=1))),
        "window_bars": len(slice_by_date(full_series, window_start, last_ts + timedelta(hours=1))),
        "forward_run_id": fwd_runner.run_id,
        "fix_applied": "HTF temporal sync — _sync_htf_to drains HTF feed to current LTF timestamp",
        "root_cause": "ForwardPaperRunner polled one HTF bar per LTF bar from oldest H4 data, creating temporal misalignment. HTF regime was BULLISH (from 2024 data) while LTF was BEARISH (2026 data), so BOSContinuationDetector found 0 breaks in HTF direction.",
    }
    with open(out / "repaired_nearlive_session_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Print summary
    logger.info("=" * 60)
    logger.info("REPAIR VALIDATION COMPLETE")
    logger.info("=" * 60)
    logger.info("Forward trades: %d | Paper trades: %d | Diff: %d (%.1f%%)",
                fwd_stats["trades"], paper_stats["trades"],
                comparison["parity"]["trade_count_diff"],
                comparison["parity"]["trade_count_diff_pct"])
    logger.info("Forward PnL: %.2f | Paper PnL: %.2f | Diff: %.2f",
                fwd_stats["pnl"], paper_stats["pnl"], comparison["parity"]["pnl_diff"])
    logger.info("Signal generation restored: %s", signal_alive)
    logger.info("Overall parity: %s", comparison["assessment"]["overall_parity"])
    logger.info("Results in: %s", out)


if __name__ == "__main__":
    main()
