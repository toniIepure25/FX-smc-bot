"""Synthetic-only A0R2 feature transformations."""

from __future__ import annotations

import pandas as pd  # type: ignore[import-untyped]


def train_only_standardize(
    train: pd.DataFrame, test: pd.DataFrame, columns: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standardize train/test frames using only train-window moments."""
    train_out = train.copy()
    test_out = test.copy()
    for column in columns:
        mean = float(train[column].mean())
        std = float(train[column].std(ddof=0)) or 1.0
        train_out[column] = (train[column] - mean) / std
        test_out[column] = (test[column] - mean) / std
    return train_out, test_out


def strictly_lagged_cross_pair_features(
    frame: pd.DataFrame, columns: list[str], lag: int
) -> pd.DataFrame:
    """Create cross-pair predictors that cannot see the current bar."""
    if lag < 1:
        raise ValueError("A0R2_CROSS_PAIR_LAG_MUST_BE_POSITIVE")
    out = frame.copy()
    for column in columns:
        out[f"{column}_lag{lag}"] = out[column].shift(lag)
    return out


def filtered_regime_states(values: pd.Series, n_states: int) -> pd.Series:
    """Assign deterministic filtered quantile states from past values only."""
    if n_states < 2:
        raise ValueError("A0R2_REGIME_STATE_COUNT_TOO_LOW")
    expanding_rank = values.expanding().rank(pct=True).shift(1).fillna(0.5)
    states = (expanding_rank * n_states).clip(0, n_states - 1).astype(int)
    return states
