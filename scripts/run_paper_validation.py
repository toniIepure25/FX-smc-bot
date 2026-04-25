#!/usr/bin/env python3
"""Paper Validation Campaign Runner.

Orchestrates a disciplined multi-week paper-trading validation program
for the promoted bos_only_usdjpy candidate. Handles:

- Config fingerprint validation before each run
- Persistent session identity
- Time-bounded replay windows (--weeks N)
- Daily/weekly artifact generation (--generate-reviews)
- Reconciliation against backtest expectations
- Review-period artifact organization

Usage:
    python scripts/run_paper_validation.py --weeks 6
    python scripts/run_paper_validation.py --resume <session_id>
    python scripts/run_paper_validation.py --generate-reviews <session_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.live.journal import EventJournal, JournalEvent
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.research.paper_review import (
    PaperReviewChecklist,
    PaperStageRecommendation,
    PaperStageStatus,
    build_daily_summaries,
    build_weekly_summary,
    evaluate_paper_stage,
    format_paper_review,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("paper_validation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
PROGRAM_DIR = PROJECT_ROOT / "paper_validation_program"
FROZEN_CONFIG_PATH = (
    PROJECT_ROOT / "results" / "final_promotion_gate"
    / "bos_only_usdjpy_champion_bundle" / "champion_config.json"
)

PROMOTED_CANDIDATE = "bos_only_usdjpy"
PROMOTED_FAMILIES = ["bos_continuation"]
PROMOTED_PAIRS = ["USDJPY"]
RISK_CONFIG = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}

BARS_PER_WEEK_H1 = 5 * 24  # ~120 bars per week (weekday hours)


def _compute_config_fingerprint(cfg: dict) -> str:
    canonical = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _build_promoted_config() -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = list(PROMOTED_FAMILIES)
    for k, v in RISK_CONFIG.items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _validate_config() -> tuple[bool, str]:
    """Validate that the frozen config matches expectations."""
    if not FROZEN_CONFIG_PATH.exists():
        return False, f"Frozen config not found at {FROZEN_CONFIG_PATH}"
    with open(FROZEN_CONFIG_PATH) as f:
        frozen = json.load(f)
    if frozen.get("champion") != PROMOTED_CANDIDATE:
        return False, f"Champion mismatch: expected {PROMOTED_CANDIDATE}, got {frozen.get('champion')}"
    if frozen.get("family") != "bos_continuation":
        return False, f"Family mismatch: expected bos_continuation, got {frozen.get('family')}"
    if frozen.get("pairs") != PROMOTED_PAIRS:
        return False, f"Pairs mismatch: expected {PROMOTED_PAIRS}, got {frozen.get('pairs')}"
    return True, "Config validated successfully"


def _init_session(resume_id: str | None = None) -> tuple[str, Path]:
    """Initialize or resume a paper validation session."""
    sessions_dir = PROGRAM_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    if resume_id:
        session_dir = sessions_dir / resume_id
        if not session_dir.exists():
            logger.error("Session %s not found", resume_id)
            sys.exit(1)
        logger.info("Resuming session %s", resume_id)
        return resume_id, session_dir

    session_id = f"pv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "session_id": session_id,
        "candidate": PROMOTED_CANDIDATE,
        "started_at": datetime.utcnow().isoformat(),
        "config_fingerprint": _compute_config_fingerprint({
            "families": PROMOTED_FAMILIES,
            "pairs": PROMOTED_PAIRS,
            "risk": RISK_CONFIG,
        }),
        "status": "active",
        "checkpoints_completed": [],
    }
    (session_dir / "session_manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info("Created new session: %s", session_id)
    return session_id, session_dir


def _create_checkpoint(session_dir: Path, checkpoint_name: str, data: dict) -> Path:
    """Create a checkpoint directory with artifacts."""
    cp_dir = session_dir / "checkpoints" / checkpoint_name
    cp_dir.mkdir(parents=True, exist_ok=True)
    (cp_dir / "checkpoint.json").write_text(json.dumps({
        "checkpoint": checkpoint_name,
        "timestamp": datetime.utcnow().isoformat(),
        **data,
    }, indent=2, default=str))
    return cp_dir


def _slice_to_window(
    data: dict[TradingPair, BarSeries], weeks: int,
) -> tuple[dict[TradingPair, BarSeries], dict[str, Any]]:
    """Slice data to the last N weeks and return metadata about the window."""
    target_bars = weeks * BARS_PER_WEEK_H1
    sliced: dict[TradingPair, BarSeries] = {}
    window_meta: dict[str, Any] = {"weeks": weeks, "target_bars": target_bars}

    for pair, series in data.items():
        n = len(series)
        start = max(0, n - target_bars)
        sl = series.slice(start, n)
        sliced[pair] = sl
        first_ts = sl.timestamps[0].astype("datetime64[us]").item()
        last_ts = sl.timestamps[-1].astype("datetime64[us]").item()
        window_meta[pair.value] = {
            "total_available": n,
            "window_bars": len(sl),
            "start": str(first_ts),
            "end": str(last_ts),
        }
        logger.info(
            "  %s: %d bars window [%s .. %s] (of %d total)",
            pair.value, len(sl), first_ts, last_ts, n,
        )

    return sliced, window_meta


def _find_journal(session_dir: Path) -> Path | None:
    """Find the journal.jsonl inside a session's runs directory."""
    runs_dir = session_dir / "runs"
    if not runs_dir.exists():
        return None
    journals = list(runs_dir.glob("*/journal.jsonl"))
    if not journals:
        return None
    return sorted(journals, key=lambda p: p.stat().st_mtime)[-1]


