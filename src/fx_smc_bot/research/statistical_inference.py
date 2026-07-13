"""Dependence-aware statistical inference for backtest evaluation.

Implements bootstrap confidence intervals, Probabilistic/Deflated Sharpe
Ratio, minimum track record length, and block bootstrap methods that
respect the non-IID nature of financial time series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy import stats


@dataclass(frozen=True, slots=True)
class BootstrapCI:
    """Confidence interval from bootstrap."""

    statistic: str
    point_estimate: float
    lower: float
    upper: float
    confidence_level: float
    n_bootstrap: int
    method: str


def stationary_bootstrap(
    data: NDArray[np.float64],
    statistic_fn,
    n_bootstrap: int = 10_000,
    expected_block_length: float = 5.0,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapCI:
    """Stationary bootstrap for dependent time series.

    Uses geometrically distributed block lengths (Politis & Romano, 1994)
    rather than fixed blocks, producing stationary resampled series.

    Parameters
    ----------
    data : 1-D array of observations (e.g. daily returns)
    statistic_fn : callable(array) -> float
    expected_block_length : average block length (controls dependence)
    """
    rng = np.random.default_rng(seed)
    n = len(data)
    if n == 0:
        return BootstrapCI(
            statistic="", point_estimate=0.0, lower=0.0, upper=0.0,
            confidence_level=confidence, n_bootstrap=n_bootstrap,
            method="stationary_bootstrap",
        )

    point = float(statistic_fn(data))
    p = 1.0 / expected_block_length
    boot_stats = np.empty(n_bootstrap)

    for b in range(n_bootstrap):
        resampled = np.empty(n)
        idx = rng.integers(0, n)
        for i in range(n):
            resampled[i] = data[idx]
            if rng.random() < p:
                idx = rng.integers(0, n)
            else:
                idx = (idx + 1) % n
        boot_stats[b] = statistic_fn(resampled)

    alpha = 1 - confidence
    lower = float(np.percentile(boot_stats, 100 * alpha / 2))
    upper = float(np.percentile(boot_stats, 100 * (1 - alpha / 2)))

    return BootstrapCI(
        statistic="", point_estimate=point, lower=lower, upper=upper,
        confidence_level=confidence, n_bootstrap=n_bootstrap,
        method="stationary_bootstrap",
    )


def block_bootstrap(
    data: NDArray[np.float64],
    statistic_fn,
    block_size: int = 5,
    n_bootstrap: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapCI:
    """Moving block bootstrap (Kunsch, 1989).

    Divides data into overlapping blocks and resamples blocks.
    """
    rng = np.random.default_rng(seed)
    n = len(data)
    if n == 0 or block_size > n:
        return BootstrapCI(
            statistic="", point_estimate=0.0, lower=0.0, upper=0.0,
            confidence_level=confidence, n_bootstrap=n_bootstrap,
            method="block_bootstrap",
        )

    point = float(statistic_fn(data))
    n_blocks = max(1, n // block_size)
    max_start = n - block_size
    boot_stats = np.empty(n_bootstrap)

    for b in range(n_bootstrap):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        resampled = np.concatenate([data[s:s + block_size] for s in starts])[:n]
        boot_stats[b] = statistic_fn(resampled)

    alpha = 1 - confidence
    lower = float(np.percentile(boot_stats, 100 * alpha / 2))
    upper = float(np.percentile(boot_stats, 100 * (1 - alpha / 2)))

    return BootstrapCI(
        statistic="", point_estimate=point, lower=lower, upper=upper,
        confidence_level=confidence, n_bootstrap=n_bootstrap,
        method="block_bootstrap",
    )


def sharpe_ratio(returns: NDArray[np.float64], annual_factor: float = 252.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    mean = np.mean(returns)
    std = np.std(returns, ddof=1)
    if std == 0:
        return 0.0
    return float(mean / std * np.sqrt(annual_factor))


def sortino_ratio(returns: NDArray[np.float64], annual_factor: float = 252.0) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(returns) < 2:
        return 0.0
    mean = np.mean(returns)
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf") if mean > 0 else 0.0
    dd = np.sqrt(np.mean(downside ** 2))
    if dd == 0:
        return 0.0
    return float(mean / dd * np.sqrt(annual_factor))


def probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probabilistic Sharpe Ratio (Bailey & Lopez de Prado, 2012).

    Returns the probability that the observed SR exceeds the benchmark SR
    given estimation uncertainty from finite sample.
    """
    if n_observations < 3:
        return 0.5

    se = np.sqrt(
        (1.0 + 0.5 * observed_sr ** 2 - skewness * observed_sr
         + (kurtosis - 3) / 4.0 * observed_sr ** 2)
        / (n_observations - 1)
    )
    if se <= 0:
        return 0.5

    z = (observed_sr - benchmark_sr) / se
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    observed_sr: float,
    n_observations: int,
    n_trials: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    variance_of_srs: float | None = None,
) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Adjusts for multiple testing by computing the expected maximum
    Sharpe ratio under the null across n_trials independent tests.
    """
    if n_trials <= 0 or n_observations < 3:
        return 0.5

    if variance_of_srs is None:
        variance_of_srs = 1.0

    euler_mascheroni = 0.5772156649
    expected_max_sr = (
        variance_of_srs ** 0.5
        * ((1 - euler_mascheroni) * stats.norm.ppf(1 - 1.0 / n_trials)
           + euler_mascheroni * stats.norm.ppf(1 - 1.0 / (n_trials * math.e)))
    )

    return probabilistic_sharpe_ratio(
        observed_sr, expected_max_sr, n_observations, skewness, kurtosis,
    )


def minimum_track_record_length(
    observed_sr: float,
    benchmark_sr: float = 0.0,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    confidence: float = 0.95,
) -> float:
    """Minimum Track Record Length (Bailey & Lopez de Prado, 2012).

    Returns the minimum number of observations needed to conclude
    that observed_sr exceeds benchmark_sr with given confidence.
    """
    z_alpha = stats.norm.ppf(confidence)
    sr_diff = observed_sr - benchmark_sr
    if abs(sr_diff) < 1e-10:
        return float("inf")

    numer = (
        1 + 0.5 * observed_sr ** 2
        - skewness * observed_sr
        + (kurtosis - 3) / 4.0 * observed_sr ** 2
    )
    return float(1 + numer * (z_alpha / sr_diff) ** 2)


def var_cvar(
    returns: NDArray[np.float64],
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Value at Risk and Conditional VaR (Expected Shortfall).

    Returns (VaR, CVaR) at the given alpha level.
    VaR is the alpha-quantile loss. CVaR is the average loss beyond VaR.
    """
    if len(returns) == 0:
        return 0.0, 0.0
    sorted_returns = np.sort(returns)
    var_idx = int(np.floor(alpha * len(sorted_returns)))
    var_idx = max(0, min(var_idx, len(sorted_returns) - 1))
    var_val = float(sorted_returns[var_idx])
    tail = sorted_returns[:var_idx + 1]
    cvar = float(np.mean(tail)) if len(tail) > 0 else var_val
    return var_val, cvar


