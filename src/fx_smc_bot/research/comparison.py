"""Experiment comparison: load and compare results from multiple runs.

Provides side-by-side metric comparison tables for quantitative assessment
of strategy variants, parameter changes, or execution model differences.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Lightweight summary of an experiment run for comparison."""
    run_id: str
    label: str
    metrics: dict[str, Any]
    config: dict[str, Any]


def load_run_snapshot(artifact_dir: Path | str) -> RunSnapshot:
    """Load a run snapshot from an artifact directory."""
    artifact_dir = Path(artifact_dir)
    metrics_path = artifact_dir / "metrics.json"
    config_path = artifact_dir / "config.json"

    metrics = {}
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)

    return RunSnapshot(
        run_id=artifact_dir.name,
        label=artifact_dir.name,
        metrics=metrics,
        config=config,
    )


_COMPARISON_METRICS = [
    ("total_trades", "Total Trades", "d"),
    ("win_rate", "Win Rate", ".1%"),
    ("profit_factor", "Profit Factor", ".2f"),
    ("sharpe_ratio", "Sharpe Ratio", ".3f"),
    ("sortino_ratio", "Sortino Ratio", ".3f"),
    ("calmar_ratio", "Calmar Ratio", ".3f"),
    ("max_drawdown_pct", "Max DD %", ".1%"),
    ("total_pnl", "Total PnL", ",.2f"),
    ("expectancy", "Expectancy", ",.2f"),
    ("avg_rr_ratio", "Avg R:R", ".2f"),
    ("annualized_return", "Ann. Return", ".1%"),
]


def compare_runs(runs: list[RunSnapshot]) -> str:
    """Generate a formatted comparison table of multiple runs."""
    if not runs:
        return "No runs to compare."

    # Header
    col_width = max(16, max(len(r.label) for r in runs) + 2)
    header = f"{'Metric':<20s}"
    for r in runs:
        header += f"  {r.label:>{col_width}s}"
    lines = [header, "-" * len(header)]

    for key, label, fmt in _COMPARISON_METRICS:
        row = f"{label:<20s}"
        for r in runs:
            val = r.metrics.get(key, "N/A")
            if val == "N/A" or val is None:
                row += f"  {'N/A':>{col_width}s}"
            else:
                try:
                    if fmt == "d":
                        row += f"  {int(val):>{col_width}d}"
                    elif fmt.endswith("%"):
                        row += f"  {float(val):>{col_width}{fmt}}"
                    else:
                        row += f"  {float(val):>{col_width}{fmt}}"
                except (ValueError, TypeError):
                    row += f"  {str(val):>{col_width}s}"
        lines.append(row)

    return "\n".join(lines)


def compare_configs(runs: list[RunSnapshot]) -> str:
    """Show configuration differences between runs."""
    if len(runs) < 2:
        return "Need at least 2 runs to compare configs."

    all_keys: set[str] = set()
    flat_configs: list[dict[str, Any]] = []
    for r in runs:
        flat = _flatten_dict(r.config)
        flat_configs.append(flat)
        all_keys.update(flat.keys())

    diffs: list[tuple[str, list[Any]]] = []
    for key in sorted(all_keys):
        values = [fc.get(key, "N/A") for fc in flat_configs]
        if len(set(str(v) for v in values)) > 1:
            diffs.append((key, values))

    if not diffs:
        return "All configs are identical."

    lines = [f"{'Config Key':<40s}" + "  ".join(f"{r.label:>16s}" for r in runs)]
    lines.append("-" * len(lines[0]))
    for key, values in diffs:
        row = f"{key:<40s}" + "  ".join(f"{str(v):>16s}" for v in values)
        lines.append(row)

    return "\n".join(lines)


def _flatten_dict(d: dict, prefix: str = "") -> dict[str, Any]:
    items: dict[str, Any] = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key))
        else:
            items[new_key] = v
    return items
