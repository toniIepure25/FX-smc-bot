"""CSV-based market data provider.

Expected directory layout::

    root/
      EURUSD/
        15m.csv
        1h.csv
      GBPUSD/
        ...

CSV columns: timestamp, open, high, low, close [, volume] [, spread]
Timestamp format: ISO-8601 or any pandas-parseable format.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries


class CsvProvider:
    """Loads OHLCV data from CSV files organised by pair/timeframe."""

    def __init__(self, root_dir: Path | str) -> None:
        self._root = Path(root_dir)

    def _csv_path(self, pair: TradingPair, timeframe: Timeframe) -> Path:
        return self._root / pair.value / f"{timeframe.value}.csv"

    def load(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        start: str | None = None,
        end: str | None = None,
    ) -> BarSeries:
        path = self._csv_path(pair, timeframe)
        if not path.exists():
            raise FileNotFoundError(f"No CSV file at {path}")

        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        if start:
            df = df[df["timestamp"] >= pd.Timestamp(start)]
        if end:
            df = df[df["timestamp"] <= pd.Timestamp(end)]

        if df.empty:
            raise ValueError(f"No data for {pair.value}/{timeframe.value} in date range")

        timestamps = df["timestamp"].values.astype("datetime64[ns]")
        o = df["open"].values.astype(np.float64)
        h = df["high"].values.astype(np.float64)
        lo = df["low"].values.astype(np.float64)
        c = df["close"].values.astype(np.float64)
        vol = df["volume"].values.astype(np.float64) if "volume" in df.columns else None
        sp = df["spread"].values.astype(np.float64) if "spread" in df.columns else None

        return BarSeries(
            pair=pair, timeframe=timeframe, timestamps=timestamps,
            open=o, high=h, low=lo, close=c,
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
            if (pair_dir / f"{member.value}.csv").exists():
                tfs.append(member)
        return tfs
