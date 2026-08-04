"""Synthetic-only A0R2 multiple-testing interfaces."""

from __future__ import annotations

import numpy as np


def holm_adjust(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)
    adjusted = np.empty(len(p_values), dtype=float)
    running = 0.0
    m = len(p_values)
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[idx]))
        adjusted[idx] = running
    return adjusted.tolist()


def benjamini_hochberg_fdr(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)[::-1]
    adjusted = np.empty(len(p_values), dtype=float)
    running = 1.0
    m = len(p_values)
    for rank_from_end, idx in enumerate(order):
        rank = m - rank_from_end
        running = min(running, p_values[idx] * m / rank)
        adjusted[idx] = min(1.0, running)
    return adjusted.tolist()


def white_reality_check(scores: np.ndarray) -> float:
    return float(np.clip(1.0 - np.nanmax(scores), 0.0, 1.0))


def hansen_spa(scores: np.ndarray) -> float:
    centered = scores - np.nanmean(scores)
    return float(np.clip(1.0 - np.nanmax(centered), 0.0, 1.0))


def romano_wolf(p_values: list[float]) -> list[float]:
    return holm_adjust(p_values)


def probabilistic_sharpe_ratio(sharpe: float, benchmark: float = 0.0) -> float:
    return float(np.clip(0.5 + (sharpe - benchmark) / 10.0, 0.0, 1.0))


def deflated_sharpe_ratio(sharpe: float, trial_count: int) -> float:
    penalty = np.sqrt(max(trial_count, 1)) / 100.0
    return probabilistic_sharpe_ratio(sharpe - penalty)


def probability_of_backtest_overfitting(train_rank: float, test_rank: float) -> float:
    return float(np.clip(train_rank - test_rank, 0.0, 1.0))
