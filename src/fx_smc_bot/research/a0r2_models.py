"""Synthetic-only A0R2 model interfaces."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


def fit_train_only_linear_scores(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
) -> pd.Series:
    """Fit a deterministic least-squares model on train data only."""
    x = train_x.to_numpy(dtype=float)
    y = train_y.to_numpy(dtype=float)
    coef = np.linalg.pinv(x) @ y
    scores = test_x.to_numpy(dtype=float) @ coef
    return pd.Series(scores, index=test_x.index, name="score")
