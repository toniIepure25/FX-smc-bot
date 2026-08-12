"""Shared fixtures/helpers for A0R4 V2 tests."""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]

# NY 10:00 EDT (summer, UTC-4): safely outside rollover/flat windows (16:30-17:30 NY).
BASE_TS = pd.Timestamp("2016-06-15 14:00", tz="UTC")


def build_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a canonical bid/ask OHLC frame from explicit per-bar dicts.

    Each bar dict provides ``bid``/``ask`` scalars expanded into flat OHLC unless explicit
    ``*_open/_high/_low/_close`` keys are given. ``minute`` offsets from BASE_TS.
    """

    rows: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        ts = bar.get("timestamp", BASE_TS + pd.Timedelta(minutes=bar.get("minute", i)))
        row: dict[str, Any] = {"timestamp": ts}
        for side in ("bid", "ask"):
            flat = bar.get(side)
            for ohlc in ("open", "high", "low", "close"):
                key = f"{side}_{ohlc}"
                row[key] = float(bar.get(key, flat))
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["mid_close"] = (frame["bid_close"] + frame["ask_close"]) / 2.0
    frame["mid_open"] = (frame["bid_open"] + frame["ask_open"]) / 2.0
    frame["mid_high"] = (frame["bid_high"] + frame["ask_high"]) / 2.0
    frame["mid_low"] = (frame["bid_low"] + frame["ask_low"]) / 2.0
    frame["spread"] = frame["ask_close"] - frame["bid_close"]
    frame["mid_return"] = frame["mid_close"].pct_change().fillna(0.0)
    return frame
