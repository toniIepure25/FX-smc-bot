#!/usr/bin/env python3
"""Automated report generation for the live forward paper service.

Reads session artifacts from forward_runs/ and produces structured
daily or weekly reports. Optionally sends the summary via Telegram.

Usage:
  python scripts/generate_report.py --type daily
  python scripts/generate_report.py --type weekly
  python scripts/generate_report.py --type health
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("report_gen")


def _find_latest_run(base: Path) -> Path | None:
    runs = [d for d in base.iterdir() if d.is_dir() and d.name.startswith("fwd_")]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_alerts(path: Path, since: datetime | None = None) -> list[dict]:
    if not path.exists():
        return []
    alerts = []
    with open(path) as f:
        for line in f:
            try:
                a = json.loads(line)
                if since:
                    ts = datetime.fromisoformat(a.get("timestamp", ""))
                    if ts < since:
                        continue
                alerts.append(a)
            except (json.JSONDecodeError, ValueError):
                continue
    return alerts


def _daily_reviews(run_dir: Path) -> list[dict]:
    review_dir = run_dir / "reviews"
    if not review_dir.exists():
        return []
    reviews = []
    for f in sorted(review_dir.glob("day_*.json")):
        with open(f) as fh:
            reviews.append(json.load(fh))
    return reviews


def generate_health_report(base: Path) -> str:
    health = _load_json(base / "health.json")
    if not health:
        return "*Health*: No health file found"

    run_dir = _find_latest_run(base)
    summary = _load_json(run_dir / "session_summary.json") if run_dir else None

    lines = [
        "*Health Status Report*",
        f"Status: `{health.get('status', 'unknown')}`",
        f"Timestamp: `{health.get('timestamp', 'N/A')}`",
    ]

    if summary:
        lines.extend([
            f"Run ID: `{summary.get('run_id', 'N/A')}`",
            f"Bars: `{summary.get('bars_processed', 0)}`",
            f"Trades: `{summary.get('total_trades', 0)}`",
            f"PnL: `${summary.get('total_pnl', 0):,.2f}`",
            f"Equity: `${summary.get('final_equity', 0):,.2f}`",
        ])
        fh = summary.get("feed_health", {})
        lines.append(f"Feed completeness: `{fh.get('completeness_pct', 0):.0f}%`")

    return "\n".join(lines)


def generate_daily_report(base: Path) -> str:
    run_dir = _find_latest_run(base)
    if not run_dir:
        return "*Daily Report*: No active run found"

    summary = _load_json(run_dir / "session_summary.json")
    reviews = _daily_reviews(run_dir)

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")

    lines = [
        f"*Daily Report — {today}*",
        "",
    ]

    if summary:
        mon = summary.get("monitor", {})
        lines.extend([
            f"Run: `{summary.get('run_id', 'N/A')}`",
            f"Bars processed: `{summary.get('bars_processed', 0)}`",
            f"Total trades: `{summary.get('total_trades', 0)}`",
            f"Win rate: `{summary.get('win_rate', 0):.1%}`",
            f"PnL: `${summary.get('total_pnl', 0):,.2f}`",
            f"Equity: `${summary.get('final_equity', 0):,.2f}`",
            f"Peak equity: `${mon.get('peak_equity', 0):,.2f}`",
            f"Trailing DD: `{mon.get('trailing_dd_pct', 0):.2%}`",
            f"Max loss streak: `{mon.get('max_loss_streak', 0)}`",
            f"CB fires: `{mon.get('total_cb_fires', 0)}`",
            f"Signal drought bars: `{mon.get('signal_drought_bars', 0)}`",
        ])

        drift = summary.get("drift", {})
        if drift.get("any_drift_detected"):
            lines.append("\n*Drift detected:*")
            for t in drift.get("tests", []):
                if t.get("significant"):
                    lines.append(f"  - {t.get('message', 'unknown')}")

    # Alerts from last 24h
    since = now - timedelta(hours=24)
    alerts = _load_alerts(base / "alerts.jsonl", since)
    warn_count = sum(1 for a in alerts if a.get("level", "").upper() in ("WARNING", "CRITICAL", "EMERGENCY"))
    lines.append(f"\nAlerts (24h): `{len(alerts)}` total, `{warn_count}` warnings+")

    # Latest daily review
    if reviews:
        last = reviews[-1]
        lines.append(f"\nLatest daily review (day {last.get('day', '?')}):")
        lines.append(f"  Equity: `${last.get('equity', 0):,.2f}`")
        lines.append(f"  Trades today: `{last.get('trades_today', 0)}`")
        lines.append(f"  State: `{last.get('operational_state', 'unknown')}`")

    return "\n".join(lines)


def generate_weekly_report(base: Path) -> str:
    run_dir = _find_latest_run(base)
    if not run_dir:
        return "*Weekly Report*: No active run found"

    summary = _load_json(run_dir / "session_summary.json")
    reviews = _daily_reviews(run_dir)

    now = datetime.utcnow()
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    lines = [
        f"*Weekly Report — week of {week_start}*",
        "",
    ]

    if summary:
        mon = summary.get("monitor", {})
        rev = summary.get("reviews", {})
        lines.extend([
            f"Run: `{summary.get('run_id', 'N/A')}`",
            f"Bars: `{summary.get('bars_processed', 0)}`",
            f"Trades: `{summary.get('total_trades', 0)}`",
            f"Win rate: `{summary.get('win_rate', 0):.1%}`",
            f"PnL: `${summary.get('total_pnl', 0):,.2f}`",
            f"Profit factor: estimated from WR and avg RR",
            f"Equity: `${summary.get('final_equity', 0):,.2f}`",
            f"Peak: `${mon.get('peak_equity', 0):,.2f}`",
            f"Trailing DD: `{mon.get('trailing_dd_pct', 0):.2%}`",
            f"CB fires: `{mon.get('total_cb_fires', 0)}`",
            "",
            "*Review pipeline:*",
            f"  Candidates reviewed: `{rev.get('candidates_reviewed', 0)}`",
            f"  Accepted: `{rev.get('candidates_accepted', 0)}`",
            f"  Rejected: `{rev.get('candidates_rejected', 0)}`",
        ])
        reasons = rev.get("rejection_reasons", {})
        if reasons:
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                lines.append(f"    {reason}: `{count}`")

    # Alerts summary for the week
    since = now - timedelta(days=7)
    alerts = _load_alerts(base / "alerts.jsonl", since)
    by_level = defaultdict(int)
    for a in alerts:
        by_level[a.get("level", "INFO").upper()] += 1
    lines.append(f"\n*Alerts (7d):* {dict(by_level)}")

    # Daily trade counts
    if reviews:
        lines.append("\n*Daily summary:*")
        for r in reviews[-7:]:
            lines.append(f"  Day {r.get('day', '?')}: {r.get('trades_today', 0)} trades, "
                         f"${r.get('equity', 0):,.0f}")

    fh = (summary or {}).get("feed_health", {})
    lines.append(f"\n*Feed health:*")
    lines.append(f"  Bars received: `{fh.get('total_bars_received', 0)}`")
    lines.append(f"  Completeness: `{fh.get('completeness_pct', 0):.0f}%`")
    lines.append(f"  Gaps: `{fh.get('gaps_detected', 0)}`")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "health"], required=True)
    parser.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR", "forward_runs"))
    parser.add_argument("--send-telegram", action="store_true",
                        default=os.environ.get("TELEGRAM_BOT_TOKEN", "") != "")
    args = parser.parse_args()

    base = Path(args.output_dir)

    if args.type == "health":
        report = generate_health_report(base)
    elif args.type == "daily":
        report = generate_daily_report(base)
    else:
        report = generate_weekly_report(base)

    print(report)

    report_dir = base / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(report_dir / f"{args.type}_{ts}.md", "w") as f:
        f.write(report)

    if args.send_telegram:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if token and chat:
            from fx_smc_bot.live.alerts import TelegramAlertSink
            tg = TelegramAlertSink(token, chat)
            tg.send_report(report)
            logger.info("Report sent to Telegram")
        else:
            logger.warning("Telegram credentials not set — report not sent")


if __name__ == "__main__":
    main()
