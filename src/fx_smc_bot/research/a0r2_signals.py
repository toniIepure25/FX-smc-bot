"""Synthetic-only A0R2 signal helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


def threshold_signal(score: pd.Series, entry_threshold: float, abstain_below: float) -> pd.Series:
    """Convert scores to {-1, 0, 1} positions with deterministic abstention."""
    if entry_threshold < 0 or abstain_below < 0:
        raise ValueError("A0R2_INVALID_SIGNAL_THRESHOLD")
    values = score.to_numpy(dtype=float)
    raw = np.where(values >= entry_threshold, 1, np.where(values <= -entry_threshold, -1, 0))
    raw = np.where(np.abs(values) < abstain_below, 0, raw)
    return pd.Series(raw.astype(int), index=score.index, name="signal")
