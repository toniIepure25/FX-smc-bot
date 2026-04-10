"""Meta-labeling framework.

Meta-labeling (de Prado) treats the primary model's directional signal as
given and trains a secondary model to predict whether that signal will be
profitable.  This module provides the labeling infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray


class MetaLabel(str, Enum):
    TAKE = "take"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class LabeledSample:
    """A single labeled sample for meta-labeling training."""
    features: NDArray[np.float64]
    primary_signal_correct: bool
    pnl: float
    label: MetaLabel


def label_trades(
    feature_vectors: list[NDArray[np.float64]],
    pnls: list[float],
    threshold: float = 0.0,
) -> list[LabeledSample]:
    """Create meta-labels from historical trade outcomes.

    Trades with PnL > threshold get TAKE, others get SKIP.
    """
    samples: list[LabeledSample] = []
    for features, pnl in zip(feature_vectors, pnls):
        is_correct = pnl > threshold
        label = MetaLabel.TAKE if is_correct else MetaLabel.SKIP
        samples.append(LabeledSample(
            features=features,
            primary_signal_correct=is_correct,
            pnl=pnl,
            label=label,
        ))
    return samples
