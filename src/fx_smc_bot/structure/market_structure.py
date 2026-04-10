"""Market structure analysis: BOS (Break of Structure) and CHoCH (Change of Character).

Definitions
-----------
- **BOS**: Price closes beyond a prior swing point *in the direction of the
  prevailing trend*.  Example: in a bullish trend (HH, HL pattern), price
  closing above the most recent swing high is a bullish BOS.
- **CHoCH**: Price closes beyond a prior swing point *against the prevailing
  trend*.  Example: in a bullish trend, price closing below the most recent
  swing low is a bearish CHoCH -- it signals a potential reversal.

The module tracks both internal (minor) and external (major) structure by
operating on swing points of different strengths.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.domain import (
    BreakType,
    Direction,
    StructureBreak,
    StructureLevel,
    StructureRegime,
    SwingPoint,
    SwingType,
)


def detect_structure_breaks(
    swings: list[SwingPoint],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    min_strength: int = 1,
) -> list[StructureBreak]:
    """Identify BOS and CHoCH events from a sequence of swing points.

    Parameters
    ----------
    swings : swing points sorted by bar_index.
    close : close prices array (full series).
    timestamps : aligned timestamps.
    min_strength : only consider swings with strength >= this value.

    Returns
    -------
    List of StructureBreak events in chronological order.
    """
    filtered = [s for s in swings if s.strength >= min_strength]
    if len(filtered) < 3:
        return []

    level = StructureLevel.INTERNAL if min_strength <= 1 else StructureLevel.EXTERNAL

    breaks: list[StructureBreak] = []
    regime = StructureRegime.RANGING

    last_sh: SwingPoint | None = None
    last_sl: SwingPoint | None = None

    for swing in filtered:
        if swing.swing_type == SwingType.HIGH:
            if last_sh is not None and last_sl is not None:
                # Check for previous structure context to determine regime
                pass
            last_sh = swing
        else:
            last_sl = swing

    # Second pass: scan close prices bar-by-bar after each swing to find breaks
    regime = StructureRegime.RANGING
    last_sh = None
    last_sl = None

    swing_idx = 0
    for bar_i in range(len(close)):
        # Update active swings up to this bar
        while swing_idx < len(filtered) and filtered[swing_idx].bar_index <= bar_i:
            s = filtered[swing_idx]
            if s.swing_type == SwingType.HIGH:
                last_sh = s
            else:
                last_sl = s
            swing_idx += 1

        if last_sh is None or last_sl is None:
            continue

        # Check for break of swing high
        if close[bar_i] > last_sh.price:
            if regime in (StructureRegime.BULLISH, StructureRegime.RANGING):
                break_type = BreakType.BOS
            else:
                break_type = BreakType.CHOCH

            ts = timestamps[bar_i].astype("datetime64[us]").astype(datetime)
            breaks.append(StructureBreak(
                break_type=break_type,
                direction=Direction.LONG,
                level=level,
                swing_broken=last_sh,
                break_bar_index=bar_i,
                break_price=float(close[bar_i]),
                timestamp=ts,
            ))
            regime = StructureRegime.BULLISH
            last_sh = None  # consumed; wait for next swing high

        # Check for break of swing low
        elif close[bar_i] < last_sl.price:
            if regime in (StructureRegime.BEARISH, StructureRegime.RANGING):
                break_type = BreakType.BOS
            else:
                break_type = BreakType.CHOCH

            ts = timestamps[bar_i].astype("datetime64[us]").astype(datetime)
            breaks.append(StructureBreak(
                break_type=break_type,
                direction=Direction.SHORT,
                level=level,
                swing_broken=last_sl,
                break_bar_index=bar_i,
                break_price=float(close[bar_i]),
                timestamp=ts,
            ))
            regime = StructureRegime.BEARISH
            last_sl = None

    return breaks


def current_regime(breaks: list[StructureBreak]) -> StructureRegime:
    """Derive the current structure regime from the most recent break."""
    if not breaks:
        return StructureRegime.RANGING
    last = breaks[-1]
    if last.direction == Direction.LONG:
        return StructureRegime.BULLISH
    return StructureRegime.BEARISH
