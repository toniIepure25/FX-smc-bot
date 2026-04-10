"""Parquet-based market data provider.

Expected directory layout::

    root/
      EURUSD/
        15m.parquet
        1h.parquet
      GBPUSD/
        ...

Each parquet file has canonical columns: timestamp, open, high, low, close
[, volume] [, spread].
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.normalize import load_parquet


class ParquetProvider:
    """Loads OHLCV data from Parquet files organised by pair/timeframe."""

    def __init__(self, root_dir: Path | str) -> None:
        self._root = Path(root_dir)

    def _parquet_path(self, pair: TradingPair, timeframe: Timeframe) -> Path:
        return self._root / pair.value / f"{timeframe.value}.parquet"

    def load(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        start: str | None = None,
        end: str | None = None,
    ) -> BarSeries:
        path = self._parquet_path(pair, timeframe)
        if not path.exists():
            raise FileNotFoundError(f"No Parquet file at {path}")

        df = load_parquet(path)

        if start:
            df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]

        if df.empty:
            raise ValueError(f"No data for {pair.value}/{timeframe.value} in date range")

        timestamps = df["timestamp"].values.astype("datetime64[ns]")
        vol = df["volume"].values.astype(np.float64) if "volume" in df.columns else None
        sp = df["spread"].values.astype(np.float64) if "spread" in df.columns else None

        return BarSeries(
            pair=pair, timeframe=timeframe, timestamps=timestamps,
            open=df["open"].values.astype(np.float64),
            high=df["high"].values.astype(np.float64),
            low=df["low"].values.astype(np.float64),
            close=df["close"].values.astype(np.float64),
            volume=vol, spread=sp,
        )

    def available_pairs(self) -> list[TradingPair]:
        pairs: list[TradingPair] = []
        for member in TradingPair:
            if (self._root / member.value).is_dir():
                pairs.append(member)
        return pairs

    def available_timeframes(self, pair: TradingPair) -> list[Timeframe]:
        pair_dir = self._root / pair.value
        if not pair_dir.is_dir():
            return []
        tfs: list[Timeframe] = []
        for member in Timeframe:
            if (pair_dir / f"{member.value}.parquet").exists():
                tfs.append(member)
        return tfs
