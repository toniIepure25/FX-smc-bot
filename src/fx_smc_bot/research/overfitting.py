"""Multiple-testing correction and overfitting controls.

Implements:
- Holm-Bonferroni correction
- Benjamini-Hochberg FDR
- White's Reality Check via bootstrap
- Probability of Backtest Overfitting (PBO) via CSCV
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import stats


@dataclass(frozen=True, slots=True)
class CorrectedPValues:
    """Result of multiple-testing correction."""

    method: str
    original: list[float]
    corrected: list[float]
    rejected: list[bool]
    alpha: float


def holm_bonferroni(
    p_values: list[float],
    alpha: float = 0.05,
) -> CorrectedPValues:
    """Holm-Bonferroni step-down correction for FWER control."""
    n = len(p_values)
    if n == 0:
        return CorrectedPValues("holm_bonferroni", [], [], [], alpha)

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * n
    rejected = [False] * n

    for rank, (orig_idx, pval) in enumerate(indexed):
        adj = pval * (n - rank)
        corrected[orig_idx] = min(adj, 1.0)

    max_so_far = 0.0
    for _rank, (orig_idx, _) in enumerate(indexed):
        max_so_far = max(max_so_far, corrected[orig_idx])
        corrected[orig_idx] = max_so_far
        rejected[orig_idx] = corrected[orig_idx] <= alpha

    return CorrectedPValues("holm_bonferroni", list(p_values), corrected, rejected, alpha)


def benjamini_hochberg(
    p_values: list[float],
    alpha: float = 0.05,
) -> CorrectedPValues:
    """Benjamini-Hochberg FDR correction."""
    n = len(p_values)
    if n == 0:
        return CorrectedPValues("benjamini_hochberg", [], [], [], alpha)

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * n
    rejected = [False] * n

    for rank, (orig_idx, pval) in enumerate(indexed):
        corrected[orig_idx] = pval * n / (rank + 1)

    min_so_far = 1.0
    for rank in range(n - 1, -1, -1):
        orig_idx = indexed[rank][0]
        min_so_far = min(min_so_far, corrected[orig_idx])
        corrected[orig_idx] = min(min_so_far, 1.0)
        rejected[orig_idx] = corrected[orig_idx] <= alpha

    return CorrectedPValues("benjamini_hochberg", list(p_values), corrected, rejected, alpha)


def whites_reality_check(
    benchmark_returns: NDArray[np.float64],
    strategy_returns_list: list[NDArray[np.float64]],
    n_bootstrap: int = 5_000,
    block_size: int = 5,
    seed: int = 42,
) -> float:
    """White's Reality Check (White, 2000) / Hansen's SPA test.

    Tests if the best strategy significantly outperforms the benchmark
    after accounting for the number of strategies tested.

    Returns a p-value. If p < alpha, the best strategy significantly
    outperforms the benchmark.
    """
    rng = np.random.default_rng(seed)
    n = len(benchmark_returns)
    if n == 0 or len(strategy_returns_list) == 0:
        return 1.0

    excess_list = []
    for strat_ret in strategy_returns_list:
        if len(strat_ret) != n:
            continue
        excess_list.append(strat_ret - benchmark_returns)

    if not excess_list:
        return 1.0

    excess = np.column_stack(excess_list)
    observed_means = np.mean(excess, axis=0)
    observed_max = np.max(observed_means)

    n_blocks = max(1, n // block_size)
    max_start = n - block_size
    boot_max_stats = np.empty(n_bootstrap)

    centered = excess - observed_means[np.newaxis, :]

    for b in range(n_bootstrap):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        boot_rows = np.concatenate(
            [centered[s:s + block_size] for s in starts], axis=0,
        )[:n]
        boot_means = np.mean(boot_rows, axis=0)
        boot_max_stats[b] = np.max(boot_means)

    p_value = float(np.mean(boot_max_stats >= observed_max))
    return p_value


def cscv_pbo(
    strategy_returns_matrix: NDArray[np.float64],
    n_splits: int = 16,
    performance_fn=None,
    seed: int = 42,
) -> float:
    """Combinatorially Symmetric Cross-Validation for PBO.

    Estimates the Probability of Backtest Overfitting from a matrix
    of strategy variant returns (rows=time, cols=variants).

    Returns PBO in [0, 1]. Higher = more likely overfitted.
    """
    rng = np.random.default_rng(seed)
    n_obs, n_variants = strategy_returns_matrix.shape

    if n_obs < n_splits * 2 or n_variants < 2:
        return 0.5

    if performance_fn is None:
        def performance_fn(r):
            std = np.std(r, ddof=1)
            return np.mean(r) / std if std > 0 else 0.0

    segment_size = n_obs // n_splits
    segments = []
    for i in range(n_splits):
        start = i * segment_size
        end = start + segment_size
        segments.append(strategy_returns_matrix[start:end])

    n_combos = min(100, 2 ** n_splits // 2)
    logit_values = []

    for _ in range(n_combos):
        perm = rng.permutation(n_splits)
        half = n_splits // 2
        is_idx = perm[:half]
        oos_idx = perm[half:]

        is_data = np.concatenate([segments[i] for i in is_idx])
        oos_data = np.concatenate([segments[i] for i in oos_idx])

        is_perf = np.array([performance_fn(is_data[:, j]) for j in range(n_variants)])
        oos_perf = np.array([performance_fn(oos_data[:, j]) for j in range(n_variants)])

        best_is = np.argmax(is_perf)
        rank_oos = float(stats.rankdata(oos_perf)[best_is])
        relative_rank = rank_oos / n_variants

        if relative_rank <= 0.0 or relative_rank >= 1.0:
            logit_values.append(0.0)
        else:
            logit_values.append(np.log(relative_rank / (1 - relative_rank)))

    pbo = float(np.mean(np.array(logit_values) <= 0))
    return pbo
