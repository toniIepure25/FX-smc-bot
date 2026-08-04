"""Synthetic-only A0R2 walk-forward fold utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: int
    train_indices: np.ndarray
    test_indices: np.ndarray
    embargo_start_index: int
    embargo_end_index: int


def purged_expanding_folds(
    n_samples: int,
    *,
    min_train_size: int,
    test_size: int,
    embargo: int,
) -> list[WalkForwardFold]:
    """Build deterministic expanding folds with a purged embargo gap."""
    if min_train_size <= 0 or test_size <= 0 or embargo < 0:
        raise ValueError("A0R2_INVALID_FOLD_PARAMETERS")
    folds: list[WalkForwardFold] = []
    fold_id = 0
    test_start = min_train_size + embargo
    while test_start + test_size <= n_samples:
        train_end = max(0, test_start - embargo)
        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_indices=np.arange(0, train_end, dtype=np.int64),
                test_indices=np.arange(test_start, test_start + test_size, dtype=np.int64),
                embargo_start_index=train_end,
                embargo_end_index=test_start,
            )
        )
        fold_id += 1
        test_start += test_size
    return folds
