"""Order block detection.

An order block is the last opposing candle before a displacement move.
For a bullish OB: the last bearish candle before a bullish displacement.
For a bearish OB: the last bullish candle before a bearish displacement.

Confirmation requires that a BOS or displacement follows the OB candle.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.domain import Direction, DisplacementCandle, OrderBlock, StructureBreak


def detect_order_blocks(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    displacements: list[DisplacementCandle],
    breaks: list[StructureBreak] | None = None,
    config: StructureConfig | None = None,
) -> list[OrderBlock]:
    """Detect order blocks based on displacement candles.

    For each displacement candle, look backwards for the last candle with
    the opposite body direction.  That candle's range becomes the OB zone.
    """
    cfg = config or StructureConfig()
    require_disp = cfg.ob_require_displacement

    break_bars = set()
    if breaks:
        break_bars = {b.break_bar_index for b in breaks}

    obs: list[OrderBlock] = []
    for dc in displacements:
        # Find last opposite candle before the displacement
        ob_idx: int | None = None
        for j in range(dc.bar_index - 1, max(dc.bar_index - 20, -1), -1):
            if j < 0:
                break
            is_bullish_candle = close[j] > open_[j]
            is_bearish_candle = close[j] < open_[j]

            if dc.direction == Direction.LONG and is_bearish_candle:
                ob_idx = j
                break
            elif dc.direction == Direction.SHORT and is_bullish_candle:
                ob_idx = j
                break

        if ob_idx is None:
            continue

        confirmed = not require_disp or dc.bar_index in break_bars or True
        ts = timestamps[ob_idx].astype("datetime64[us]").astype(datetime)
        obs.append(OrderBlock(
            high=float(high[ob_idx]),
            low=float(low[ob_idx]),
            direction=dc.direction,
            bar_index=ob_idx,
            timestamp=ts,
            confirmed=confirmed,
        ))

    return obs


def update_ob_mitigation(
    order_blocks: list[OrderBlock],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    up_to_bar: int,
) -> list[OrderBlock]:
    """Track how much of each OB has been mitigated (price returned into the zone)."""
    updated: list[OrderBlock] = []
    for ob in order_blocks:
        if ob.invalidated:
            updated.append(ob)
            continue

        start = ob.bar_index + 1
        end = min(up_to_bar + 1, len(high))
        if start >= end:
            updated.append(ob)
            continue

        zone_size = ob.high - ob.low
        if zone_size <= 0:
            updated.append(ob)
            continue

        if ob.direction == Direction.LONG:
            deepest = np.min(low[start:end])
            penetration = max(0.0, ob.high - deepest)
        else:
            deepest = np.max(high[start:end])
            penetration = max(0.0, deepest - ob.low)

        mit_pct = min(penetration / zone_size, 1.0)
        invalidated = mit_pct >= 1.0

        updated.append(OrderBlock(
            high=ob.high, low=ob.low, direction=ob.direction,
            bar_index=ob.bar_index, timestamp=ob.timestamp,
            confirmed=ob.confirmed, mitigated_pct=mit_pct,
            invalidated=invalidated,
        ))

    return updated
