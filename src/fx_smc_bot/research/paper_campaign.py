"""Paper trading campaign: structured multi-session paper replay.

Runs a frozen candidate through the paper trading runner, then
reconciles against a matching backtest to measure discrepancies
and produce a go/no-go recommendation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.research.frozen_config import FrozenCandidate, split_data, validate_frozen
from fx_smc_bot.research.reconciliation import (
    ReconciliationReport,
    format_reconciliation_report,
    reconcile_paper_vs_backtest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PaperCampaignConfig:
    candidate: FrozenCandidate
    data_slice: str = "holdout"
    max_discrepancy_pct: float = 5.0
    daily_summary: bool = True


@dataclass(slots=True)
class PaperCampaignResult:
    run_id: str = ""
    candidate_label: str = ""
    final_equity: float = 0.0
    total_trades: int = 0
    reconciliation: ReconciliationReport | None = None
    daily_summaries: list[dict[str, Any]] = field(default_factory=list)
    health_snapshots: list[dict[str, Any]] = field(default_factory=list)
    go_no_go: str = "no_go"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "candidate_label": self.candidate_label,
            "final_equity": round(self.final_equity, 2),
            "total_trades": self.total_trades,
            "go_no_go": self.go_no_go,
            "notes": self.notes,
        }
        if self.reconciliation:
            d["reconciliation"] = self.reconciliation.to_dict()
        return d


def run_paper_campaign(
    config: PaperCampaignConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
    output_dir: Path | str = Path("paper_campaigns"),
) -> PaperCampaignResult:
    """Execute a paper campaign with reconciliation and go/no-go."""
    output_dir = Path(output_dir)

    result = PaperCampaignResult(
        candidate_label=config.candidate.label,
    )

    if not validate_frozen(config.candidate):
        result.notes.append("ABORT: frozen config hash mismatch -- config was mutated")
        return result

    # Select the data slice
    if config.data_slice == "holdout":
        _, _, slice_data = split_data(data, config.candidate.data_split)
    elif config.data_slice == "validation":
        _, slice_data, _ = split_data(data, config.candidate.data_split)
    else:
        slice_data = data

    has_data = any(len(s) > 20 for s in slice_data.values())
    if not has_data:
        result.notes.append(f"ABORT: insufficient data in '{config.data_slice}' slice")
        return result

    # Run paper trading
    runner = PaperTradingRunner(config.candidate.config, output_dir=output_dir)
    try:
        final_state = runner.run(slice_data, htf_data)
        result.run_id = runner._run_id
        result.final_equity = final_state.equity

        # Read journal events
        journal_path = output_dir / runner._run_id / "journal.jsonl"
        if journal_path.exists():
            fills = []
            daily = []
            with open(journal_path) as f:
                for line in f:
                    evt = json.loads(line)
                    if evt.get("event_type") == "fill":
                        fills.append(evt)
                    elif evt.get("event_type") == "daily_summary":
                        daily.append(evt)
            result.total_trades = len(fills)
            result.daily_summaries = daily

    except Exception as e:
        logger.error("Paper campaign failed for %s: %s", config.candidate.label, e)
        result.notes.append(f"PAPER_RUN_ERROR: {e}")
        return result

    # Run matching backtest for reconciliation
    try:
        engine = BacktestEngine(config.candidate.config)
        bt_result = engine.run(slice_data, htf_data)

        journal_path = output_dir / runner._run_id / "journal.jsonl"
        if journal_path.exists():
            result.reconciliation = reconcile_paper_vs_backtest(
                bt_result, journal_path, paper_final_equity=result.final_equity,
            )

    except Exception as e:
        logger.warning("Reconciliation backtest failed: %s", e)
        result.notes.append(f"RECONCILIATION_ERROR: {e}")

    # Go/no-go based on discrepancy threshold
    if result.reconciliation:
        if abs(result.reconciliation.pnl_diff_pct) <= config.max_discrepancy_pct:
            result.go_no_go = "go"
            result.notes.append(
                f"PnL discrepancy {result.reconciliation.pnl_diff_pct:.1f}% "
                f"within {config.max_discrepancy_pct}% threshold"
            )
        else:
            result.go_no_go = "no_go"
            result.notes.append(
                f"PnL discrepancy {result.reconciliation.pnl_diff_pct:.1f}% "
                f"exceeds {config.max_discrepancy_pct}% threshold"
            )

    return result


def format_paper_report(result: PaperCampaignResult) -> str:
    """Generate a markdown paper campaign report."""
    lines = [
        "# Paper Campaign Report",
        "",
        f"**Candidate**: {result.candidate_label}",
        f"**Run ID**: {result.run_id}",
        f"**Final Equity**: {result.final_equity:,.2f}",
        f"**Total Trades**: {result.total_trades}",
        f"**Go/No-Go**: {result.go_no_go.upper()}",
        "",
    ]

    if result.notes:
        lines.append("## Notes")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")

    if result.reconciliation:
        lines.append("## Reconciliation")
        lines.append("")
        lines.append(format_reconciliation_report(result.reconciliation))
        lines.append("")

    if result.daily_summaries:
        lines.append("## Daily Summaries")
        lines.append("")
        lines.append(f"| Day | Events |")
        lines.append("|-----|--------|")
        for ds in result.daily_summaries:
            day = ds.get("data", {}).get("date", "?")
            lines.append(f"| {day} | {json.dumps(ds.get('data', {}))} |")

    return "\n".join(lines)
