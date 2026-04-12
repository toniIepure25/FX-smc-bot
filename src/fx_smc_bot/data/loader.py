"""Unified data loader for validation campaigns.

Auto-detects CSV or Parquet files in the data directory and loads all
available pairs at the primary execution timeframe. Optionally generates
HTF context data via resampling.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.providers.csv_provider import CsvProvider
from fx_smc_bot.data.providers.parquet_provider import ParquetProvider

logger = logging.getLogger(__name__)

_EXEC_TF_PRIORITY = [Timeframe.M15, Timeframe.M5, Timeframe.H1, Timeframe.H4]


def _get_provider(data_dir: Path):
    has_parquet = any(data_dir.rglob("*.parquet"))
    has_csv = any(data_dir.rglob("*.csv"))
    if has_parquet:
        return ParquetProvider(data_dir)
    if has_csv:
        return CsvProvider(data_dir)
    return None


def load_pair_data(
    data_dir: Path | str,
    pairs: list[TradingPair] | None = None,
    timeframe: Timeframe | None = None,
) -> dict[TradingPair, BarSeries]:
    """Load execution-timeframe data for all available pairs."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        logger.error("Data directory does not exist: %s", data_dir)
        return {}

    provider = _get_provider(data_dir)
    if provider is None:
        logger.error("No CSV or Parquet files found in %s", data_dir)
        return {}

    target_pairs = pairs or list(TradingPair)
    tfs_to_try = [timeframe] if timeframe else _EXEC_TF_PRIORITY

    data: dict[TradingPair, BarSeries] = {}
    for pair in target_pairs:
        for tf in tfs_to_try:
            try:
                series = provider.load(pair, tf)
                if len(series) > 0:
                    data[pair] = series
                    logger.info("Loaded %s %s: %d bars", pair.value, tf.value, len(series))
                    break
            except (FileNotFoundError, ValueError):
                continue
        else:
            logger.debug("No data found for %s", pair.value)

    return data


def load_htf_data(
    data: dict[TradingPair, BarSeries],
    htf_timeframe: Timeframe = Timeframe.H1,
    data_dir: Path | str | None = None,
) -> dict[TradingPair, BarSeries]:
    """Load or generate HTF context data.

    First tries to load from disk. If not available, resamples from
    the execution-timeframe data.
    """
    from fx_smc_bot.config import TIMEFRAME_MINUTES
    from fx_smc_bot.data.resampling import resample

    htf: dict[TradingPair, BarSeries] = {}

    # Try loading from disk first
    if data_dir:
        provider = _get_provider(Path(data_dir))
        if provider:
            for pair in data:
                try:
                    series = provider.load(pair, htf_timeframe)
                    if len(series) > 0:
                        htf[pair] = series
                        logger.info("Loaded HTF %s %s: %d bars", pair.value, htf_timeframe.value, len(series))
                        continue
                except (FileNotFoundError, ValueError):
                    pass

    # Resample missing pairs from execution data
    for pair, series in data.items():
        if pair in htf:
            continue
        src_min = TIMEFRAME_MINUTES[series.timeframe]
        tgt_min = TIMEFRAME_MINUTES[htf_timeframe]
        if tgt_min <= src_min:
            logger.debug("Cannot resample %s from %s to %s (not higher)", pair.value, series.timeframe.value, htf_timeframe.value)
            continue
        try:
            htf[pair] = resample(series, htf_timeframe)
            logger.info("Resampled HTF %s %s -> %s: %d bars", pair.value, series.timeframe.value, htf_timeframe.value, len(htf[pair]))
        except Exception as e:
            logger.warning("Could not resample HTF for %s: %s", pair.value, e)

    return htf
