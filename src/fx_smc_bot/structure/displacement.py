"""Displacement candle detection.

A displacement candle is a large-bodied candle that signals strong
institutional intent.  It is defined by:
  1. Body size >= `displacement_atr_multiple` * ATR
  2. Body efficiency (body/range) >= `displacement_body_efficiency`
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.domain import Direction, DisplacementCandle
from fx_smc_bot.utils.math import atr as compute_atr, body_efficiency, body_size


def detect_displacement(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    config: StructureConfig | None = None,
) -> list[DisplacementCandle]:
    """Find displacement candles in the price series."""
    cfg = config or StructureConfig()
    atr_vals = compute_atr(high, low, close, period=cfg.atr_period)
    bodies = body_size(open_, close)
    ranges = high - low
    efficiencies = body_efficiency(open_, close, high, low)

    results: list[DisplacementCandle] = []
    for i in range(len(close)):
        if atr_vals[i] <= 0:
            continue
        atr_mult = bodies[i] / atr_vals[i]
        if atr_mult < cfg.displacement_atr_multiple:
            continue
        if efficiencies[i] < cfg.displacement_body_efficiency:
            continue

        direction = Direction.LONG if close[i] > open_[i] else Direction.SHORT
        ts = timestamps[i].astype("datetime64[us]").astype(datetime)
        results.append(DisplacementCandle(
            bar_index=i, timestamp=ts, direction=direction,
            body_size=float(bodies[i]), range_size=float(ranges[i]),
            atr_multiple=float(atr_mult), body_efficiency=float(efficiencies[i]),
        ))

    return results
