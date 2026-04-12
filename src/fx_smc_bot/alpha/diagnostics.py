"""Detector diagnostics: signal funnel tracking, rejection analysis, and reports.

Instruments the alpha generation pipeline to track where signals are
created, filtered, and why families produce zero or few trades.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class FamilyFunnel:
    """Per-family signal funnel counters."""
    scans: int = 0
    raw_signals: int = 0
    after_filters: int = 0
    orders_placed: int = 0
    trades_filled: int = 0

    # Rejection breakdown
    no_htf_bias: int = 0
    no_swept_levels: int = 0
    no_entry_zone: int = 0
    no_bos_breaks: int = 0
    regime_filtered: int = 0
    score_too_low: int = 0
    rr_too_low: int = 0
    risk_distance_zero: int = 0


@dataclass
class DetectorDiagnostics:
    """Aggregates signal funnel data across a full backtest run."""

    family_funnels: dict[str, FamilyFunnel] = field(
        default_factory=lambda: defaultdict(FamilyFunnel)
    )
    pair_signals: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    session_signals: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    def record_scan(self, family: str) -> None:
        self.family_funnels[family].scans += 1

    def record_raw_signal(self, family: str, pair: str, session: str | None = None) -> None:
        self.family_funnels[family].raw_signals += 1
        self.pair_signals[family][pair] += 1
        if session:
            self.session_signals[family][session] += 1

    def record_filter_pass(self, family: str) -> None:
        self.family_funnels[family].after_filters += 1

    def record_rejection(self, family: str, reason: str) -> None:
        f = self.family_funnels[family]
        attr = reason.replace(" ", "_").replace("-", "_")
        if hasattr(f, attr):
            setattr(f, attr, getattr(f, attr) + 1)

    def record_order(self, family: str) -> None:
        self.family_funnels[family].orders_placed += 1

    def record_fill(self, family: str) -> None:
        self.family_funnels[family].trades_filled += 1

    def merge(self, other: DetectorDiagnostics) -> None:
        for fam, funnel in other.family_funnels.items():
            mine = self.family_funnels[fam]
            for attr in FamilyFunnel.__slots__:
                setattr(mine, attr, getattr(mine, attr) + getattr(funnel, attr))
        for fam, pairs in other.pair_signals.items():
            for pair, count in pairs.items():
                self.pair_signals[fam][pair] += count
        for fam, sessions in other.session_signals.items():
            for sess, count in sessions.items():
                self.session_signals[fam][sess] += count


def format_detector_diagnostics(diag: DetectorDiagnostics) -> str:
    """Generate a markdown detector diagnostics report."""
    lines = ["# Detector Diagnostics Report", ""]

    # Signal funnel table
    lines.append("## Signal Funnel by Family")
    lines.append("")
    lines.append("| Family | Scans | Raw Signals | After Filters | Orders | Trades | Conversion |")
    lines.append("|--------|-------|-------------|---------------|--------|--------|------------|")
    for fam in sorted(diag.family_funnels.keys()):
        f = diag.family_funnels[fam]
        conv = f"{f.trades_filled / f.scans:.2%}" if f.scans > 0 else "0.00%"
        lines.append(
            f"| {fam} | {f.scans:,d} | {f.raw_signals:,d} | {f.after_filters:,d} | "
            f"{f.orders_placed:,d} | {f.trades_filled:,d} | {conv} |"
        )

    # Rejection breakdown
    lines.append("")
    lines.append("## Rejection Breakdown")
    lines.append("")
    rejection_fields = [
        "no_htf_bias", "no_swept_levels", "no_entry_zone", "no_bos_breaks",
        "regime_filtered", "score_too_low", "rr_too_low", "risk_distance_zero",
    ]
    header = "| Family | " + " | ".join(f.replace("_", " ").title() for f in rejection_fields) + " |"
    sep = "|--------|" + "|".join("---" for _ in rejection_fields) + "|"
    lines.append(header)
    lines.append(sep)
    for fam in sorted(diag.family_funnels.keys()):
        f = diag.family_funnels[fam]
        vals = " | ".join(str(getattr(f, attr)) for attr in rejection_fields)
        lines.append(f"| {fam} | {vals} |")

    # Per-pair signal distribution
    lines.append("")
    lines.append("## Signals by Pair")
    lines.append("")
    all_pairs = sorted({p for pairs in diag.pair_signals.values() for p in pairs})
    if all_pairs:
        header = "| Family | " + " | ".join(all_pairs) + " | Total |"
        sep = "|--------|" + "|".join("---" for _ in all_pairs) + "|-------|"
        lines.append(header)
        lines.append(sep)
        for fam in sorted(diag.pair_signals.keys()):
            counts = [str(diag.pair_signals[fam].get(p, 0)) for p in all_pairs]
            total = sum(diag.pair_signals[fam].values())
            lines.append(f"| {fam} | {' | '.join(counts)} | {total} |")

    # Per-session signal distribution
    lines.append("")
    lines.append("## Signals by Session")
    lines.append("")
    all_sessions = sorted({s for sessions in diag.session_signals.values() for s in sessions})
    if all_sessions:
        header = "| Family | " + " | ".join(all_sessions) + " |"
        sep = "|--------|" + "|".join("---" for _ in all_sessions) + "|"
        lines.append(header)
        lines.append(sep)
        for fam in sorted(diag.session_signals.keys()):
            counts = [str(diag.session_signals[fam].get(s, 0)) for s in all_sessions]
            lines.append(f"| {fam} | {' | '.join(counts)} |")

    # Inactive family warnings
    lines.append("")
    lines.append("## Inactive / Weak Family Alerts")
    lines.append("")
    for fam in sorted(diag.family_funnels.keys()):
        f = diag.family_funnels[fam]
        if f.raw_signals == 0:
            lines.append(f"- **{fam}**: INACTIVE — zero raw signals from {f.scans:,d} scans")
            if f.no_htf_bias > 0:
                lines.append(f"  - {f.no_htf_bias:,d} rejections due to no HTF bias")
            if f.no_swept_levels > 0:
                lines.append(f"  - {f.no_swept_levels:,d} rejections due to no swept levels")
            if f.no_entry_zone > 0:
                lines.append(f"  - {f.no_entry_zone:,d} rejections due to no entry zone")
            if f.no_bos_breaks > 0:
                lines.append(f"  - {f.no_bos_breaks:,d} rejections due to no BOS breaks")
        elif f.trades_filled == 0:
            lines.append(
                f"- **{fam}**: {f.raw_signals} signals generated but 0 trades filled "
                f"(filtered: score={f.score_too_low}, rr={f.rr_too_low})"
            )

    return "\n".join(lines)
