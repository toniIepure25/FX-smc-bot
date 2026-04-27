#!/usr/bin/env python3
"""Live forward paper trading service for VPS deployment.

Production entry point for bos_only_usdjpy. Polls Yahoo Finance
for live H1/H4 candles and runs the frozen strategy in real-time.

Usage:
  python scripts/run_live_forward_service.py              # live mode (default)
  python scripts/run_live_forward_service.py --mode replay # replay historical
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_pair_data, load_htf_data
from fx_smc_bot.data.providers.live_feed import (
    FileWatchFeedProvider,
    ReplayFeedProvider,
)
from fx_smc_bot.live.alerts import (
    AlertEvent,
    AlertRouter,
    AlertSeverity,
    FileAlertSink,
    LogAlertSink,
    TelegramAlertSink,
)
from fx_smc_bot.live.drift_detector import BaselineProfile
from fx_smc_bot.live.forward_runner import ForwardPaperRunner
from fx_smc_bot.live.state import LiveState, config_fingerprint
from fx_smc_bot.risk.sizing import DrawdownAwareSizing

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

PAIR = TradingPair.USDJPY
TF = Timeframe.H1


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(console)

    fh = logging.FileHandler(log_dir / "service.log")
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(fh)


logger = logging.getLogger("live_forward_service")


def build_frozen_config() -> AppConfig:
    """Frozen promoted prop_v2_hardened configuration. DO NOT MODIFY."""
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


def _build_alert_router(output_dir: Path) -> AlertRouter:
    sinks = [
        LogAlertSink(),
        FileAlertSink(output_dir / "alerts.jsonl"),
    ]
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        sinks.append(TelegramAlertSink(
            tg_token, tg_chat,
            min_severity=AlertSeverity.INFO,
        ))
        logger.info("Telegram alerts enabled (chat_id=%s)", tg_chat)
    else:
        logger.info("Telegram disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    return AlertRouter(sinks=sinks, dedup_cooldown_seconds=300.0)


_UTC = timezone.utc
_RO_TZ = ZoneInfo("Europe/Bucharest")


def _now_utc() -> datetime:
    return datetime.now(_UTC)


def _write_health(health_path: Path, status: str, details: dict) -> None:
    health = {"status": status, "timestamp": _now_utc().isoformat(), **details}
    health_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = health_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(health, f, indent=2, default=str)
    tmp.rename(health_path)


def _find_latest_checkpoint(output_dir: Path) -> Path | None:
    candidates = list(output_dir.glob("*/state.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _build_yahoo_feeds():
    from fx_smc_bot.data.providers.yahoo_feed import YahooFeedProvider

    ltf_feed = YahooFeedProvider(pair=PAIR, timeframe=TF, poll_interval_seconds=120.0)
    htf_feed = YahooFeedProvider(pair=PAIR, timeframe=Timeframe.H4, poll_interval_seconds=300.0)

    logger.info("Yahoo Finance feeds configured: %s", PAIR.value)
    logger.info("Fetching H1 warmup history...")
    ltf_warmup = ltf_feed.fetch_history(count=500)
    logger.info("Fetching H4 warmup history...")
    htf_warmup = htf_feed.fetch_history(count=200)

    return ltf_feed, htf_feed, ltf_warmup, htf_warmup


def main() -> None:
    parser = argparse.ArgumentParser(description="Live forward paper service")
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data/real"))
    parser.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR", "forward_runs"))
    parser.add_argument("--mode", choices=["live", "replay"],
                        default=os.environ.get("FEED_MODE", "live"))
    parser.add_argument("--auto-resume", action="store_true",
                        default=os.environ.get("AUTO_RESUME", "true").lower() == "true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(output_dir / "logs")

    cfg = build_frozen_config()
    cfg.data.root_dir = Path(args.data_dir)
    fp = config_fingerprint(cfg)
    logger.info("Config fingerprint: %s", fp)

    alert_router = _build_alert_router(output_dir)
    health_path = output_dir / "health.json"

    resume_path: Path | None = None
    if args.auto_resume:
        resume_path = _find_latest_checkpoint(output_dir)
        if resume_path:
            try:
                saved = LiveState.load(resume_path)
                if not saved.verify_config(cfg):
                    logger.error("Config fingerprint mismatch — starting fresh")
                    alert_router.emit(AlertEvent(
                        level="CRITICAL",
                        message="Config fingerprint mismatch on resume — starting fresh session",
                        timestamp=_now_utc(),
                        category="state_integrity",
                    ))
                    resume_path = None
                else:
                    logger.info("Resuming: %s (bars=%d, equity=%.2f)",
                                resume_path, saved.bars_processed, saved.equity)
            except Exception:
                logger.exception("Checkpoint validation failed — starting fresh")
                resume_path = None

    htf_feed = None
    ltf_warmup = None
    htf_warmup = None

    if args.mode == "live":
        feed, htf_feed, ltf_warmup, htf_warmup = _build_yahoo_feeds()
    else:
        logger.info("Loading replay data from %s", args.data_dir)
        all_data = load_pair_data(args.data_dir, pairs=[PAIR], timeframe=TF)
        if PAIR not in all_data:
            logger.error("No data for %s in %s", PAIR.value, args.data_dir)
            sys.exit(1)
        feed = ReplayFeedProvider(all_data[PAIR])
        logger.info("Replay feed: %d bars", feed.remaining)
        try:
            htf_dict = load_htf_data(all_data, htf_timeframe=Timeframe.H4, data_dir=args.data_dir)
            htf_series = htf_dict.get(PAIR)
            if htf_series:
                htf_feed = ReplayFeedProvider(htf_series)
        except Exception:
            pass

    sizing = DrawdownAwareSizing(max_dd_for_full_reduction=0.10, min_scale=0.25)
    baseline = BaselineProfile(win_rate=0.57, avg_rr=1.5, profit_factor=1.8)

    runner = ForwardPaperRunner(
        config=cfg,
        feed=feed,
        output_dir=output_dir,
        alert_sink=alert_router,
        sizing_policy=sizing,
        baseline_profile=baseline,
        htf_feed=htf_feed,
    )

    if ltf_warmup:
        runner.load_warmup(ltf_warmup, htf_warmup)

    _write_health(health_path, "starting", {"run_id": runner.run_id, "mode": args.mode})

    alert_router.emit(AlertEvent(
        level="INFO",
        message=(
            f"FX SMC Bot started\n"
            f"Strategy: bos_only_usdjpy\n"
            f"Mode: {'LIVE Paper' if args.mode == 'live' else 'Replay'}\n"
            f"Feed: Yahoo Finance (real-time)\n"
            f"Run: {runner.run_id}"
        ),
        timestamp=_now_utc(),
        category="lifecycle",
    ))

    logger.info("Starting: run_id=%s, mode=%s", runner.run_id, args.mode)

    try:
        runner.start(resume_from=resume_path)
    except KeyboardInterrupt:
        logger.info("Interrupted — stopping gracefully")
    except Exception:
        logger.exception("Unhandled exception in forward runner")
        alert_router.emit(AlertEvent(
            level="EMERGENCY",
            message="Bot crashed — auto-restarting. Check logs if this repeats.",
            timestamp=_now_utc(),
            category="crash",
        ))
        _write_health(health_path, "crashed", {"run_id": runner.run_id})
        raise
    finally:
        _write_health(health_path, "stopped", {"run_id": runner.run_id})
        alert_router.emit(AlertEvent(
            level="INFO",
            message=f"FX SMC Bot stopped — run {runner.run_id}",
            timestamp=_now_utc(),
            category="lifecycle",
        ))


if __name__ == "__main__":
    main()
