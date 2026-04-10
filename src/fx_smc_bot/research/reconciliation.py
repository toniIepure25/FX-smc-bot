"""Paper-vs-backtest reconciliation: compare execution paths.

Reads a backtest result and a paper trading journal to identify
discrepancies in trade counts, PnL, fill prices, and timing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fx_smc_bot.domain import BacktestResult, ClosedTrade
from fx_smc_bot.live.journal import EventJournal, JournalEvent


@dataclass(slots=True)
class ReconciliationReport:
    backtest_trade_count: int = 0
    paper_trade_count: int = 0
    trade_count_diff: int = 0
    backtest_pnl: float = 0.0
    paper_pnl: float = 0.0
    pnl_diff: float = 0.0
    pnl_diff_pct: float = 0.0
    backtest_equity: float = 0.0
    paper_equity: float = 0.0
    equity_diff: float = 0.0
    fill_price_discrepancies: list[dict[str, Any]] = field(default_factory=list)
    per_family: dict[str, dict[str, float]] = field(default_factory=dict)
    per_pair: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backtest_trades": self.backtest_trade_count,
            "paper_trades": self.paper_trade_count,
            "trade_count_diff": self.trade_count_diff,
            "backtest_pnl": round(self.backtest_pnl, 2),
            "paper_pnl": round(self.paper_pnl, 2),
            "pnl_diff": round(self.pnl_diff, 2),
            "pnl_diff_pct": round(self.pnl_diff_pct, 2),
            "equity_diff": round(self.equity_diff, 2),
            "fill_discrepancies": len(self.fill_price_discrepancies),
            "per_family": self.per_family,
            "per_pair": self.per_pair,
            "notes": self.notes,
        }


def reconcile_paper_vs_backtest(
    backtest_result: BacktestResult,
    paper_journal_path: Path | str,
    paper_final_equity: float | None = None,
) -> ReconciliationReport:
    """Compare backtest result against a paper trading journal.

    Reads the journal JSONL to extract paper fill/PnL events, then
    computes differences against the backtest result.
    """
    journal_path = Path(paper_journal_path)
    paper_events = _read_journal_events(journal_path)

    paper_fills = [e for e in paper_events if e.event_type == "fill"]
    paper_run_complete = [e for e in paper_events if e.event_type == "run_complete"]

    paper_trade_count = 0
    paper_pnl = 0.0
    p_equity = paper_final_equity or 0.0

    if paper_run_complete:
        last_complete = paper_run_complete[-1]
        paper_trade_count = last_complete.data.get("total_trades", len(paper_fills))
        paper_pnl = last_complete.data.get("total_pnl", 0.0)
        p_equity = last_complete.data.get("final_equity", p_equity)

    bt_pnl = sum(t.pnl for t in backtest_result.trades)

    report = ReconciliationReport(
        backtest_trade_count=len(backtest_result.trades),
        paper_trade_count=paper_trade_count,
        trade_count_diff=paper_trade_count - len(backtest_result.trades),
        backtest_pnl=bt_pnl,
        paper_pnl=paper_pnl,
        pnl_diff=paper_pnl - bt_pnl,
        pnl_diff_pct=((paper_pnl - bt_pnl) / abs(bt_pnl) * 100) if bt_pnl != 0 else 0.0,
        backtest_equity=backtest_result.final_equity,
        paper_equity=p_equity,
        equity_diff=p_equity - backtest_result.final_equity,
    )

    # Per-family comparison from backtest side
    family_bt: dict[str, float] = {}
    for t in backtest_result.trades:
        key = t.family.value
        family_bt[key] = family_bt.get(key, 0.0) + t.pnl
    report.per_family = {k: {"backtest_pnl": round(v, 2)} for k, v in family_bt.items()}

    # Per-pair comparison from backtest side
    pair_bt: dict[str, float] = {}
    for t in backtest_result.trades:
        key = t.pair.value
        pair_bt[key] = pair_bt.get(key, 0.0) + t.pnl
    report.per_pair = {k: {"backtest_pnl": round(v, 2)} for k, v in pair_bt.items()}

    # Notes
    if abs(report.trade_count_diff) > 0:
        report.notes.append(
            f"Trade count mismatch: backtest={report.backtest_trade_count}, paper={report.paper_trade_count}"
        )
    if abs(report.pnl_diff_pct) > 5.0:
        report.notes.append(f"PnL divergence of {report.pnl_diff_pct:.1f}% exceeds 5% threshold")

    return report


def format_reconciliation_report(report: ReconciliationReport) -> str:
    """Format reconciliation report as markdown."""
    lines = [
        "# Paper vs Backtest Reconciliation",
        "",
        "| Metric | Backtest | Paper | Diff |",
        "|--------|----------|-------|------|",
        f"| Trades | {report.backtest_trade_count} | {report.paper_trade_count} | {report.trade_count_diff} |",
        f"| PnL | {report.backtest_pnl:,.2f} | {report.paper_pnl:,.2f} | {report.pnl_diff:,.2f} ({report.pnl_diff_pct:+.1f}%) |",
        f"| Final Equity | {report.backtest_equity:,.2f} | {report.paper_equity:,.2f} | {report.equity_diff:,.2f} |",
        "",
    ]

    if report.per_family:
        lines.append("## Per Family")
        lines.append("")
        lines.append("| Family | Backtest PnL |")
        lines.append("|--------|-------------|")
        for fam, data in sorted(report.per_family.items()):
            lines.append(f"| {fam} | {data.get('backtest_pnl', 0):,.2f} |")
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def _read_journal_events(path: Path) -> list[JournalEvent]:
    if not path.exists():
        return []
    events: list[JournalEvent] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(JournalEvent.from_json(line))
    return events
