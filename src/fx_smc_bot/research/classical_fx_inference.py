"""Deterministic inference utilities for Gate F.0 classical FX factors.

The functions in this module operate only on caller-provided arrays. They do
not read market data, inspect data roots, or persist empirical results.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import stats  # type: ignore[import-untyped]

PROTOCOL_SEED = 1729
PROTOCOL_RESAMPLES = 10_000
PROTOCOL_CONFIDENCE = 0.95
PROTOCOL_HAC_LAG = 5
TRADING_DAYS = 252

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    point_estimate: float
    lower: float
    upper: float
    confidence_level: float
    resamples: int
    seed: int
    method: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HacAlphaResult:
    alpha: float
    standard_error: float
    t_statistic: float
    p_value: float
    lag: int
    observations: int
    regressors: int
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyTestResult:
    statistic: float
    p_value: float
    candidate_statistics: tuple[float, ...]
    candidate_p_values: tuple[float, ...]
    resamples: int
    seed: int
    method: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MultipleTestingResult:
    raw_p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    alpha: float
    method: str


@dataclass(frozen=True, slots=True)
class RomanoWolfResult:
    raw_p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    t_statistics: tuple[float, ...]
    resamples: int
    seed: int
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SharpeProbabilityResult:
    observed_sharpe: float
    reference_sharpe: float
    probability: float
    observations: int
    method: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PboResult:
    probability: float
    logits: tuple[float, ...]
    combinations: int
    slices: int
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReturnMetrics:
    observations: int
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    sortino: float
    calmar: float
    maximum_drawdown: float
    time_under_water: float
    cvar_95: float
    skew: float
    kurtosis: float
    hit_rate: float
    monthly_win_rate: float
    yearly_returns: tuple[tuple[int, float], ...]
    diagnostics: tuple[str, ...] = ()


def _as_vector(values: Sequence[float] | FloatArray, *, name: str, minimum: int = 1) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if array.size < minimum:
        raise ValueError(f"{name} must contain at least {minimum} observations")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _as_matrix(
    values: Sequence[Sequence[float]] | FloatArray,
    *,
    name: str,
    minimum_rows: int = 2,
) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] < minimum_rows or array.shape[1] == 0:
        raise ValueError(f"{name} must be a non-empty two-dimensional observation matrix")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _validate_resampling(resamples: int, confidence_level: float) -> None:
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")


def _stationary_indices(
    observations: int,
    resamples: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> NDArray[np.int64]:
    if expected_block_length < 1.0 or not math.isfinite(expected_block_length):
        raise ValueError("expected_block_length must be finite and at least one")
    restart_probability = 1.0 / expected_block_length
    indices = np.empty((resamples, observations), dtype=np.int64)
    indices[:, 0] = rng.integers(0, observations, size=resamples)
    for position in range(1, observations):
        restart = rng.random(resamples) < restart_probability
        continuation = (indices[:, position - 1] + 1) % observations
        starts = rng.integers(0, observations, size=resamples)
        indices[:, position] = np.where(restart, starts, continuation)
    return indices


def _stationary_bootstrap_means(
    values: FloatArray,
    *,
    resamples: int,
    expected_block_length: float,
    seed: int,
) -> FloatArray:
    matrix = values[:, None] if values.ndim == 1 else values
    result = np.empty((resamples, matrix.shape[1]), dtype=np.float64)
    rng = np.random.default_rng(seed)
    batch_size = 256
    completed = 0
    while completed < resamples:
        batch = min(batch_size, resamples - completed)
        indices = _stationary_indices(len(matrix), batch, expected_block_length, rng)
        result[completed : completed + batch] = np.mean(matrix[indices], axis=1)
        completed += batch
    return result


def stationary_bootstrap_ci(
    values: Sequence[float] | FloatArray,
    *,
    resamples: int = PROTOCOL_RESAMPLES,
    expected_block_length: float = 10.0,
    confidence_level: float = PROTOCOL_CONFIDENCE,
    seed: int = PROTOCOL_SEED,
) -> ConfidenceInterval:
    """Percentile CI for the mean using the Politis-Romano stationary bootstrap."""
    array = _as_vector(values, name="values", minimum=2)
    _validate_resampling(resamples, confidence_level)
    diagnostics: list[str] = []
    if float(np.std(array)) == 0.0:
        diagnostics.append("CONSTANT_SERIES")
    estimates = _stationary_bootstrap_means(
        array,
        resamples=resamples,
        expected_block_length=expected_block_length,
        seed=seed,
    )[:, 0]
    tail = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(estimates, (tail, 1.0 - tail))
    return ConfidenceInterval(
        point_estimate=float(np.mean(array)),
        lower=float(lower),
        upper=float(upper),
        confidence_level=confidence_level,
        resamples=resamples,
        seed=seed,
        method="STATIONARY_BOOTSTRAP_PERCENTILE_MEAN",
        diagnostics=tuple(diagnostics),
    )


def month_cluster_bootstrap_ci(
    values: Sequence[float] | FloatArray,
    dates: Sequence[object] | NDArray[np.datetime64],
    *,
    resamples: int = PROTOCOL_RESAMPLES,
    confidence_level: float = PROTOCOL_CONFIDENCE,
    seed: int = PROTOCOL_SEED,
) -> ConfidenceInterval:
    """Percentile CI for the mean by resampling whole observed calendar months."""
    array = _as_vector(values, name="values", minimum=2)
    _validate_resampling(resamples, confidence_level)
    date_array = np.asarray(dates, dtype="datetime64[D]")
    if date_array.ndim != 1 or len(date_array) != len(array) or np.isnat(date_array).any():
        raise ValueError("dates must be valid and aligned with values")
    months = date_array.astype("datetime64[M]")
    unique_months = np.unique(months)
    if len(unique_months) < 2:
        raise ValueError("month cluster bootstrap requires at least two calendar months")
    month_indices = [np.flatnonzero(months == month) for month in unique_months]
    rng = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=np.float64)
    for iteration in range(resamples):
        selected = rng.integers(0, len(month_indices), size=len(month_indices))
        sample = np.concatenate([array[month_indices[index]] for index in selected])
        estimates[iteration] = float(np.mean(sample))
    tail = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(estimates, (tail, 1.0 - tail))
    return ConfidenceInterval(
        point_estimate=float(np.mean(array)),
        lower=float(lower),
        upper=float(upper),
        confidence_level=confidence_level,
        resamples=resamples,
        seed=seed,
        method="CALENDAR_MONTH_CLUSTER_BOOTSTRAP_PERCENTILE_MEAN",
        diagnostics=(f"CLUSTERS={len(unique_months)}",),
    )


def newey_west_hac_alpha(
    returns: Sequence[float] | FloatArray,
    controls: Sequence[Sequence[float]] | FloatArray | None = None,
    *,
    lag: int = PROTOCOL_HAC_LAG,
) -> HacAlphaResult:
    """OLS intercept with Bartlett-kernel Newey-West HAC inference."""
    y = _as_vector(returns, name="returns", minimum=2)
    if lag < 0:
        raise ValueError("lag must be non-negative")
    if controls is None:
        control_matrix = np.empty((len(y), 0), dtype=np.float64)
    else:
        control_matrix = np.asarray(controls, dtype=np.float64)
        if control_matrix.ndim == 1:
            control_matrix = control_matrix[:, None]
        if control_matrix.ndim != 2 or control_matrix.shape[0] != len(y):
            raise ValueError("controls must align with returns")
        if not np.all(np.isfinite(control_matrix)):
            raise ValueError("controls contains non-finite values")
    design = np.column_stack((np.ones(len(y)), control_matrix))
    if len(y) <= design.shape[1]:
        raise ValueError("more observations than regression coefficients are required")
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        raise ValueError("regression design is rank deficient")
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    residuals = y - design @ beta
    bread = np.linalg.inv(design.T @ design)
    scores = design * residuals[:, None]
    meat = scores.T @ scores
    effective_lag = min(lag, len(y) - 1)
    for distance in range(1, effective_lag + 1):
        weight = 1.0 - distance / (lag + 1.0)
        covariance = scores[distance:].T @ scores[:-distance]
        meat += weight * (covariance + covariance.T)
    hac_covariance = bread @ meat @ bread
    variance = float(hac_covariance[0, 0])
    diagnostics: list[str] = []
    if effective_lag != lag:
        diagnostics.append(f"EFFECTIVE_LAG={effective_lag}")
    if variance <= np.finfo(float).eps:
        standard_error = 0.0
        t_statistic = 0.0
        p_value = 1.0
        diagnostics.append("DEGENERATE_HAC_VARIANCE")
    else:
        standard_error = math.sqrt(variance)
        t_statistic = float(beta[0] / standard_error)
        p_value = float(2.0 * stats.norm.sf(abs(t_statistic)))
    return HacAlphaResult(
        alpha=float(beta[0]),
        standard_error=standard_error,
        t_statistic=t_statistic,
        p_value=p_value,
        lag=lag,
        observations=len(y),
        regressors=design.shape[1],
        diagnostics=tuple(diagnostics),
    )


def _studentized_means(excess: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    means = np.mean(excess, axis=0)
    standard_errors = np.std(excess, axis=0, ddof=1) / math.sqrt(excess.shape[0])
    valid = standard_errors > np.finfo(float).eps
    statistics = np.zeros(excess.shape[1], dtype=np.float64)
    statistics[valid] = means[valid] / standard_errors[valid]
    return means, standard_errors, statistics


def _bootstrap_centered_t(
    excess: FloatArray,
    center: FloatArray,
    standard_errors: FloatArray,
    *,
    resamples: int,
    expected_block_length: float,
    seed: int,
) -> FloatArray:
    bootstrap_means = (
        _stationary_bootstrap_means(
            excess,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
        )
        - center
    )
    result = np.zeros_like(bootstrap_means)
    valid = standard_errors > np.finfo(float).eps
    result[:, valid] = bootstrap_means[:, valid] / standard_errors[valid]
    return result


def white_reality_check(
    excess_returns: Sequence[Sequence[float]] | FloatArray,
    *,
    resamples: int = PROTOCOL_RESAMPLES,
    expected_block_length: float = 10.0,
    seed: int = PROTOCOL_SEED,
) -> FamilyTestResult:
    """White Reality Check for the best mean excess return in a frozen family."""
    excess = _as_matrix(excess_returns, name="excess_returns")
    _validate_resampling(resamples, PROTOCOL_CONFIDENCE)
    means = np.mean(excess, axis=0)
    observed = float(max(0.0, np.max(means)))
    centered = excess - means
    bootstrap = np.max(
        _stationary_bootstrap_means(
            centered,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
        ),
        axis=1,
    )
    family_p = float((1 + np.count_nonzero(bootstrap >= observed)) / (resamples + 1))
    raw_p = tuple(
        float((1 + np.count_nonzero(bootstrap >= max(0.0, mean))) / (resamples + 1))
        for mean in means
    )
    diagnostics = () if np.any(np.std(excess, axis=0) > 0.0) else ("CONSTANT_FAMILY",)
    return FamilyTestResult(
        statistic=observed,
        p_value=family_p,
        candidate_statistics=tuple(float(value) for value in means),
        candidate_p_values=raw_p,
        resamples=resamples,
        seed=seed,
        method="WHITE_REALITY_CHECK_STATIONARY_BOOTSTRAP",
        diagnostics=diagnostics,
    )


def hansen_spa(
    excess_returns: Sequence[Sequence[float]] | FloatArray,
    *,
    resamples: int = PROTOCOL_RESAMPLES,
    expected_block_length: float = 10.0,
    seed: int = PROTOCOL_SEED,
) -> FamilyTestResult:
    """Hansen SPA with studentization and consistent null recentering."""
    excess = _as_matrix(excess_returns, name="excess_returns")
    _validate_resampling(resamples, PROTOCOL_CONFIDENCE)
    means, standard_errors, statistics = _studentized_means(excess)
    valid = standard_errors > np.finfo(float).eps
    diagnostics: list[str] = []
    if not np.all(valid):
        diagnostics.append(f"ZERO_VARIANCE_CANDIDATES={int(np.count_nonzero(~valid))}")
    # Hansen's consistent selection: clearly inferior models are recentered at
    # zero in the bootstrap, while plausible models retain their sample mean.
    threshold = -math.sqrt(2.0 * math.log(math.log(max(len(excess), 3))))
    selected = valid & (statistics >= threshold)
    center = np.where(selected, means, 0.0)
    bootstrap_t = _bootstrap_centered_t(
        excess,
        center,
        standard_errors,
        resamples=resamples,
        expected_block_length=expected_block_length,
        seed=seed,
    )
    bootstrap_max = np.maximum(0.0, np.max(bootstrap_t, axis=1))
    observed = float(max(0.0, np.max(statistics)))
    family_p = float((1 + np.count_nonzero(bootstrap_max >= observed)) / (resamples + 1))
    raw_p = tuple(
        float((1 + np.count_nonzero(bootstrap_t[:, index] >= max(0.0, value))) / (resamples + 1))
        if valid[index]
        else 1.0
        for index, value in enumerate(statistics)
    )
    return FamilyTestResult(
        statistic=observed,
        p_value=family_p,
        candidate_statistics=tuple(float(value) for value in statistics),
        candidate_p_values=raw_p,
        resamples=resamples,
        seed=seed,
        method="HANSEN_SPA_STATIONARY_BOOTSTRAP",
        diagnostics=tuple(diagnostics),
    )


def romano_wolf_max_t(
    excess_returns: Sequence[Sequence[float]] | FloatArray,
    *,
    resamples: int = PROTOCOL_RESAMPLES,
    expected_block_length: float = 10.0,
    seed: int = PROTOCOL_SEED,
) -> RomanoWolfResult:
    """Step-down Romano-Wolf max-T adjusted one-sided p-values."""
    excess = _as_matrix(excess_returns, name="excess_returns")
    _validate_resampling(resamples, PROTOCOL_CONFIDENCE)
    means, standard_errors, statistics = _studentized_means(excess)
    valid = standard_errors > np.finfo(float).eps
    bootstrap_t = _bootstrap_centered_t(
        excess,
        means,
        standard_errors,
        resamples=resamples,
        expected_block_length=expected_block_length,
        seed=seed,
    )
    raw = np.ones(excess.shape[1], dtype=np.float64)
    for index in np.flatnonzero(valid):
        raw[index] = (1 + np.count_nonzero(bootstrap_t[:, index] >= statistics[index])) / (
            resamples + 1
        )
    order = np.argsort(-statistics, kind="stable")
    adjusted = np.ones(excess.shape[1], dtype=np.float64)
    running = 0.0
    for position, index in enumerate(order):
        if not valid[index]:
            adjusted[index] = 1.0
            continue
        remaining = order[position:]
        remaining = remaining[valid[remaining]]
        maxima = np.max(bootstrap_t[:, remaining], axis=1)
        step_p = float((1 + np.count_nonzero(maxima >= statistics[index])) / (resamples + 1))
        running = max(running, step_p)
        adjusted[index] = min(1.0, max(raw[index], running))
    diagnostics = (
        (f"ZERO_VARIANCE_CANDIDATES={int(np.count_nonzero(~valid))}",) if not np.all(valid) else ()
    )
    return RomanoWolfResult(
        raw_p_values=tuple(float(value) for value in raw),
        adjusted_p_values=tuple(float(value) for value in adjusted),
        t_statistics=tuple(float(value) for value in statistics),
        resamples=resamples,
        seed=seed,
        diagnostics=diagnostics,
    )


def _validate_p_values(p_values: Sequence[float], alpha: float) -> FloatArray:
    values = _as_vector(p_values, name="p_values")
    if np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("p_values must lie in [0, 1]")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    return values


def holm_correction(p_values: Sequence[float], *, alpha: float = 0.05) -> MultipleTestingResult:
    """Holm step-down family-wise error correction (primary adjustment)."""
    values = _validate_p_values(p_values, alpha)
    count = len(values)
    order = np.argsort(values, kind="stable")
    adjusted = np.empty(count, dtype=np.float64)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return MultipleTestingResult(
        raw_p_values=tuple(float(value) for value in values),
        adjusted_p_values=tuple(float(value) for value in adjusted),
        rejected=tuple(bool(value <= alpha) for value in adjusted),
        alpha=alpha,
        method="HOLM_FWER",
    )


def benjamini_hochberg(p_values: Sequence[float], *, alpha: float = 0.05) -> MultipleTestingResult:
    """Benjamini-Hochberg FDR correction (protocol sensitivity analysis only)."""
    values = _validate_p_values(p_values, alpha)
    count = len(values)
    order = np.argsort(values, kind="stable")
    adjusted = np.empty(count, dtype=np.float64)
    running = 1.0
    for rank in range(count - 1, -1, -1):
        index = order[rank]
        running = min(running, count * values[index] / (rank + 1))
        adjusted[index] = min(1.0, running)
    return MultipleTestingResult(
        raw_p_values=tuple(float(value) for value in values),
        adjusted_p_values=tuple(float(value) for value in adjusted),
        rejected=tuple(bool(value <= alpha) for value in adjusted),
        alpha=alpha,
        method="BENJAMINI_HOCHBERG_FDR_SENSITIVITY",
    )


def probabilistic_sharpe_ratio(
    returns: Sequence[float] | FloatArray,
    *,
    reference_sharpe: float = 0.0,
    annualization: int = TRADING_DAYS,
) -> SharpeProbabilityResult:
    """Probability that the annualized Sharpe exceeds a reference Sharpe."""
    array = _as_vector(returns, name="returns", minimum=3)
    if annualization < 1 or not math.isfinite(reference_sharpe):
        raise ValueError("annualization and reference_sharpe must be valid")
    sample_std = float(np.std(array, ddof=1))
    if sample_std <= np.finfo(float).eps:
        return SharpeProbabilityResult(
            observed_sharpe=0.0,
            reference_sharpe=reference_sharpe,
            probability=0.5,
            observations=len(array),
            method="PROBABILISTIC_SHARPE_RATIO",
            diagnostics=("DEGENERATE_RETURN_VARIANCE",),
        )
    daily_sharpe = float(np.mean(array) / sample_std)
    skewness = float(stats.skew(array, bias=False))
    kurtosis = float(stats.kurtosis(array, fisher=False, bias=False))
    variance_term = (1.0 - skewness * daily_sharpe + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2) / (
        len(array) - 1
    )
    if variance_term <= np.finfo(float).eps:
        return SharpeProbabilityResult(
            observed_sharpe=daily_sharpe * math.sqrt(annualization),
            reference_sharpe=reference_sharpe,
            probability=0.5,
            observations=len(array),
            method="PROBABILISTIC_SHARPE_RATIO",
            diagnostics=("DEGENERATE_SHARPE_VARIANCE",),
        )
    reference_daily = reference_sharpe / math.sqrt(annualization)
    probability = float(stats.norm.cdf((daily_sharpe - reference_daily) / math.sqrt(variance_term)))
    return SharpeProbabilityResult(
        observed_sharpe=daily_sharpe * math.sqrt(annualization),
        reference_sharpe=reference_sharpe,
        probability=probability,
        observations=len(array),
        method="PROBABILISTIC_SHARPE_RATIO",
    )


def deflated_sharpe_ratio(
    returns: Sequence[float] | FloatArray,
    trial_sharpes: Sequence[float],
    *,
    annualization: int = TRADING_DAYS,
) -> SharpeProbabilityResult:
    """DSR probability using the expected maximum Sharpe across frozen trials."""
    trials = _as_vector(trial_sharpes, name="trial_sharpes")
    if annualization < 1:
        raise ValueError("annualization must be positive")
    diagnostics: list[str] = []
    trial_scale = float(np.std(trials, ddof=1)) if len(trials) > 1 else 0.0
    if len(trials) < 2 or trial_scale <= np.finfo(float).eps:
        expected_maximum = float(np.mean(trials))
        diagnostics.append("TRIAL_SHARPE_DISPERSION_UNAVAILABLE")
    else:
        count = len(trials)
        euler_gamma = 0.5772156649015329
        expected_standard_max = (1.0 - euler_gamma) * stats.norm.ppf(
            1.0 - 1.0 / count
        ) + euler_gamma * stats.norm.ppf(1.0 - 1.0 / (count * math.e))
        expected_maximum = float(np.mean(trials) + trial_scale * expected_standard_max)
    psr = probabilistic_sharpe_ratio(
        returns, reference_sharpe=expected_maximum, annualization=annualization
    )
    return SharpeProbabilityResult(
        observed_sharpe=psr.observed_sharpe,
        reference_sharpe=expected_maximum,
        probability=psr.probability,
        observations=psr.observations,
        method="DEFLATED_SHARPE_RATIO_PROBABILITY",
        diagnostics=tuple(diagnostics) + psr.diagnostics,
    )


def probability_of_backtest_overfitting(
    candidate_returns: Sequence[Sequence[float]] | FloatArray,
    *,
    slices: int = 10,
) -> PboResult:
    """CSCV estimate of PBO for a frozen candidate family.

    Rows are chronological observations and columns are candidates. For each
    symmetric train/test split, the in-sample winner is ranked out of sample.
    """
    returns = _as_matrix(candidate_returns, name="candidate_returns", minimum_rows=4)
    if slices < 2 or slices % 2 != 0 or slices > len(returns):
        raise ValueError("slices must be even and between two and the observation count")
    boundaries = np.linspace(0, len(returns), slices + 1, dtype=int)
    blocks = [np.arange(boundaries[index], boundaries[index + 1]) for index in range(slices)]
    if any(len(block) == 0 for block in blocks):
        raise ValueError("all chronological slices must contain observations")
    logits: list[float] = []
    half = slices // 2
    all_blocks = set(range(slices))
    for train_blocks in itertools.combinations(range(slices), half):
        test_blocks = sorted(all_blocks.difference(train_blocks))
        train_index = np.concatenate([blocks[index] for index in train_blocks])
        test_index = np.concatenate([blocks[index] for index in test_blocks])
        train_score = _column_sharpes(returns[train_index])
        winner = int(np.argmax(train_score))
        test_score = _column_sharpes(returns[test_index])
        # Mid-rank percentile in (0, 1), where one is the best OOS candidate.
        rank = 1 + int(np.count_nonzero(test_score < test_score[winner]))
        ties = int(np.count_nonzero(test_score == test_score[winner]))
        percentile = (rank - 0.5 + 0.5 * (ties - 1)) / returns.shape[1]
        percentile = min(1.0 - 1e-12, max(1e-12, percentile))
        logits.append(float(math.log(percentile / (1.0 - percentile))))
    probability = float(np.mean(np.asarray(logits) <= 0.0))
    diagnostics: tuple[str, ...] = ()
    if np.all(np.std(returns, axis=0) <= np.finfo(float).eps):
        diagnostics = ("CONSTANT_FAMILY_TIE_BREAK_BY_COLUMN_ORDER",)
    return PboResult(
        probability=probability,
        logits=tuple(logits),
        combinations=len(logits),
        slices=slices,
        diagnostics=diagnostics,
    )


def _column_sharpes(values: FloatArray) -> FloatArray:
    means = np.mean(values, axis=0)
    standard_deviations = np.std(values, axis=0, ddof=1)
    scores = np.zeros(values.shape[1], dtype=np.float64)
    valid = standard_deviations > np.finfo(float).eps
    scores[valid] = means[valid] / standard_deviations[valid]
    return scores


def calculate_return_metrics(
    returns: Sequence[float] | FloatArray,
    dates: Sequence[object] | NDArray[np.datetime64],
    *,
    annualization: int = TRADING_DAYS,
) -> ReturnMetrics:
    """Calculate the return-derived metrics frozen by the Gate F.0 protocol."""
    array = _as_vector(returns, name="returns", minimum=2)
    if np.any(array <= -1.0):
        raise ValueError("simple returns must be greater than -1")
    if annualization < 1:
        raise ValueError("annualization must be positive")
    date_array = np.asarray(dates, dtype="datetime64[D]")
    if date_array.ndim != 1 or len(date_array) != len(array) or np.isnat(date_array).any():
        raise ValueError("dates must be valid and aligned with returns")
    nav = np.cumprod(1.0 + array)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], nav)))[1:]
    drawdowns = nav / running_peak - 1.0
    maximum_drawdown = float(-np.min(drawdowns))
    years = len(array) / annualization
    annualized_return = float(nav[-1] ** (1.0 / years) - 1.0)
    daily_volatility = float(np.std(array, ddof=1))
    annualized_volatility = daily_volatility * math.sqrt(annualization)
    diagnostics: list[str] = []
    if daily_volatility <= np.finfo(float).eps:
        sharpe = 0.0
        diagnostics.append("DEGENERATE_RETURN_VARIANCE")
    else:
        sharpe = float(np.mean(array) / daily_volatility * math.sqrt(annualization))
    downside_deviation = float(np.sqrt(np.mean(np.minimum(array, 0.0) ** 2)))
    if downside_deviation <= np.finfo(float).eps:
        sortino = 0.0
        diagnostics.append("NO_DOWNSIDE_DEVIATION")
    else:
        sortino = float(np.mean(array) / downside_deviation * math.sqrt(annualization))
    if maximum_drawdown <= np.finfo(float).eps:
        calmar = 0.0
        diagnostics.append("NO_DRAWDOWN_FOR_CALMAR")
    else:
        calmar = annualized_return / maximum_drawdown
    time_under_water = float(np.mean(drawdowns < 0.0))
    threshold = float(np.quantile(array, 0.05))
    cvar = float(np.mean(array[array <= threshold]))
    skewness = float(stats.skew(array, bias=False)) if daily_volatility > 0.0 else 0.0
    kurtosis = (
        float(stats.kurtosis(array, fisher=False, bias=False)) if daily_volatility > 0.0 else 3.0
    )
    months = date_array.astype("datetime64[M]")
    monthly = [float(np.prod(1.0 + array[months == month]) - 1.0) for month in np.unique(months)]
    calendar_years = date_array.astype("datetime64[Y]")
    yearly: list[tuple[int, float]] = []
    for year in np.unique(calendar_years):
        numeric_year = int(str(year))
        yearly.append((numeric_year, float(np.prod(1.0 + array[calendar_years == year]) - 1.0)))
    return ReturnMetrics(
        observations=len(array),
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        maximum_drawdown=maximum_drawdown,
        time_under_water=time_under_water,
        cvar_95=cvar,
        skew=skewness,
        kurtosis=kurtosis,
        hit_rate=float(np.mean(array > 0.0)),
        monthly_win_rate=float(np.mean(np.asarray(monthly) > 0.0)),
        yearly_returns=tuple(yearly),
        diagnostics=tuple(diagnostics),
    )
