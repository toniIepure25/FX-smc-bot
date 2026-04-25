#!/usr/bin/env python3
"""Forward paper-validation CLI entry point.

Runs the ForwardPaperRunner against either:
  - A replay feed (historical data simulating live arrival)
  - A file-watch feed (new CSVs dropped into a directory)

Usage:
  python scripts/run_forward_paper.py --data-dir data/real --mode replay
  python scripts/run_forward_paper.py --watch-dir data/live --mode file_watch
  python scripts/run_forward_paper.py --data-dir data/real --resume forward_runs/fwd_xxx/state.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_pair_data, load_htf_data
from fx_smc_bot.data.providers.live_feed import (
    FileWatchFeedProvider,
    ReplayFeedProvider,
)
from fx_smc_bot.live.alerts import AlertRouter, FileAlertSink, LogAlertSink
from fx_smc_bot.live.drift_detector import BaselineProfile
from fx_smc_bot.live.forward_runner import ForwardPaperRunner
from fx_smc_bot.risk.sizing import DrawdownAwareSizing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_forward_paper")


def build_prop_config() -> AppConfig:
    """Build AppConfig matching the promoted prop_v2_hardened profile."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward paper-validation runner")
    parser.add_argument("--data-dir", type=str, default="data/real",
                        help="Directory with historical USDJPY data (for replay mode)")
    parser.add_argument("--watch-dir", type=str, default="",
                        help="Directory to watch for new CSV files (for file_watch mode)")
    parser.add_argument("--mode", choices=["replay", "file_watch"], default="replay")
    parser.add_argument("--output-dir", type=str, default="forward_runs")
    parser.add_argument("--resume", type=str, default="",
                        help="Path to state.json checkpoint for resume")
    parser.add_argument("--baseline", type=str, default="",
                        help="Path to baseline profile JSON for drift detection")
    args = parser.parse_args()

    cfg = build_prop_config()
    cfg.data.root_dir = Path(args.data_dir)

    pair = TradingPair.USDJPY
    tf = Timeframe.H1

    # Build feed
    if args.mode == "replay":
        logger.info("Loading data for replay feed from %s", args.data_dir)
        all_data = load_pair_data(args.data_dir, pairs=[pair], timeframe=tf)
        if pair not in all_data:
            logger.error("No data found for %s %s in %s", pair.value, tf.value, args.data_dir)
            sys.exit(1)
        feed = ReplayFeedProvider(all_data[pair])
        logger.info("Replay feed: %d bars", feed.remaining)
    else:
        watch_dir = Path(args.watch_dir)
        if not watch_dir.exists():
            logger.error("Watch directory does not exist: %s", watch_dir)
            sys.exit(1)
        feed = FileWatchFeedProvider(watch_dir, pair, tf)
        logger.info("File-watch feed on %s", watch_dir)
        all_data = {}

    # HTF feed (try to load H4 data for structure context)
    htf_feed = None
    try:
        if all_data:
            htf_dict = load_htf_data(all_data, htf_timeframe=Timeframe.H4, data_dir=args.data_dir)
            htf_series = htf_dict.get(pair)
            if htf_series:
                htf_feed = ReplayFeedProvider(htf_series)
                logger.info("HTF replay feed loaded: %d bars", htf_feed.remaining)
    except Exception:
        logger.info("No HTF data available — running without HTF context")

    # Baseline profile
    baseline = BaselineProfile()
    if args.baseline and Path(args.baseline).exists():
        baseline = BaselineProfile.from_json(args.baseline)
        logger.info("Loaded baseline profile from %s", args.baseline)

    # Alert routing
    output_dir = Path(args.output_dir)
    alert_router = AlertRouter(sinks=[
        LogAlertSink(),
        FileAlertSink(output_dir / "alerts.jsonl"),
    ])

    # Sizing policy
    sizing_policy = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)

    runner = ForwardPaperRunner(
        config=cfg,
        feed=feed,
        output_dir=output_dir,
        alert_sink=alert_router,
        sizing_policy=sizing_policy,
        baseline_profile=baseline,
        htf_feed=htf_feed,
    )

    resume_path = Path(args.resume) if args.resume else None
    logger.info("Starting forward paper session: %s", runner.run_id)

    runner.start(resume_from=resume_path)
    logger.info("Forward paper session complete")


if __name__ == "__main__":
    main()
