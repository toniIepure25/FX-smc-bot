"""Config-driven experiment runner.

Loads a YAML config, runs a backtest, and saves results with full
reproducibility metadata. Integrates with the experiment registry
and auto-saves structured artifacts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult
from fx_smc_bot.research.registry import ExperimentRegistry
from fx_smc_bot.research.reporting import save_run_artifacts

logger = logging.getLogger(__name__)


def load_config(path: Path | str) -> AppConfig:
    """Load an AppConfig from a YAML file."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw) if raw else AppConfig()


def run_experiment(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> tuple[BacktestResult, PerformanceSummary]:
    """Run a single experiment and return results + metrics."""
    engine = BacktestEngine(config)
    result = engine.run(data, htf_data)
    metrics = engine.metrics(result)
    return result, metrics


def run_registered_experiment(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
    label: str = "experiment",
    output_dir: Path | str = "results",
    registry_path: Path | str | None = None,
    tags: list[str] | None = None,
    notes: str = "",
) -> tuple[BacktestResult, PerformanceSummary, Path]:
    """Run an experiment with full registry tracking and artifact saving.

    Returns (result, metrics, artifact_directory).
    """
    output_dir = Path(output_dir)
    config_dict = config.model_dump()

    registry = None
    run_record = None
    if registry_path:
        registry = ExperimentRegistry(registry_path)
        run_record = registry.create_run(label, config_dict, tags=tags, notes=notes)

    start_time = time_module.time()
    try:
        result, metrics = run_experiment(config, data, htf_data)
        elapsed = time_module.time() - start_time

        artifact_dir = save_run_artifacts(
            result, metrics, output_dir,
            config_dict=config_dict, label=label,
        )

        if registry and run_record:
            metrics_dict = {k: v for k, v in vars(metrics).items() if not k.startswith("_")}
            registry.complete_run(
                run_record.run_id, metrics_dict,
                artifact_dir=str(artifact_dir),
                duration_seconds=elapsed,
            )

        return result, metrics, artifact_dir

    except Exception as e:
        if registry and run_record:
            registry.fail_run(run_record.run_id, str(e))
        raise


def save_experiment(
    result: BacktestResult,
    metrics: PerformanceSummary,
    output_dir: Path | str,
    label: str = "",
    config_dict: dict[str, Any] | None = None,
) -> Path:
    """Save experiment results to a timestamped directory (legacy + enhanced)."""
    return save_run_artifacts(result, metrics, output_dir,
                              config_dict=config_dict, label=label)
