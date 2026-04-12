"""Paper-candidate review workflow: structured daily/weekly summaries,
drift detection, cumulative discrepancy tracking, and pass/fail/conditional
promotion decisions for the paper testing stage.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PaperStageStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL = "conditional"
    SUSPENDED = "suspended"


@dataclass(slots=True)
class DailyReviewSummary:
    """Summary of a single paper trading day."""
    date: str = ""
    trades_opened: int = 0
    trades_closed: int = 0
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    equity: float = 0.0
    drawdown_pct: float = 0.0
    signals_generated: int = 0
    signals_rejected: int = 0
    incidents: list[str] = field(default_factory=list)
    # Risk-state monitoring fields
    throttle_activations: int = 0
    lockout_activations: int = 0
    circuit_breaker_proximity: float = 0.0
    peak_to_trough_dd: float = 0.0
    risk_utilization: float = 0.0
    operational_state: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "daily_pnl": round(self.daily_pnl, 2),
            "cumulative_pnl": round(self.cumulative_pnl, 2),
            "equity": round(self.equity, 2),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "signals_generated": self.signals_generated,
            "signals_rejected": self.signals_rejected,
            "incidents": self.incidents,
            "throttle_activations": self.throttle_activations,
            "lockout_activations": self.lockout_activations,
            "circuit_breaker_proximity": round(self.circuit_breaker_proximity, 4),
            "peak_to_trough_dd": round(self.peak_to_trough_dd, 4),
            "risk_utilization": round(self.risk_utilization, 4),
            "operational_state": self.operational_state,
        }


@dataclass(slots=True)
class WeeklyReviewSummary:
    """Summary of a paper trading week."""
    week: str = ""
    total_trades: int = 0
    weekly_pnl: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    daily_summaries: list[DailyReviewSummary] = field(default_factory=list)
    discrepancy_trend: float = 0.0
    drift_detected: bool = False
    incidents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "total_trades": self.total_trades,
            "weekly_pnl": round(self.weekly_pnl, 2),
            "win_rate": round(self.win_rate, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "discrepancy_trend": round(self.discrepancy_trend, 3),
            "drift_detected": self.drift_detected,
            "incidents": self.incidents,
            "n_daily_summaries": len(self.daily_summaries),
        }


@dataclass(slots=True)
class PaperReviewChecklist:
    """Structured review checklist for paper-stage decisions."""
    trade_volume_adequate: bool = False
    no_system_errors: bool = True
    discrepancy_within_threshold: bool = True
    no_behavioral_drift: bool = True
    drawdown_within_limits: bool = True
    no_blocking_incidents: bool = True
    circuit_breaker_not_fired: bool = True
    risk_profile_compliant: bool = True

    @property
    def all_pass(self) -> bool:
        return all([
            self.trade_volume_adequate, self.no_system_errors,
            self.discrepancy_within_threshold, self.no_behavioral_drift,
            self.drawdown_within_limits, self.no_blocking_incidents,
            self.circuit_breaker_not_fired, self.risk_profile_compliant,
        ])

    @property
    def n_failures(self) -> int:
        checks = [
            self.trade_volume_adequate, self.no_system_errors,
            self.discrepancy_within_threshold, self.no_behavioral_drift,
            self.drawdown_within_limits, self.no_blocking_incidents,
            self.circuit_breaker_not_fired, self.risk_profile_compliant,
        ]
        return sum(1 for c in checks if not c)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_volume_adequate": self.trade_volume_adequate,
            "no_system_errors": self.no_system_errors,
            "discrepancy_within_threshold": self.discrepancy_within_threshold,
            "no_behavioral_drift": self.no_behavioral_drift,
            "drawdown_within_limits": self.drawdown_within_limits,
            "no_blocking_incidents": self.no_blocking_incidents,
            "circuit_breaker_not_fired": self.circuit_breaker_not_fired,
            "risk_profile_compliant": self.risk_profile_compliant,
            "all_pass": self.all_pass,
            "n_failures": self.n_failures,
        }


@dataclass(slots=True)
class PaperStageRecommendation:
    """Decision object for paper stage promotion."""
    status: PaperStageStatus = PaperStageStatus.IN_PROGRESS
    candidate_label: str = ""
    checklist: PaperReviewChecklist = field(default_factory=PaperReviewChecklist)
    weekly_summaries: list[WeeklyReviewSummary] = field(default_factory=list)
    cumulative_discrepancy_pct: float = 0.0
    blocking_issues: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "candidate_label": self.candidate_label,
            "checklist": self.checklist.to_dict(),
            "cumulative_discrepancy_pct": round(self.cumulative_discrepancy_pct, 2),
            "blocking_issues": self.blocking_issues,
            "recommendation": self.recommendation,
            "n_weeks_reviewed": len(self.weekly_summaries),
        }


def build_daily_summaries(journal_events: list[dict[str, Any]]) -> list[DailyReviewSummary]:
    """Build daily review summaries from journal events."""
    days: dict[str, DailyReviewSummary] = {}

    for evt in journal_events:
        ts = evt.get("timestamp", "")
        date = ts[:10] if len(ts) >= 10 else "unknown"

        if date not in days:
            days[date] = DailyReviewSummary(date=date)

        day = days[date]
        etype = evt.get("event_type", "")

        if etype == "signal":
            day.signals_generated += 1
        elif etype == "fill":
            day.trades_opened += 1
        elif etype == "daily_summary":
            data = evt.get("data", {})
            day.equity = data.get("equity", day.equity)
        elif etype == "alert":
            day.incidents.append(evt.get("data", {}).get("message", str(evt.get("data", ""))))

    # Compute cumulative PnL from equity progression
    summaries = sorted(days.values(), key=lambda d: d.date)
    prev_equity = 0.0
    cumulative = 0.0
    for s in summaries:
        if prev_equity > 0 and s.equity > 0:
            s.daily_pnl = s.equity - prev_equity
        cumulative += s.daily_pnl
        s.cumulative_pnl = cumulative
        if prev_equity > 0:
            s.drawdown_pct = max(0.0, (prev_equity - s.equity) / prev_equity)
        prev_equity = s.equity if s.equity > 0 else prev_equity

    return summaries


def build_weekly_summary(
    daily_summaries: list[DailyReviewSummary],
    week_label: str = "",
) -> WeeklyReviewSummary:
    """Aggregate daily summaries into a weekly review."""
    ws = WeeklyReviewSummary(week=week_label)

    if not daily_summaries:
        return ws

    ws.total_trades = sum(d.trades_opened for d in daily_summaries)
    ws.weekly_pnl = sum(d.daily_pnl for d in daily_summaries)
    ws.max_drawdown_pct = max(d.drawdown_pct for d in daily_summaries) if daily_summaries else 0.0
    ws.daily_summaries = daily_summaries

    # Drift detection: check if later days diverge significantly from earlier days
    if len(daily_summaries) >= 3:
        first_half = daily_summaries[:len(daily_summaries) // 2]
        second_half = daily_summaries[len(daily_summaries) // 2:]
        avg_first = sum(d.daily_pnl for d in first_half) / max(1, len(first_half))
        avg_second = sum(d.daily_pnl for d in second_half) / max(1, len(second_half))
        if abs(avg_first) > 0:
            drift_ratio = abs(avg_second - avg_first) / abs(avg_first)
            ws.drift_detected = drift_ratio > 2.0

    for d in daily_summaries:
        ws.incidents.extend(d.incidents)

    return ws


def evaluate_paper_stage(
    candidate_label: str,
    weekly_summaries: list[WeeklyReviewSummary],
    reconciliation_pnl_diff_pct: float = 0.0,
    min_weeks: int = 2,
    min_trades: int = 20,
    max_discrepancy_pct: float = 5.0,
    max_drawdown_pct: float = 0.15,
    circuit_breaker_threshold: float = 0.15,
) -> PaperStageRecommendation:
    """Evaluate paper trading results and produce a promotion recommendation."""
    rec = PaperStageRecommendation(
        candidate_label=candidate_label,
        weekly_summaries=weekly_summaries,
        cumulative_discrepancy_pct=reconciliation_pnl_diff_pct,
    )

    total_trades = sum(w.total_trades for w in weekly_summaries)
    n_weeks = len(weekly_summaries)
    max_dd = max((w.max_drawdown_pct for w in weekly_summaries), default=0.0)
    any_drift = any(w.drift_detected for w in weekly_summaries)
    all_incidents = []
    for w in weekly_summaries:
        all_incidents.extend(w.incidents)

    # Check for circuit breaker firing across daily summaries
    cb_fired = False
    max_peak_dd = 0.0
    for w in weekly_summaries:
        for d in w.daily_summaries:
            max_peak_dd = max(max_peak_dd, d.peak_to_trough_dd)
            if d.operational_state == "stopped":
                cb_fired = True

    # Build checklist
    cl = PaperReviewChecklist()
    cl.trade_volume_adequate = total_trades >= min_trades
    cl.no_system_errors = not any("ERROR" in i.upper() for i in all_incidents)
    cl.discrepancy_within_threshold = abs(reconciliation_pnl_diff_pct) <= max_discrepancy_pct
    cl.no_behavioral_drift = not any_drift
    cl.drawdown_within_limits = max_dd <= max_drawdown_pct
    cl.no_blocking_incidents = not any("BLOCK" in i.upper() for i in all_incidents)
    cl.circuit_breaker_not_fired = not cb_fired
    cl.risk_profile_compliant = max_peak_dd < circuit_breaker_threshold
    rec.checklist = cl

    # Determine status
    if n_weeks < min_weeks:
        rec.status = PaperStageStatus.IN_PROGRESS
        rec.recommendation = f"Need at least {min_weeks} weeks of paper data (have {n_weeks})"
    elif cl.all_pass:
        rec.status = PaperStageStatus.PASS
        rec.recommendation = (
            f"Paper stage PASS: {total_trades} trades over {n_weeks} weeks, "
            f"discrepancy {reconciliation_pnl_diff_pct:.1f}%, no blocking issues."
        )
    elif cl.n_failures <= 2 and cl.no_system_errors:
        rec.status = PaperStageStatus.CONDITIONAL
        failures = []
        if not cl.trade_volume_adequate:
            failures.append(f"low volume ({total_trades} trades)")
        if not cl.discrepancy_within_threshold:
            failures.append(f"discrepancy {reconciliation_pnl_diff_pct:.1f}%")
        if not cl.no_behavioral_drift:
            failures.append("behavioral drift detected")
        if not cl.drawdown_within_limits:
            failures.append(f"drawdown {max_dd:.2%}")
        rec.recommendation = f"CONDITIONAL: minor issues ({', '.join(failures)}), review before promoting"
        rec.blocking_issues = failures
    else:
        rec.status = PaperStageStatus.FAIL
        rec.recommendation = f"FAIL: {cl.n_failures} checklist failures"
        if not cl.no_system_errors:
            rec.blocking_issues.append("System errors detected in paper run")
        if not cl.discrepancy_within_threshold:
            rec.blocking_issues.append(f"Discrepancy {reconciliation_pnl_diff_pct:.1f}% too high")

    return rec


def format_paper_review(rec: PaperStageRecommendation) -> str:
    """Format paper review as markdown."""
    lines = [
        "# Paper Trading Review",
        "",
        f"**Candidate**: {rec.candidate_label}",
        f"**Status**: {rec.status.value.upper()}",
        f"**Weeks reviewed**: {len(rec.weekly_summaries)}",
        f"**Cumulative discrepancy**: {rec.cumulative_discrepancy_pct:.1f}%",
        "",
        f"**Recommendation**: {rec.recommendation}",
        "",
        "## Review Checklist",
        "",
    ]

    cl = rec.checklist
    _check = lambda v: "PASS" if v else "FAIL"
    lines.append(f"- Trade volume adequate: {_check(cl.trade_volume_adequate)}")
    lines.append(f"- No system errors: {_check(cl.no_system_errors)}")
    lines.append(f"- Discrepancy within threshold: {_check(cl.discrepancy_within_threshold)}")
    lines.append(f"- No behavioral drift: {_check(cl.no_behavioral_drift)}")
    lines.append(f"- Drawdown within limits: {_check(cl.drawdown_within_limits)}")
    lines.append(f"- No blocking incidents: {_check(cl.no_blocking_incidents)}")
    lines.append(f"- Circuit breaker not fired: {_check(cl.circuit_breaker_not_fired)}")
    lines.append(f"- Risk profile compliant: {_check(cl.risk_profile_compliant)}")

    if rec.blocking_issues:
        lines.append("")
        lines.append("## Blocking Issues")
        lines.append("")
        for issue in rec.blocking_issues:
            lines.append(f"- {issue}")

    if rec.weekly_summaries:
        lines.append("")
        lines.append("## Weekly Summaries")
        lines.append("")
        lines.append("| Week | Trades | PnL | Max DD | Drift | Incidents |")
        lines.append("|------|--------|-----|--------|-------|-----------|")
        for w in rec.weekly_summaries:
            lines.append(
                f"| {w.week} | {w.total_trades} | {w.weekly_pnl:,.0f} | "
                f"{w.max_drawdown_pct:.2%} | {'YES' if w.drift_detected else 'no'} | "
                f"{len(w.incidents)} |"
            )

    return "\n".join(lines)
