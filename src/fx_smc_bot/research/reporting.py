"""Report generation: format backtest results for display and export.

Supports plain-text summary, CSV trade ledger, markdown reports,
structured JSON artifacts, and full run artifact orchestration.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.backtesting.attribution import (
    AttributionSlice,
    by_direction,
    by_family,
    by_month,
    by_pair,
    by_session,
    by_year,
)
from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.domain import BacktestResult, ClosedTrade

logger = logging.getLogger(__name__)


def summary_report(
    result: BacktestResult,
    metrics: PerformanceSummary,
) -> str:
    """Generate a human-readable performance summary."""
    lines = [
        "=" * 60,
        "BACKTEST SUMMARY",
        "=" * 60,
        f"Period:          {result.start_date} -> {result.end_date}",
        f"Initial Capital: {result.initial_capital:,.2f}",
        f"Final Equity:    {result.final_equity:,.2f}",
        f"Total PnL:       {metrics.total_pnl:,.2f}",
        "",
        f"Total Trades:    {metrics.total_trades}",
        f"Win Rate:        {metrics.win_rate:.1%}",
        f"Profit Factor:   {metrics.profit_factor:.2f}",
        f"Expectancy:      {metrics.expectancy:,.2f}",
        f"Avg RR:          {metrics.avg_rr_ratio:.2f}",
        "",
        f"Sharpe Ratio:    {metrics.sharpe_ratio:.3f}",
        f"Sortino Ratio:   {metrics.sortino_ratio:.3f}",
        f"Calmar Ratio:    {metrics.calmar_ratio:.3f}",
        f"Max Drawdown:    {metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct:.1%})",
        "",
    ]

    if result.trades:
        lines.append("--- BY PAIR ---")
        for s in by_pair(result.trades):
            lines.append(f"  {s.label:12s}  trades={s.trade_count:3d}  "
                         f"pnl={s.total_pnl:>10,.2f}  wr={s.win_rate:.1%}")

        lines.append("")
        lines.append("--- BY FAMILY ---")
        for s in by_family(result.trades):
            lines.append(f"  {s.label:24s}  trades={s.trade_count:3d}  "
                         f"pnl={s.total_pnl:>10,.2f}  wr={s.win_rate:.1%}")

        lines.append("")
        lines.append("--- BY YEAR ---")
        for s in by_year(result.trades):
            lines.append(f"  {s.label:12s}  trades={s.trade_count:3d}  "
                         f"pnl={s.total_pnl:>10,.2f}  wr={s.win_rate:.1%}")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSV trade ledger
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "trade_id", "pair", "direction", "family", "entry_price", "exit_price",
    "units", "pnl", "pnl_pips", "opened_at", "closed_at", "duration_bars",
    "reward_risk_ratio", "session", "tags",
]


def save_csv_ledger(trades: list[ClosedTrade], path: Path | str) -> Path:
    """Save full trade ledger as CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for i, t in enumerate(trades):
            writer.writerow({
                "trade_id": i + 1,
                "pair": t.pair.value,
                "direction": t.direction.value,
                "family": t.family.value,
                "entry_price": round(t.entry_price, 6),
                "exit_price": round(t.exit_price, 6),
                "units": round(t.units, 2),
                "pnl": round(t.pnl, 2),
                "pnl_pips": round(t.pnl_pips, 2),
                "opened_at": str(t.opened_at),
                "closed_at": str(t.closed_at),
                "duration_bars": t.duration_bars,
                "reward_risk_ratio": round(t.reward_risk_ratio, 3),
                "session": t.session.value if t.session else "",
                "tags": ";".join(t.tags),
            })
    logger.info("Trade ledger saved to %s (%d trades)", path, len(trades))
    return path


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def save_markdown_report(
    result: BacktestResult,
    metrics: PerformanceSummary,
    config_dict: dict[str, Any] | None = None,
    path: Path | str = "report.md",
) -> Path:
    """Generate and save a formatted Markdown report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Backtest Report")
    lines.append("")
    lines.append(f"**Period:** {result.start_date} to {result.end_date}")
    lines.append(f"**Generated:** {datetime.utcnow().isoformat()}")
    lines.append("")

    lines.append("## Performance Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Initial Capital | {result.initial_capital:,.2f} |")
    lines.append(f"| Final Equity | {result.final_equity:,.2f} |")
    lines.append(f"| Total PnL | {metrics.total_pnl:,.2f} |")
    lines.append(f"| Total Trades | {metrics.total_trades} |")
    lines.append(f"| Win Rate | {metrics.win_rate:.1%} |")
    lines.append(f"| Profit Factor | {metrics.profit_factor:.2f} |")
    lines.append(f"| Sharpe Ratio | {metrics.sharpe_ratio:.3f} |")
    lines.append(f"| Sortino Ratio | {metrics.sortino_ratio:.3f} |")
    lines.append(f"| Calmar Ratio | {metrics.calmar_ratio:.3f} |")
    lines.append(f"| Max Drawdown | {metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct:.1%}) |")
    lines.append(f"| Expectancy | {metrics.expectancy:,.2f} |")
    lines.append(f"| Avg R:R | {metrics.avg_rr_ratio:.2f} |")
    lines.append(f"| Annualized Return | {metrics.annualized_return:.1%} |")
    lines.append("")

    if result.trades:
        lines.append("## Attribution")
        lines.append("")
        _add_attribution_table(lines, "By Pair", by_pair(result.trades))
        _add_attribution_table(lines, "By Family", by_family(result.trades))
        _add_attribution_table(lines, "By Year", by_year(result.trades))
        _add_attribution_table(lines, "By Session", by_session(result.trades))
        _add_attribution_table(lines, "By Direction", by_direction(result.trades))

    if config_dict:
        lines.append("## Configuration")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(config_dict, indent=2, default=str))
        lines.append("```")
        lines.append("")

    # Deployment gate results section
    if gate_result := (config_dict or {}).get("__gate_result"):
        lines.append("## Deployment Gate Evaluation")
        lines.append("")
        lines.append(f"**Verdict:** {gate_result.get('verdict', 'N/A')}")
        lines.append(f"**Recommendation:** {gate_result.get('recommendation', '')}")
        lines.append("")
        if gate_result.get("criteria"):
            lines.append("| Criterion | Threshold | Actual | Passed | Severity |")
            lines.append("|-----------|-----------|--------|--------|----------|")
            for c in gate_result["criteria"]:
                lines.append(f"| {c['name']} | {c['threshold']} | {c['actual']} | "
                             f"{'PASS' if c['passed'] else 'FAIL'} | {c['severity']} |")
            lines.append("")

    # Warning flags
    warning_flags = _compute_warning_flags(result, metrics)
    if warning_flags:
        lines.append("## Warning Flags")
        lines.append("")
        for flag in warning_flags:
            lines.append(f"- {flag}")
        lines.append("")

    content = "\n".join(lines)
    path.write_text(content)
    logger.info("Markdown report saved to %s", path)
    return path


def _compute_warning_flags(result: BacktestResult, metrics: PerformanceSummary) -> list[str]:
    """Generate warning flags for common issues."""
    flags: list[str] = []
    if metrics.total_trades < 30:
        flags.append(f"LOW_TRADE_COUNT: only {metrics.total_trades} trades (minimum 30 for statistical significance)")
    if metrics.max_drawdown_pct > 0.25:
        flags.append(f"HIGH_DRAWDOWN: {metrics.max_drawdown_pct:.1%} max drawdown exceeds 25% threshold")
    if metrics.win_rate < 0.30:
        flags.append(f"LOW_WIN_RATE: {metrics.win_rate:.1%} is below 30% floor")
    if metrics.profit_factor < 1.0:
        flags.append(f"NEGATIVE_EDGE: profit factor {metrics.profit_factor:.2f} < 1.0 (net losing strategy)")

    # Check for overconcentration in any one pair
    if result.trades:
        pair_counts: dict[str, int] = {}
        for t in result.trades:
            pair_counts[t.pair.value] = pair_counts.get(t.pair.value, 0) + 1
        max_pct = max(pair_counts.values()) / len(result.trades) if result.trades else 0
        if max_pct > 0.7:
            top_pair = max(pair_counts, key=pair_counts.get)  # type: ignore[arg-type]
            flags.append(f"OVERCONCENTRATION: {max_pct:.0%} of trades on {top_pair}")

    # Check for poor OOS pattern (declining yearly performance)
    if result.trades:
        yearly_pnl: dict[str, float] = {}
        for t in result.trades:
            yr = str(t.closed_at.year) if t.closed_at else "unknown"
            yearly_pnl[yr] = yearly_pnl.get(yr, 0.0) + t.pnl
        years = sorted(yearly_pnl.keys())
        if len(years) >= 2 and yearly_pnl[years[-1]] < yearly_pnl[years[-2]] * 0.3:
            flags.append("PERFORMANCE_DECAY: last year significantly worse than prior year")

    return flags


def _add_attribution_table(lines: list[str], title: str, slices: list[AttributionSlice]) -> None:
    lines.append(f"### {title}")
    lines.append("")
    lines.append("| Label | Trades | PnL | Win Rate | Avg PnL | Avg R:R |")
    lines.append("|-------|--------|-----|----------|---------|---------|")
    for s in slices:
        lines.append(
            f"| {s.label} | {s.trade_count} | {s.total_pnl:,.2f} | "
            f"{s.win_rate:.1%} | {s.avg_pnl:,.2f} | {s.avg_rr:.2f} |"
        )
    lines.append("")


# ---------------------------------------------------------------------------
# Full run artifact orchestrator
# ---------------------------------------------------------------------------

def save_run_artifacts(
    result: BacktestResult,
    metrics: PerformanceSummary,
    output_dir: Path | str,
    config_dict: dict[str, Any] | None = None,
    label: str = "",
) -> Path:
    """Save all experiment artifacts to a structured directory.

    Creates:
      <output_dir>/
        config.json
        metrics.json
        trades.csv
        equity_curve.csv
        attribution.json
        report.md
    """
    output_dir = Path(output_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_name = f"{label}_{timestamp}" if label else timestamp
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # Config
    if config_dict:
        with open(run_dir / "config.json", "w") as f:
            json.dump(config_dict, f, indent=2, default=str)

    # Metrics
    metrics_dict = {k: v for k, v in vars(metrics).items() if not k.startswith("_")}
    with open(run_dir / "metrics.json", "w") as f:
        json.dump(metrics_dict, f, indent=2, default=str)

    # Trade ledger
    if result.trades:
        save_csv_ledger(result.trades, run_dir / "trades.csv")

    # Equity curve
    if result.equity_curve:
        with open(run_dir / "equity_curve.csv", "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "equity", "cash", "unrealized_pnl",
                               "drawdown", "drawdown_pct"],
            )
            writer.writeheader()
            for ep in result.equity_curve:
                writer.writerow({
                    "timestamp": str(ep.timestamp),
                    "equity": round(ep.equity, 2),
                    "cash": round(ep.cash, 2),
                    "unrealized_pnl": round(ep.unrealized_pnl, 2),
                    "drawdown": round(ep.drawdown, 2),
                    "drawdown_pct": round(ep.drawdown_pct, 4),
                })

    # Attribution summary
    if result.trades:
        attr = {
            "by_pair": [_slice_dict(s) for s in by_pair(result.trades)],
            "by_family": [_slice_dict(s) for s in by_family(result.trades)],
            "by_year": [_slice_dict(s) for s in by_year(result.trades)],
            "by_session": [_slice_dict(s) for s in by_session(result.trades)],
            "by_direction": [_slice_dict(s) for s in by_direction(result.trades)],
        }
        with open(run_dir / "attribution.json", "w") as f:
            json.dump(attr, f, indent=2)

    # Markdown report
    save_markdown_report(result, metrics, config_dict, run_dir / "report.md")

    logger.info("All artifacts saved to %s", run_dir)
    return run_dir


def _slice_dict(s: AttributionSlice) -> dict[str, Any]:
    return {
        "label": s.label, "trade_count": s.trade_count,
        "total_pnl": round(s.total_pnl, 2), "win_rate": round(s.win_rate, 3),
        "avg_pnl": round(s.avg_pnl, 2), "avg_rr": round(s.avg_rr, 3),
    }
