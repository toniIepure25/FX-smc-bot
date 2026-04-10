"""Walk-forward validation: split data into train/test windows for out-of-sample testing.

Supports anchored, rolling, and purged (with embargo) modes.

Purged walk-forward prevents data leakage by inserting a gap (embargo)
between train and test windows. This is critical when features might
contain look-ahead information from recent bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    """A single train/test split with bar index boundaries."""
    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def anchored_walk_forward(
    n_bars: int,
    n_folds: int = 5,
    min_train_bars: int = 200,
) -> list[WalkForwardSplit]:
    """Anchored walk-forward: training always starts at bar 0, test window advances."""
    if n_bars < min_train_bars + 50:
        raise ValueError(f"Not enough bars ({n_bars}) for {n_folds} folds")

    test_bars = (n_bars - min_train_bars) // n_folds
    splits: list[WalkForwardSplit] = []

    for i in range(n_folds):
        test_start = min_train_bars + i * test_bars
        test_end = min(test_start + test_bars, n_bars)
        splits.append(WalkForwardSplit(
            fold_id=i,
            train_start=0,
            train_end=test_start,
            test_start=test_start,
            test_end=test_end,
        ))

    return splits


def rolling_walk_forward(
    n_bars: int,
    train_size: int = 500,
    test_size: int = 100,
    step_size: int | None = None,
) -> list[WalkForwardSplit]:
    """Rolling walk-forward: fixed-size training window that advances."""
    step = step_size or test_size
    splits: list[WalkForwardSplit] = []
    fold_id = 0
    start = 0

    while start + train_size + test_size <= n_bars:
        splits.append(WalkForwardSplit(
            fold_id=fold_id,
            train_start=start,
            train_end=start + train_size,
            test_start=start + train_size,
            test_end=min(start + train_size + test_size, n_bars),
        ))
        start += step
        fold_id += 1

    return splits


def purged_walk_forward(
    n_bars: int,
    n_folds: int = 5,
    embargo_bars: int = 10,
    min_train_bars: int = 200,
) -> list[WalkForwardSplit]:
    """Purged walk-forward: anchored splits with an embargo gap between train and test.

    The embargo period creates a buffer zone between the end of training
    and the start of testing, preventing information leakage from
    auto-correlated features or overlapping label windows.

    Parameters
    ----------
    n_bars : total number of bars in the dataset
    n_folds : number of validation folds
    embargo_bars : number of bars to skip between train end and test start
    min_train_bars : minimum bars in the initial training window
    """
    usable = n_bars - min_train_bars - embargo_bars
    if usable < n_folds * 20:
        raise ValueError(
            f"Not enough bars ({n_bars}) for {n_folds} purged folds "
            f"with {embargo_bars}-bar embargo"
        )

    test_bars = usable // n_folds
    splits: list[WalkForwardSplit] = []

    for i in range(n_folds):
        train_end = min_train_bars + i * test_bars
        test_start = train_end + embargo_bars
        test_end = min(test_start + test_bars, n_bars)

        if test_start >= n_bars or test_end <= test_start:
            break

        splits.append(WalkForwardSplit(
            fold_id=i,
            train_start=0,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        ))

    return splits
