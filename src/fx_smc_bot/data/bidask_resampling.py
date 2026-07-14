"""Independent bid/ask OHLC resampling.

Resamples bid and ask channels separately — never derives ask from bid+spread.
Supports M1→M5, M1→M15, M1→H1, M1→H4, M5→H1, etc.
"""
from __future__ import annotations

import numpy as np

from fx_smc_bot.config import Timeframe
from fx_smc_bot.data.bidask import BidAskBarSeries

RESAMPLE_MINUTES = {
    Timeframe.M1: 1, Timeframe.M5: 5, Timeframe.M15: 15,
    Timeframe.H1: 60, Timeframe.H4: 240,
}


def resample_bidask(
    source: BidAskBarSeries,
    target_tf: Timeframe,
) -> BidAskBarSeries:
    """Resample a BidAskBarSeries to a coarser timeframe.

    Bid and ask are resampled independently:
    - bid_open = first bid tick in period
    - bid_high = max of all bid highs in period
    - bid_low = min of all bid lows in period
    - bid_close = last bid close in period
    (same for ask side)
    """
    src_minutes = RESAMPLE_MINUTES.get(source.timeframe)
    tgt_minutes = RESAMPLE_MINUTES.get(target_tf)
    if src_minutes is None or tgt_minutes is None:
        raise ValueError(
            f"Unsupported timeframe: {source.timeframe} → {target_tf}"
        )
    if tgt_minutes <= src_minutes:
        raise ValueError(
            f"Target {target_tf.value} must be coarser than "
            f"source {source.timeframe.value}"
        )
    if tgt_minutes % src_minutes != 0:
        raise ValueError(
            f"Target {tgt_minutes}m not evenly divisible by "
            f"source {src_minutes}m"
        )

    n = len(source)
    if n == 0:
        return BidAskBarSeries(
            pair=source.pair, timeframe=target_tf,
            timestamps=source.timestamps[:0],
            bid_open=source.bid_open[:0], bid_high=source.bid_high[:0],
            bid_low=source.bid_low[:0], bid_close=source.bid_close[:0],
            ask_open=source.ask_open[:0], ask_high=source.ask_high[:0],
            ask_low=source.ask_low[:0], ask_close=source.ask_close[:0],
        )

    bars_per_group: dict[int, list[int]] = {}
    period_ns = int(tgt_minutes * 60 * 1e9)
    aligned_keys: dict[int, np.datetime64] = {}
    for i in range(n):
        ts = source.timestamps[i]
        epoch = int(ts.astype("datetime64[ns]").astype("int64"))
        key = epoch - (epoch % period_ns)
        if key not in bars_per_group:
            bars_per_group[key] = []
            aligned_keys[key] = np.datetime64(key, "ns")
        bars_per_group[key].append(i)

    sorted_keys = sorted(bars_per_group.keys())
    m = len(sorted_keys)

    out_ts = np.array(
        [aligned_keys[k] for k in sorted_keys], dtype="datetime64[ns]",
    )
    out_bid_o = np.zeros(m, dtype=np.float64)
    out_bid_h = np.zeros(m, dtype=np.float64)
    out_bid_l = np.zeros(m, dtype=np.float64)
    out_bid_c = np.zeros(m, dtype=np.float64)
    out_ask_o = np.zeros(m, dtype=np.float64)
    out_ask_h = np.zeros(m, dtype=np.float64)
    out_ask_l = np.zeros(m, dtype=np.float64)
    out_ask_c = np.zeros(m, dtype=np.float64)
    out_vol = np.zeros(m, dtype=np.float64)

    for j, k in enumerate(sorted_keys):
        idxs = bars_per_group[k]
        first, last = idxs[0], idxs[-1]
        out_bid_o[j] = source.bid_open[first]
        out_bid_h[j] = np.max(source.bid_high[idxs])
        out_bid_l[j] = np.min(source.bid_low[idxs])
        out_bid_c[j] = source.bid_close[last]
        out_ask_o[j] = source.ask_open[first]
        out_ask_h[j] = np.max(source.ask_high[idxs])
        out_ask_l[j] = np.min(source.ask_low[idxs])
        out_ask_c[j] = source.ask_close[last]
        if source.volume is not None:
            out_vol[j] = np.sum(source.volume[idxs])

    return BidAskBarSeries(
        pair=source.pair, timeframe=target_tf,
        timestamps=out_ts,
        bid_open=out_bid_o, bid_high=out_bid_h,
        bid_low=out_bid_l, bid_close=out_bid_c,
        ask_open=out_ask_o, ask_high=out_ask_h,
        ask_low=out_ask_l, ask_close=out_ask_c,
        volume=out_vol if source.volume is not None else None,
    )
