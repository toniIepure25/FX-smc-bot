"""Regression tests for run artifact export."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from fx_smc_bot.backtesting.metrics import compute_metrics
from fx_smc_bot.domain import BacktestResult
from fx_smc_bot.research.reporting import save_run_artifacts


def test_save_run_artifacts_handles_slots_metrics(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1)
    result = BacktestResult(
        config_hash="test",
        start_date=start,
        end_date=start + timedelta(days=1),
        initial_capital=100_000.0,
        final_equity=100_000.0,
    )
    metrics = compute_metrics([], [])

    run_dir = save_run_artifacts(result, metrics, tmp_path, label="slots")

    payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert payload["total_trades"] == 0
    assert (run_dir / "report.md").exists()
