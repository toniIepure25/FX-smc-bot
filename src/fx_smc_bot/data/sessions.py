"""Session labeling: tag each bar with its FX session.

Labels are stored as a numpy array of SessionName enum values (or None)
aligned with the BarSeries timestamps.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import SessionConfig
from fx_smc_bot.domain import SessionName
from fx_smc_bot.utils.time import classify_session


def label_sessions(
    timestamps: NDArray[np.datetime64],
    cfg: SessionConfig | None = None,
) -> list[SessionName | None]:
    """Return a session label for each timestamp."""
    cfg = cfg or SessionConfig()
    labels: list[SessionName | None] = []
    for ts_np in timestamps:
        ts_dt = ts_np.astype("datetime64[us]").astype(datetime)
        labels.append(classify_session(ts_dt, cfg))
    return labels
