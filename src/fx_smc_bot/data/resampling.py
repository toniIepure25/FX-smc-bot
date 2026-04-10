"""Timeframe resampling: aggregate lower-TF bars into higher-TF bars.

Uses pandas resample under the hood for correctness, then converts back
to BarSeries.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fx_smc_bot.config import TIMEFRAME_MINUTES, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries

_TF_TO_PANDAS_FREQ: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1D",
}


def resample(series: BarSeries, target_tf: Timeframe) -> BarSeries:
    """Aggregate *series* to *target_tf*.

    Raises ValueError if target_tf is not a higher timeframe than the source.
    """
    src_minutes = TIMEFRAME_MINUTES[series.timeframe]
    tgt_minutes = TIMEFRAME_MINUTES[target_tf]
    if tgt_minutes <= src_minutes:
        raise ValueError(
            f"Target timeframe {target_tf.value} ({tgt_minutes}m) must be "
            f"higher than source {series.timeframe.value} ({src_minutes}m)"
        )

    freq = _TF_TO_PANDAS_FREQ[target_tf]
    df = pd.DataFrame({
        "open": series.open,
        "high": series.high,
        "low": series.low,
        "close": series.close,
    }, index=pd.DatetimeIndex(series.timestamps))

    if series.volume is not None:
        df["volume"] = series.volume

    agg: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"

    resampled = df.resample(freq, label="left", closed="left").agg(agg).dropna(subset=["open"])

    timestamps = resampled.index.values.astype("datetime64[ns]")
    vol = resampled["volume"].values.astype(np.float64) if "volume" in resampled.columns else None

    return BarSeries(
        pair=series.pair,
        timeframe=target_tf,
        timestamps=timestamps,
        open=resampled["open"].values.astype(np.float64),
        high=resampled["high"].values.astype(np.float64),
        low=resampled["low"].values.astype(np.float64),
        close=resampled["close"].values.astype(np.float64),
        volume=vol,
    )
