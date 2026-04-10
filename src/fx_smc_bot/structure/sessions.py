"""Session-level structure tracking: session highs/lows, killzones.

Tracks the high and low of each session (Asian, London, NY) per day,
producing SessionWindow objects that serve as liquidity reference levels.
"""

from __future__ import annotations

from datetime import datetime, date as date_type

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import SessionConfig
from fx_smc_bot.domain import SessionName, SessionWindow
from fx_smc_bot.utils.time import classify_session


def track_session_windows(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    config: SessionConfig | None = None,
) -> list[SessionWindow]:
    """Build session windows with tracked high/low for each session each day."""
    cfg = config or SessionConfig()
    n = len(timestamps)
    if n == 0:
        return []

    # Group bars by (date, session)
    windows_map: dict[tuple[date_type, SessionName], dict] = {}

    for i in range(n):
        ts_dt = timestamps[i].astype("datetime64[us]").astype(datetime)
        session = classify_session(ts_dt, cfg)
        if session is None:
            continue

        day = ts_dt.date()
        key = (day, session)

        if key not in windows_map:
            windows_map[key] = {
                "session": session, "date": ts_dt,
                "open_time": ts_dt, "close_time": ts_dt,
                "high": float(high[i]), "low": float(low[i]),
                "high_idx": i, "low_idx": i,
            }
        else:
            w = windows_map[key]
            w["close_time"] = ts_dt
            if high[i] > w["high"]:
                w["high"] = float(high[i])
                w["high_idx"] = i
            if low[i] < w["low"]:
                w["low"] = float(low[i])
                w["low_idx"] = i

    windows: list[SessionWindow] = []
    for (day, session), w in sorted(windows_map.items()):
        windows.append(SessionWindow(
            session_name=w["session"],
            date=w["date"],
            open_time=w["open_time"],
            close_time=w["close_time"],
            high=w["high"],
            low=w["low"],
            high_index=w["high_idx"],
            low_index=w["low_idx"],
        ))

    return windows