def _read_journal_events(journal_path: Path) -> list[dict[str, Any]]:
    """Read all events from a journal file as dicts."""
    events: list[dict[str, Any]] = []
    with open(journal_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _split_events_by_week(
    events: list[dict[str, Any]], bars_per_week: int = BARS_PER_WEEK_H1,
) -> list[list[dict[str, Any]]]:
    """Split journal events into weekly buckets based on bar time ordering."""
    bar_events = [e for e in events if e.get("event_type") in (
        "signal", "fill", "order", "daily_summary", "state_transition",
        "candidate_rejected", "alert",
    )]
    if not bar_events:
        return []

    all_bar_times = sorted({e["timestamp"] for e in bar_events if "timestamp" in e})
    if not all_bar_times:
        return []

    week_boundaries: list[str] = []
    for i in range(0, len(all_bar_times), bars_per_week):
        week_boundaries.append(all_bar_times[i])
    week_boundaries.append("9999-99-99")

    weeks: list[list[dict[str, Any]]] = [[] for _ in range(len(week_boundaries) - 1)]
    for evt in bar_events:
        ts = evt.get("timestamp", "")
        for i in range(len(week_boundaries) - 1):
            if week_boundaries[i] <= ts < week_boundaries[i + 1]:
                weeks[i].append(evt)
                break

    return [w for w in weeks if w]


def generate_weekly_reviews(session_dir: Path, n_weeks: int = 6) -> None:
    """Generate week-by-week review artifacts from a completed session."""
    journal_path = _find_journal(session_dir)
    if journal_path is None:
        logger.error("No journal found in session %s", session_dir.name)
        return

    logger.info("Reading journal from %s", journal_path)
    events = _read_journal_events(journal_path)
    logger.info("  Total events: %d", len(events))

    reviews_dir = session_dir / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    run_complete = [e for e in events if e.get("event_type") == "run_complete"]
    run_meta = run_complete[0].get("data", {}) if run_complete else {}

    weekly_buckets = _split_events_by_week(events)
    logger.info("  Weekly buckets: %d", len(weekly_buckets))

    weekly_summaries = []
    all_daily = []

    for i, week_events in enumerate(weekly_buckets):
        week_num = i + 1
        label = f"Week {week_num}"
        logger.info("  Generating %s review (%d events) ...", label, len(week_events))

        daily_sums = build_daily_summaries(week_events)
        all_daily.extend(daily_sums)
        ws = build_weekly_summary(daily_sums, week_label=label)
        weekly_summaries.append(ws)

        signals = [e for e in week_events if e.get("event_type") == "signal"]
        fills = [e for e in week_events if e.get("event_type") == "fill"]
        rejected = [e for e in week_events if e.get("event_type") == "candidate_rejected"]
        transitions = [e for e in week_events if e.get("event_type") == "state_transition"]

        ts_range = sorted({e["timestamp"] for e in week_events if "timestamp" in e})
        start_ts = ts_range[0] if ts_range else "N/A"
        end_ts = ts_range[-1] if ts_range else "N/A"

        wins = sum(1 for e in fills if e.get("data", {}).get("reason") == "take_profit_hit")
        losses = sum(1 for e in fills if e.get("data", {}).get("reason") == "stop_loss_hit")
        wr = wins / (wins + losses) if (wins + losses) > 0 else 0.0

        md = [
            f"# {label} Review — Historical Paper Replay",
            "",
            f"**Mode**: Historical paper replay (NOT live forward)",
            f"**Candidate**: {PROMOTED_CANDIDATE}",
            f"**Period**: {start_ts} to {end_ts}",
            "",
            "## Performance Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total trades | {ws.total_trades} |",
            f"| Weekly PnL | {ws.weekly_pnl:,.2f} |",
            f"| Win rate | {wr:.1%} |",
            f"| Max drawdown | {ws.max_drawdown_pct:.2%} |",
            f"| Drift detected | {'YES' if ws.drift_detected else 'No'} |",
            "",
            "## Signal Funnel",
            "",
            f"| Stage | Count |",
            f"|-------|-------|",
            f"| Signals generated | {len(signals)} |",
            f"| Candidates rejected | {len(rejected)} |",
            f"| Orders filled | {len(fills)} |",
            f"| Wins (TP hit) | {wins} |",
            f"| Losses (SL hit) | {losses} |",
            "",
            "## Risk-State Transitions",
            "",
        ]

        if transitions:
            md.append("| Time | From | To | Reason |")
            md.append("|------|------|----|--------|")
            for t in transitions:
                d = t.get("data", {})
                md.append(f"| {t.get('timestamp', 'N/A')} | {d.get('old', '')} | {d.get('new', '')} | {d.get('reason', '')} |")
        else:
            md.append("No risk-state transitions this week.")

        md.extend([
            "",
            "## Daily Summaries",
            "",
            "| Date | Trades | PnL | Equity | DD% | State |",
            "|------|--------|-----|--------|-----|-------|",
        ])
        for ds in daily_sums:
            md.append(
                f"| {ds.date} | {ds.trades_opened} | {ds.daily_pnl:,.2f} | "
                f"{ds.equity:,.2f} | {ds.drawdown_pct:.2%} | {ds.operational_state} |"
            )

        if ws.incidents:
            md.extend(["", "## Incidents", ""])
            for inc in ws.incidents:
                md.append(f"- {inc}")

        review_path = reviews_dir / f"week_{week_num}_review.md"
        review_path.write_text("\n".join(md))
        logger.info("  Written %s", review_path.name)

    # Final 6-week review
    _generate_final_review(reviews_dir, weekly_summaries, run_meta, events)
    _generate_sanity_report(reviews_dir, events, run_meta)
    _generate_health_report(reviews_dir, events, run_meta)

    # Save weekly summaries as JSON
    (reviews_dir / "weekly_summaries.json").write_text(json.dumps(
        [ws.to_dict() for ws in weekly_summaries], indent=2, default=str,
    ))
    logger.info("Review generation complete: %s", reviews_dir)


def _generate_final_review(
    reviews_dir: Path,
    weekly_summaries: list,
    run_meta: dict,
    events: list[dict],
) -> None:
    """Generate the final 6-week aggregate review."""
    total_trades = sum(ws.total_trades for ws in weekly_summaries)
    total_pnl = sum(ws.weekly_pnl for ws in weekly_summaries)
    max_dd = max((ws.max_drawdown_pct for ws in weekly_summaries), default=0.0)
    any_drift = any(ws.drift_detected for ws in weekly_summaries)

    fills = [e for e in events if e.get("event_type") == "fill"]
    wins = sum(1 for e in fills if e.get("data", {}).get("reason") == "take_profit_hit")
    losses = sum(1 for e in fills if e.get("data", {}).get("reason") == "stop_loss_hit")
    wr = wins / (wins + losses) if (wins + losses) > 0 else 0.0

    replay_window = run_meta.get("replay_window", {})
    initial_equity = 100_000.0
    final_equity = run_meta.get("final_equity", initial_equity)
    ret_pct = ((final_equity - initial_equity) / initial_equity) * 100

    md = [
        "# Final 6-Week Historical Paper Replay Review",
        "",
        f"**Mode**: Historical paper replay (NOT live forward trading)",
        f"**Candidate**: {PROMOTED_CANDIDATE}",
        f"**Replay window**: {replay_window.get('start', 'N/A')} to {replay_window.get('end', 'N/A')}",
        f"**Total bars**: {replay_window.get('bars', run_meta.get('bars_processed', 'N/A'))}",
        "",
        "## Aggregate Performance",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total trades | {total_trades} |",
        f"| Total PnL | {total_pnl:,.2f} |",
        f"| Return % | {ret_pct:.2f}% |",
        f"| Win rate | {wr:.1%} |",
        f"| Max weekly DD | {max_dd:.2%} |",
        f"| Drift detected | {'YES' if any_drift else 'No'} |",
        f"| Final equity | {final_equity:,.2f} |",
        "",
        "## Week-by-Week Summary",
        "",
        "| Week | Trades | PnL | Max DD | Drift |",
        "|------|--------|-----|--------|-------|",
    ]
    for ws in weekly_summaries:
        md.append(
            f"| {ws.week} | {ws.total_trades} | {ws.weekly_pnl:,.2f} | "
            f"{ws.max_drawdown_pct:.2%} | {'YES' if ws.drift_detected else 'No'} |"
        )

    # Reconciliation section
    md.extend([
        "",
        "## Reconciliation vs Backtest",
        "",
    ])
    cp_files = list((reviews_dir.parent / "checkpoints").glob("*/checkpoint.json")) if (reviews_dir.parent / "checkpoints").exists() else []
    if cp_files:
        cp_data = json.loads(sorted(cp_files)[-1].read_text())
        recon = cp_data.get("reconciliation", {})
        bt_trades = recon.get("backtest_trades", "N/A")
        bt_pnl = recon.get("backtest_pnl", "N/A")
        bt_sharpe = recon.get("backtest_sharpe", "N/A")
        md.extend([
            f"| Metric | Paper | Backtest |",
            f"|--------|-------|----------|",
            f"| Trades | {total_trades} | {bt_trades} |",
            f"| PnL | {total_pnl:,.2f} | {bt_pnl} |",
            f"| Sharpe | N/A | {bt_sharpe} |",
        ])
        if isinstance(bt_trades, (int, float)) and bt_trades > 0:
            trade_diff = abs(total_trades - bt_trades) / bt_trades * 100
            md.append(f"\nTrade count discrepancy: {trade_diff:.1f}%")
    else:
        md.append("No reconciliation checkpoint found.")

    md.extend(["", "## Replay Completion Status", ""])
    md.append(f"- Replay complete: {run_meta.get('replay_complete', False)}")
    md.append(f"- Replay mode: {run_meta.get('replay_mode', 'unknown')}")

    (reviews_dir / "final_6week_paper_replay_review.md").write_text("\n".join(md))
    logger.info("  Written final_6week_paper_replay_review.md")


def _generate_sanity_report(
    reviews_dir: Path,
    events: list[dict],
    run_meta: dict,
) -> None:
    """Generate replay_sanity_report.md checking equity/sizing consistency."""
    fills = [e for e in events if e.get("event_type") == "fill"]
    signals = [e for e in events if e.get("event_type") == "signal"]
    transitions = [e for e in events if e.get("event_type") == "state_transition"]
    rejected = [e for e in events if e.get("event_type") == "candidate_rejected"]

    initial_equity = 100_000.0
    final_equity = run_meta.get("final_equity", initial_equity)
    ret_pct = ((final_equity - initial_equity) / initial_equity) * 100
    n_trades = run_meta.get("total_trades", len(fills) // 2)
    bars_processed = run_meta.get("bars_processed", 0)

    entry_fills = sum(1 for f in fills if f.get("data", {}).get("reason") == "market_fill")
    tp_fills = sum(1 for f in fills if f.get("data", {}).get("reason") == "take_profit_hit")
    sl_fills = sum(1 for f in fills if f.get("data", {}).get("reason") == "stop_loss_hit")

    risk_per_trade = RISK_CONFIG["base_risk_per_trade"]
    max_expected_risk_pnl = n_trades * risk_per_trade * initial_equity
    max_expected_loss = n_trades * risk_per_trade * initial_equity
    theoretical_max_return = max_expected_risk_pnl / initial_equity * 100

    lockouts = [t for t in transitions if t.get("data", {}).get("new") == "locked"]
    resets = [t for t in transitions if t.get("data", {}).get("new") == "active"
              and "new_day_reset" in t.get("data", {}).get("reason", "")]

    md = [
        "# Replay Sanity Report",
        "",
        f"**Mode**: Historical paper replay",
        f"**Candidate**: {PROMOTED_CANDIDATE}",
        "",
        "## Equity Sanity",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Initial equity | {initial_equity:,.2f} |",
        f"| Final equity | {final_equity:,.2f} |",
        f"| Return | {ret_pct:.2f}% |",
        f"| Bars processed | {bars_processed} |",
        f"| Total trades (round-trips) | {n_trades} |",
        "",
        "## Fill Breakdown",
        "",
        f"| Type | Count |",
        f"|------|-------|",
        f"| Entry (market) | {entry_fills} |",
        f"| Take-profit hit | {tp_fills} |",
        f"| Stop-loss hit | {sl_fills} |",
        f"| Total fills | {len(fills)} |",
        "",
        "## Risk Consistency",
        "",
        f"- Base risk per trade: {risk_per_trade:.2%}",
        f"- Max single-trade loss (intended): {risk_per_trade * initial_equity:,.2f}",
        f"- Theoretical max total risk exposure: {max_expected_risk_pnl:,.2f}",
        f"- Actual return: {ret_pct:.2f}%",
        "",
        "## Risk-State Recovery",
        "",
        f"- Total lockouts: {len(lockouts)}",
        f"- New-day resets from locked: {len(resets)}",
        f"- Recovery working: {'YES' if len(resets) >= len(lockouts) - 1 else 'NEEDS REVIEW'}",
        "",
        "## Signal Funnel Sanity",
        "",
        f"- Signals generated: {len(signals)}",
        f"- Candidates rejected: {len(rejected)}",
        f"- Pass-through rate: {len(fills) / max(1, len(signals)):.1%}",
        "",
    ]

    checks = []
    if n_trades == 0:
        checks.append("WARNING: Zero trades executed")
    if ret_pct > 200:
        checks.append(f"WARNING: Extreme return ({ret_pct:.0f}%) — check sizing logic")
    if ret_pct < -50:
        checks.append(f"WARNING: Extreme loss ({ret_pct:.0f}%) — check risk controls")
    if len(lockouts) > 0 and len(resets) == 0:
        checks.append("WARNING: Locked state with zero recoveries — runner stuck")
    if not checks:
        checks.append("All sanity checks passed.")

    md.extend(["## Sanity Checks", ""])
    for c in checks:
        md.append(f"- {c}")

    (reviews_dir / "replay_sanity_report.md").write_text("\n".join(md))
    logger.info("  Written replay_sanity_report.md")


def _generate_health_report(
    reviews_dir: Path,
    events: list[dict],
    run_meta: dict,
) -> None:
    """Generate replay_health_report.md from run_complete health snapshot."""
    health = run_meta.get("health", {})
    transitions = [e for e in events if e.get("event_type") == "state_transition"]
    alerts = [e for e in events if e.get("event_type") == "alert"]

    md = [
        "# Replay Health Report",
        "",
        f"**Mode**: Historical paper replay",
        f"**Candidate**: {PROMOTED_CANDIDATE}",
        "",
        "## Final Health Snapshot",
        "",
        f"| Component | Status |",
        f"|-----------|--------|",
        f"| Engine | {health.get('engine', 'N/A')} |",
        f"| Broker | {health.get('broker', 'N/A')} |",
        f"| Data | {health.get('data', 'N/A')} |",
        f"| Risk | {health.get('risk', 'N/A')} |",
        f"| Stale data flag | {health.get('stale_data_flag', 'N/A')} |",
        f"| Missing bar count | {health.get('missing_bar_count', 'N/A')} |",
        f"| Bars since last fill | {health.get('bars_since_last_fill', 'N/A')} |",
        f"| Is healthy | {health.get('is_healthy', 'N/A')} |",
        "",
        "## State Transition Log",
        "",
    ]

    if transitions:
        md.append("| Time | From | To | Reason |")
        md.append("|------|------|----|--------|")
        for t in transitions:
            d = t.get("data", {})
            md.append(f"| {t.get('timestamp', 'N/A')} | {d.get('old', '')} | {d.get('new', '')} | {d.get('reason', '')} |")
    else:
        md.append("No state transitions during replay.")

    if alerts:
        md.extend(["", "## Alerts", ""])
        for a in alerts[:50]:
            d = a.get("data", {})
            md.append(f"- [{a.get('timestamp', '')}] {d.get('level', '')}: {d.get('message', '')}")
        if len(alerts) > 50:
            md.append(f"- ... and {len(alerts) - 50} more alerts")

    replay_complete = run_meta.get("replay_complete", False)
    md.extend([
        "",
        "## Replay Completion",
        "",
        f"- Replay completed normally: {replay_complete}",
        f"- Replay mode: {run_meta.get('replay_mode', 'unknown')}",
    ])

    (reviews_dir / "replay_health_report.md").write_text("\n".join(md))
    logger.info("  Written replay_health_report.md")


def run_validation(
    resume_id: str | None = None,
    checkpoint: str | None = None,
    weeks: int = 6,
):
    """Run the paper validation campaign."""
    logger.info("=" * 60)
    logger.info("Paper Validation Campaign — %s", PROMOTED_CANDIDATE)
    logger.info("  Mode: Historical paper replay (%d weeks)", weeks)
    logger.info("=" * 60)

    valid, msg = _validate_config()
    if not valid:
        logger.error("Config validation FAILED: %s", msg)
        sys.exit(1)
    logger.info("Config validation: %s", msg)

    session_id, session_dir = _init_session(resume_id)

    logger.info("Loading real FX data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded")
        sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    jpy_data = {p: sr for p, sr in full_data.items() if p.value in PROMOTED_PAIRS}
    jpy_htf = {p: sr for p, sr in htf_data.items() if p.value in PROMOTED_PAIRS} if htf_data else None

    for pair, series in jpy_data.items():
        logger.info("  %s: %d bars total", pair.value, len(series))

    logger.info("Slicing to %d-week replay window ...", weeks)
    window_data, window_meta = _slice_to_window(jpy_data, weeks)

    if jpy_htf:
        htf_window, _ = _slice_to_window(jpy_htf, weeks)
    else:
        htf_window = None

    manifest_path = session_dir / "session_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["replay_window"] = window_meta
        manifest["replay_mode"] = "historical"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    cfg = _build_promoted_config()
    run_dir = session_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting %d-week paper trading replay ...", weeks)
    runner = PaperTradingRunner(cfg, output_dir=run_dir)
    final_state = runner.run(window_data, htf_window)

    logger.info("Paper trading replay complete:")
    logger.info("  Run ID: %s", runner._run_id)
    logger.info("  Bars: %d", final_state.bars_processed)
    logger.info("  Equity: %.2f", final_state.equity)
    logger.info("  State: %s", final_state.operational_state)

    logger.info("Running reconciliation backtest on same %d-week window ...", weeks)
    engine = BacktestEngine(cfg)
    bt_result = engine.run(window_data, htf_window)
    bt_metrics = engine.metrics(bt_result)

    recon = {
        "paper_equity": float(final_state.equity),
        "paper_bars": int(final_state.bars_processed),
        "backtest_trades": int(bt_metrics.total_trades),
        "backtest_sharpe": round(float(bt_metrics.sharpe_ratio), 4),
        "backtest_pf": round(float(bt_metrics.profit_factor), 4),
        "backtest_pnl": round(float(bt_metrics.total_pnl), 2),
    }

    cp_name = checkpoint or "6wk_replay"
    cp_data = {
        "session_id": session_id,
        "run_id": runner._run_id,
        "candidate": PROMOTED_CANDIDATE,
        "replay_window": window_meta,
        "replay_mode": "historical",
        "reconciliation": recon,
        "operational_state": final_state.operational_state,
    }
    cp_dir = _create_checkpoint(session_dir, cp_name, cp_data)
    logger.info("Checkpoint created: %s", cp_dir)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["checkpoints_completed"].append(cp_name)
        manifest["last_updated"] = datetime.utcnow().isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info("Generating weekly review artifacts ...")
    generate_weekly_reviews(session_dir, n_weeks=weeks)

    logger.info("=" * 60)
    logger.info("Session: %s", session_id)
    logger.info("Checkpoint: %s", cp_name)
    logger.info("All artifacts in: %s", session_dir)
    logger.info("=" * 60)

    return session_id, session_dir


def main():
    parser = argparse.ArgumentParser(description="Paper Validation Campaign Runner")
    parser.add_argument("--resume", type=str, default=None, help="Resume an existing session")
    parser.add_argument("--checkpoint", type=str, default=None,
                        help="Checkpoint label (e.g. week_1, week_2)")
    parser.add_argument("--weeks", type=int, default=6,
                        help="Number of weeks for the replay window (default: 6)")
    parser.add_argument("--generate-reviews", type=str, default=None, metavar="SESSION_ID",
                        help="Generate review artifacts for a completed session")
    args = parser.parse_args()

    if args.generate_reviews:
        session_dir = PROGRAM_DIR / "sessions" / args.generate_reviews
        if not session_dir.exists():
            logger.error("Session %s not found", args.generate_reviews)
            sys.exit(1)
        generate_weekly_reviews(session_dir, n_weeks=args.weeks)
    else:
        run_validation(resume_id=args.resume, checkpoint=args.checkpoint, weeks=args.weeks)


if __name__ == "__main__":
    main()
