"""Frozen statistical inference utilities for Gate Q.0."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats  # type: ignore[import-untyped]

from fx_smc_bot.research.overfitting import benjamini_hochberg, holm_bonferroni

SEED = 1729


@dataclass(frozen=True)
class ClusterInterval:
    point_estimate: float
    lower: float
    upper: float
    cluster_count: int
    iterations: int


@dataclass(frozen=True)
class HacAlpha:
    alpha: float
    standard_error: float
    t_statistic: float
    p_value: float
    lag: int
    observations: int


def cluster_bootstrap_mean_ci(
    values: Sequence[float],
    clusters: Sequence[str],
    *,
    iterations: int = 10_000,
    seed: int = SEED,
) -> ClusterInterval:
    array = np.asarray(values, dtype=float)
    cluster_array = np.asarray(clusters, dtype=object)
    if len(array) != len(cluster_array):
        raise ValueError("Values and clusters must have equal length")
    unique = np.unique(cluster_array)
    if len(unique) == 0:
        return ClusterInterval(0.0, 0.0, 0.0, 0, iterations)
    rng = np.random.default_rng(seed)
    indices = {cluster: np.flatnonzero(cluster_array == cluster) for cluster in unique}
    estimates = np.empty(iterations, dtype=float)
    for iteration in range(iterations):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        chosen = np.concatenate([indices[cluster] for cluster in sampled])
        estimates[iteration] = float(np.mean(array[chosen]))
    return ClusterInterval(
        point_estimate=float(np.mean(array)),
        lower=float(np.quantile(estimates, 0.025)),
        upper=float(np.quantile(estimates, 0.975)),
        cluster_count=len(unique),
        iterations=iterations,
    )


def matched_entry_permutation_p_value(
    candidate: Sequence[float],
    matched_random: Sequence[float],
    *,
    iterations: int = 10_000,
    seed: int = SEED,
) -> float:
    candidate_array = np.asarray(candidate, dtype=float)
    random_array = np.asarray(matched_random, dtype=float)
    if candidate_array.shape != random_array.shape or candidate_array.size == 0:
        raise ValueError("Matched candidate and random samples must be non-empty and aligned")
    differences = candidate_array - random_array
    observed = float(np.mean(differences))
    rng = np.random.default_rng(seed)
    exceedances = 0
    completed = 0
    while completed < iterations:
        batch = min(512, iterations - completed)
        signs = rng.choice((-1.0, 1.0), size=(batch, len(differences)))
        permuted = np.mean(signs * differences, axis=1)
        exceedances += int(np.sum(permuted >= observed))
        completed += batch
    return float((1 + exceedances) / (iterations + 1))


def newey_west_factor_alpha(
    strategy_returns: Sequence[float],
    factors: np.ndarray,
    *,
    lag: int = 5,
) -> HacAlpha:
    y = np.asarray(strategy_returns, dtype=float)
    x_factors = np.asarray(factors, dtype=float)
    if x_factors.ndim != 2 or len(y) != x_factors.shape[0]:
        raise ValueError("Factor matrix must align with strategy returns")
    if lag != 5:
        raise ValueError("Gate Q.0 freezes the Newey-West lag at five trading days")
    x = np.column_stack((np.ones(len(y)), x_factors))
    xtx_inverse = np.linalg.pinv(x.T @ x)
    beta = xtx_inverse @ x.T @ y
    residuals = y - x @ beta
    scores = x * residuals[:, None]
    meat = scores.T @ scores
    for distance in range(1, min(lag, len(y) - 1) + 1):
        weight = 1.0 - distance / (lag + 1.0)
        gamma = scores[distance:].T @ scores[:-distance]
        meat += weight * (gamma + gamma.T)
    covariance = xtx_inverse @ meat @ xtx_inverse
    standard_error = float(np.sqrt(max(covariance[0, 0], 0.0)))
    alpha = float(beta[0])
    t_statistic = alpha / standard_error if standard_error > 0 else 0.0
    degrees = max(len(y) - x.shape[1], 1)
    p_value = float(2.0 * stats.t.sf(abs(t_statistic), df=degrees))
    return HacAlpha(alpha, standard_error, t_statistic, p_value, lag, len(y))


def romano_wolf_max_t(
    observed_statistics: Sequence[float],
    bootstrap_statistics: np.ndarray,
) -> list[float]:
    observed = np.abs(np.asarray(observed_statistics, dtype=float))
    bootstrap = np.abs(np.asarray(bootstrap_statistics, dtype=float))
    if bootstrap.ndim != 2 or bootstrap.shape[1] != len(observed):
        raise ValueError("Bootstrap statistics must be iterations by hypotheses")
    order = np.argsort(-observed)
    adjusted = np.zeros(len(observed), dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        remaining = order[rank:]
        maxima = np.max(bootstrap[:, remaining], axis=1)
        raw = float((1 + np.sum(maxima >= observed[index])) / (len(maxima) + 1))
        running = max(running, raw)
        adjusted[index] = running
    return adjusted.tolist()


def corrected_p_values(p_values: Sequence[float]) -> dict[str, list[float]]:
    values = [float(value) for value in p_values]
    return {
        "holm": holm_bonferroni(values).corrected,
        "benjamini_hochberg": benjamini_hochberg(values).corrected,
    }


def hansen_spa_p_value(
    excess_returns: np.ndarray,
    *,
    iterations: int = 5_000,
    block_size: int = 5,
    seed: int = SEED,
) -> float:
    """Studentized block-bootstrap SPA test against a zero-excess benchmark."""
    excess = np.asarray(excess_returns, dtype=float)
    if excess.ndim != 2 or excess.shape[0] < 2 or excess.shape[1] == 0:
        return 1.0
    observations = excess.shape[0]
    means = np.mean(excess, axis=0)
    standard_errors = np.std(excess, axis=0, ddof=1) / np.sqrt(observations)
    standard_errors = np.where(standard_errors > 0, standard_errors, np.inf)
    observed = float(np.max(means / standard_errors))
    centered = excess - means
    block_size = min(block_size, observations)
    block_count = math.ceil(observations / block_size)
    maximum_start = observations - block_size
    rng = np.random.default_rng(seed)
    bootstrap_max = np.empty(iterations, dtype=float)
    for iteration in range(iterations):
        starts = rng.integers(0, maximum_start + 1, size=block_count)
        sample = np.concatenate(
            [centered[start : start + block_size] for start in starts], axis=0
        )[:observations]
        bootstrap_max[iteration] = float(
            np.max(np.mean(sample, axis=0) / standard_errors)
        )
    return float((1 + np.sum(bootstrap_max >= observed)) / (iterations + 1))