@dataclass(slots=True)
class InferenceReport:
    """Comprehensive statistical inference report."""

    n_observations: int = 0
    sharpe: float = 0.0
    sharpe_ci: BootstrapCI | None = None
    sortino: float = 0.0
    psr: float = 0.5
    dsr: float = 0.5
    min_track_record: float = float("inf")
    var_5pct: float = 0.0
    cvar_5pct: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 3.0
    profit_factor: float = 0.0
    profit_factor_ci: BootstrapCI | None = None
    win_rate: float = 0.0
    win_rate_ci: BootstrapCI | None = None


def build_inference_report(
    daily_returns: NDArray[np.float64],
    n_trials: int = 1,
    benchmark_sr: float = 0.0,
    n_bootstrap: int = 5_000,
    block_length: float = 5.0,
    confidence: float = 0.95,
    seed: int = 42,
) -> InferenceReport:
    """Build a full statistical inference report from daily returns."""
    n = len(daily_returns)
    if n < 5:
        return InferenceReport(n_observations=n)

    sr = sharpe_ratio(daily_returns)
    sort_r = sortino_ratio(daily_returns)
    skew = float(stats.skew(daily_returns))
    kurt = float(stats.kurtosis(daily_returns, fisher=False))

    sr_ci = stationary_bootstrap(
        daily_returns, sharpe_ratio,
        n_bootstrap=n_bootstrap, expected_block_length=block_length,
        confidence=confidence, seed=seed,
    )
    sr_ci = BootstrapCI(
        statistic="sharpe_ratio", point_estimate=sr_ci.point_estimate,
        lower=sr_ci.lower, upper=sr_ci.upper,
        confidence_level=sr_ci.confidence_level,
        n_bootstrap=sr_ci.n_bootstrap, method=sr_ci.method,
    )

    psr = probabilistic_sharpe_ratio(sr, benchmark_sr, n, skew, kurt)
    dsr = deflated_sharpe_ratio(sr, n, n_trials, skew, kurt)
    mtrl = minimum_track_record_length(sr, benchmark_sr, skew, kurt, confidence)
    v, cv = var_cvar(daily_returns)

    def _profit_factor(arr):
        gains = np.sum(arr[arr > 0])
        losses = abs(np.sum(arr[arr < 0]))
        return float(gains / losses) if losses > 0 else float("inf")

    def _win_rate(arr):
        return float(np.mean(arr > 0)) if len(arr) > 0 else 0.0

    pf = _profit_factor(daily_returns)
    pf_ci = stationary_bootstrap(
        daily_returns, _profit_factor,
        n_bootstrap=n_bootstrap, expected_block_length=block_length,
        confidence=confidence, seed=seed + 1,
    )
    pf_ci = BootstrapCI(
        statistic="profit_factor", point_estimate=pf_ci.point_estimate,
        lower=pf_ci.lower, upper=pf_ci.upper,
        confidence_level=pf_ci.confidence_level,
        n_bootstrap=pf_ci.n_bootstrap, method=pf_ci.method,
    )

    wr = _win_rate(daily_returns)
    wr_ci = stationary_bootstrap(
        daily_returns, _win_rate,
        n_bootstrap=n_bootstrap, expected_block_length=block_length,
        confidence=confidence, seed=seed + 2,
    )
    wr_ci = BootstrapCI(
        statistic="win_rate", point_estimate=wr_ci.point_estimate,
        lower=wr_ci.lower, upper=wr_ci.upper,
        confidence_level=wr_ci.confidence_level,
        n_bootstrap=wr_ci.n_bootstrap, method=wr_ci.method,
    )

    return InferenceReport(
        n_observations=n,
        sharpe=sr, sharpe_ci=sr_ci,
        sortino=sort_r,
        psr=psr, dsr=dsr,
        min_track_record=mtrl,
        var_5pct=v, cvar_5pct=cv,
        skewness=skew, kurtosis=kurt,
        profit_factor=pf, profit_factor_ci=pf_ci,
        win_rate=wr, win_rate_ci=wr_ci,
    )
