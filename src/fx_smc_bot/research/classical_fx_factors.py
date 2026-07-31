"""Deterministic, point-in-time factor signals for Gate F.0.

Every signal returned for decision date ``t`` uses inputs available through
``t-1``. Missing or undefined inputs remain unavailable; prices and rates are
never forward-filled by this module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, TypeAlias

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

TSMOM_ID: Final = "F0_TSMOM_COMPOSITE_V1"
REVERSAL_ID: Final = "F0_SHORT_TERM_REVERSAL_V1"
TREND_ID: Final = "F0_DUAL_HORIZON_TREND_V1"
DONCHIAN_ID: Final = "F0_DONCHIAN_BREAKOUT_V1"
CARRY_ID: Final = "F0_RATE_DIFFERENTIAL_CARRY_V1"
MULTI_FACTOR_ID: Final = "F0_FIXED_MULTI_FACTOR_V1"
MULTI_FACTOR_SIGNAL_PROXY_ID: Final = "F0_FIXED_MULTI_FACTOR_SIGNAL_WEIGHT_PROXY_NOT_CANDIDATE"

MISSING_REQUIRED_SIGNAL_INPUT: Final = "MISSING_REQUIRED_SIGNAL_INPUT"
ZERO_HORIZON_RETURN_SIGN_AMBIGUITY: Final = "ZERO_HORIZON_RETURN_SIGN_AMBIGUITY"

BASE_FACTOR_IDS: Final = (TSMOM_ID, REVERSAL_ID, TREND_ID, DONCHIAN_ID, CARRY_ID)
FACTOR_RISK_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        TSMOM_ID: 0.25,
        REVERSAL_ID: 0.15,
        TREND_ID: 0.20,
        DONCHIAN_ID: 0.15,
        CARRY_ID: 0.25,
    }
)


@dataclass(frozen=True)
class FactorSignalResult:
    """Signal values and the frozen reason recorded for unavailable decisions."""

    signal: pd.Series
    reason: pd.Series


@dataclass(frozen=True)
class FixedMultiFactorResult:
    """Candidate 6 portfolio and its ex-ante sleeve risk-budget audit."""

    target_positions: pd.Series
    sleeve_allocations: pd.Series
    normalized_risk_contributions: pd.Series
    sleeve_covariance: pd.DataFrame
    portfolio_variance: float
    covariance_information_end: pd.Timestamp
    decision_time: pd.Timestamp


SignalInput: TypeAlias = pd.Series | FactorSignalResult


def _as_float_series(values: pd.Series, argument: str) -> pd.Series:
    if not isinstance(values, pd.Series):
        raise TypeError(f"{argument} must be a pandas Series")
    if not values.index.is_unique:
        raise ValueError(f"{argument} index must be unique")
    try:
        result = pd.to_numeric(values, errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{argument} must contain numeric values") from exc
    return result.copy(deep=True)


def _require_same_index(reference: pd.Series, other: pd.Series, argument: str) -> None:
    if not reference.index.equals(other.index):
        raise ValueError(f"{argument} must have exactly the same index")


def _result(
    signal: pd.Series,
    candidate_id: str,
    reason_overrides: pd.Series | None = None,
) -> FactorSignalResult:
    clean = signal.astype(float).replace([np.inf, -np.inf], np.nan)
    clean.name = candidate_id
    reason = pd.Series(
        MISSING_REQUIRED_SIGNAL_INPUT,
        index=clean.index,
        dtype="string",
        name=f"{candidate_id}_reason",
    )
    reason.loc[clean.notna()] = pd.NA
    if reason_overrides is not None:
        _require_same_index(clean, reason_overrides, "reason_overrides")
        override_mask = clean.isna() & reason_overrides.notna()
        reason.loc[override_mask] = reason_overrides.loc[override_mask].astype("string")
    return FactorSignalResult(signal=clean, reason=reason)


def _lagged_daily_volatility(close: pd.Series, lookback: int = 60) -> pd.Series:
    daily_return = close.pct_change(fill_method=None)
    return daily_return.shift(1).rolling(lookback, min_periods=lookback).std(ddof=1)


def compute_tsmom_composite(close: pd.Series) -> FactorSignalResult:
    """Mean signs of frozen 21/63/126/252-day returns through ``t-1``."""
    prices = _as_float_series(close, "close")
    lagged_close = prices.shift(1)
    signed_returns: dict[int, pd.Series] = {}
    exact_zero = pd.Series(False, index=prices.index)
    for lookback in (21, 63, 126, 252):
        denominator = lagged_close.shift(lookback)
        returns = lagged_close.div(denominator).sub(1.0).where(denominator.ne(0.0))
        exact_zero |= returns.eq(0.0)
        signed_returns[lookback] = np.sign(returns)
    signal = pd.DataFrame(signed_returns, index=prices.index).mean(axis=1, skipna=False)
    signal = signal.mask(exact_zero)
    reason_overrides = pd.Series(pd.NA, index=prices.index, dtype="string")
    reason_overrides.loc[exact_zero] = ZERO_HORIZON_RETURN_SIGN_AMBIGUITY
    return _result(signal, TSMOM_ID, reason_overrides)


def compute_short_term_reversal(close: pd.Series) -> FactorSignalResult:
    """Frozen five-day reversal normalized by lagged 60-day daily volatility."""
    prices = _as_float_series(close, "close")
    lagged_close = prices.shift(1)
    five_day_denominator = lagged_close.shift(5)
    five_day_return = lagged_close.div(five_day_denominator).sub(1.0)
    five_day_return = five_day_return.where(five_day_denominator.ne(0.0))
    volatility = _lagged_daily_volatility(prices)
    denominator = np.sqrt(5.0) * volatility
    signal = (-five_day_return).div(denominator).where(denominator.gt(0.0)).clip(-1.0, 1.0)
    return _result(signal, REVERSAL_ID)


def compute_dual_horizon_trend(close: pd.Series) -> FactorSignalResult:
    """Frozen EMA(50)-EMA(200) trend normalized using information through ``t-1``."""
    prices = _as_float_series(close, "close")
    lagged_close = prices.shift(1)
    fast_ema = prices.ewm(span=50, adjust=False, min_periods=50).mean().shift(1)
    slow_ema = prices.ewm(span=200, adjust=False, min_periods=200).mean().shift(1)
    volatility = _lagged_daily_volatility(prices)
    denominator = lagged_close * volatility * np.sqrt(252.0)
    signal = fast_ema.sub(slow_ema).div(denominator)
    signal = signal.where(denominator.gt(0.0) & lagged_close.notna()).clip(-1.0, 1.0)
    return _result(signal, TREND_ID)


def compute_donchian_breakout(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> FactorSignalResult:
    """Stateful 55-day entry/20-day exit Donchian signal with frozen lags."""
    prices = _as_float_series(close, "close")
    highs = _as_float_series(high, "high")
    lows = _as_float_series(low, "low")
    _require_same_index(prices, highs, "high")
    _require_same_index(prices, lows, "low")

    comparison = prices.shift(1)
    entry_high = highs.shift(2).rolling(55, min_periods=55).max()
    entry_low = lows.shift(2).rolling(55, min_periods=55).min()
    exit_high = highs.shift(2).rolling(20, min_periods=20).max()
    exit_low = lows.shift(2).rolling(20, min_periods=20).min()
    required = (
        pd.concat([comparison, entry_high, entry_low, exit_high, exit_low], axis=1)
        .notna()
        .all(axis=1)
    )

    comparison_values = comparison.to_numpy(dtype=float)
    entry_high_values = entry_high.to_numpy(dtype=float)
    entry_low_values = entry_low.to_numpy(dtype=float)
    exit_high_values = exit_high.to_numpy(dtype=float)
    exit_low_values = exit_low.to_numpy(dtype=float)
    required_values = required.to_numpy(dtype=bool)
    output = np.full(len(prices), np.nan, dtype=float)
    state = 0.0

    for position in range(len(prices)):
        if not required_values[position]:
            continue
        long_entry = comparison_values[position] > entry_high_values[position]
        short_entry = comparison_values[position] < entry_low_values[position]
        long_exit = comparison_values[position] < exit_low_values[position]
        short_exit = comparison_values[position] > exit_high_values[position]

        if long_entry != short_entry:
            state = 1.0 if long_entry else -1.0
        elif not (long_exit and short_exit):
            if state == 1.0 and long_exit:
                state = 0.0
            elif state == -1.0 and short_exit:
                state = 0.0
        output[position] = state

    return _result(pd.Series(output, index=prices.index), DONCHIAN_ID)


def compute_rate_differential_carry(
    base_overnight_rate: pd.Series,
    quote_overnight_rate: pd.Series,
) -> FactorSignalResult:
    """Frozen, clipped base-minus-quote carry from eligible rates at ``t-1``."""
    base_rate = _as_float_series(base_overnight_rate, "base_overnight_rate")
    quote_rate = _as_float_series(quote_overnight_rate, "quote_overnight_rate")
    _require_same_index(base_rate, quote_rate, "quote_overnight_rate")
    signal = base_rate.shift(1).sub(quote_rate.shift(1)).div(0.05).clip(-1.0, 1.0)
    return _result(signal, CARRY_ID)


def compute_fixed_signal_weight_proxy(
    component_signals: Mapping[str, SignalInput],
) -> FactorSignalResult:
    """Return a nominal signal-weight proxy; this is not candidate 6."""
    if set(component_signals) != set(BASE_FACTOR_IDS):
        missing = sorted(set(BASE_FACTOR_IDS) - set(component_signals))
        extra = sorted(set(component_signals) - set(BASE_FACTOR_IDS))
        raise ValueError(
            f"component_signals must contain exactly the frozen factors; {missing=}, {extra=}"
        )

    extracted: dict[str, pd.Series] = {}
    reference: pd.Series | None = None
    for factor_id in BASE_FACTOR_IDS:
        value = component_signals[factor_id]
        series = value.signal if isinstance(value, FactorSignalResult) else value
        numeric = _as_float_series(series, factor_id)
        if reference is None:
            reference = numeric
        else:
            _require_same_index(reference, numeric, factor_id)
        extracted[factor_id] = numeric

    frame = pd.DataFrame(extracted, index=reference.index if reference is not None else None)
    weighted = frame.mul(pd.Series(FACTOR_RISK_WEIGHTS), axis="columns")
    signal = weighted.sum(axis=1, min_count=len(BASE_FACTOR_IDS))
    return _result(signal, MULTI_FACTOR_SIGNAL_PROXY_ID)


def _validate_lagged_covariance(
    covariance: pd.DataFrame,
    instruments: pd.Index,
) -> np.ndarray:
    if not isinstance(covariance, pd.DataFrame):
        raise TypeError("lagged_instrument_covariance must be a pandas DataFrame")
    if not covariance.index.is_unique or not covariance.columns.is_unique:
        raise ValueError("lagged_instrument_covariance labels must be unique")
    if set(covariance.index) != set(instruments) or set(covariance.columns) != set(instruments):
        raise ValueError("lagged_instrument_covariance must exactly cover sleeve instruments")
    values = covariance.loc[instruments, instruments].to_numpy(dtype=float)
    if not bool(np.isfinite(values).all()):
        raise ValueError("lagged_instrument_covariance must be finite")
    if not bool(np.allclose(values, values.T, rtol=0.0, atol=1e-14)):
        raise ValueError("lagged_instrument_covariance must be symmetric")
    eigenvalues = np.linalg.eigvalsh(values)
    tolerance = 1e-12 * max(1.0, float(np.abs(values).max(initial=0.0)))
    if float(eigenvalues.min(initial=0.0)) < -tolerance:
        raise ValueError("lagged_instrument_covariance must be positive semidefinite")
    return values


def _risk_budget_allocations(
    sleeve_covariance: np.ndarray,
    targets: np.ndarray,
    *,
    tolerance: float = 1e-11,
    maximum_iterations: int = 20_000,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Solve the convex risk-budgeting equations by deterministic CCD."""

    diagonal = np.diag(sleeve_covariance)
    if bool(np.any(diagonal <= 0.0)):
        raise ValueError("Every factor sleeve must have strictly positive ex-ante variance")
    allocations = np.sqrt(targets / diagonal)
    for _ in range(maximum_iterations):
        for index in range(len(targets)):
            cross_term = float(sleeve_covariance[index] @ allocations)
            cross_term -= float(diagonal[index] * allocations[index])
            discriminant = cross_term * cross_term + 4.0 * diagonal[index] * targets[index]
            allocations[index] = 2.0 * targets[index] / (math.sqrt(discriminant) + cross_term)

        marginal = sleeve_covariance @ allocations
        contributions = allocations * marginal
        variance = float(allocations @ marginal)
        if variance <= 0.0 or not math.isfinite(variance):
            raise ValueError("Factor sleeve covariance produces non-positive portfolio variance")
        normalized = contributions / variance
        if bool(np.max(np.abs(normalized - targets)) <= tolerance):
            allocations /= float(allocations.sum())
            marginal = sleeve_covariance @ allocations
            contributions = allocations * marginal
            variance = float(allocations @ marginal)
            return allocations, contributions / variance, variance
    raise RuntimeError("Deterministic factor risk-budget allocator did not converge")


def compute_fixed_multi_factor(
    component_sleeves: Mapping[str, pd.Series],
    lagged_instrument_covariance: pd.DataFrame,
    *,
    covariance_information_end: pd.Timestamp | str,
    decision_time: pd.Timestamp | str,
) -> FixedMultiFactorResult:
    """Combine five portfolio sleeves at the frozen ex-ante risk budgets.

    The allocator uses only the supplied lagged covariance and fixed risk
    targets. It does not inspect returns, PnL, or any performance objective.
    """

    if set(component_sleeves) != set(BASE_FACTOR_IDS):
        missing = sorted(set(BASE_FACTOR_IDS) - set(component_sleeves))
        extra = sorted(set(component_sleeves) - set(BASE_FACTOR_IDS))
        raise ValueError(
            f"component_sleeves must contain exactly the frozen factors; {missing=}, {extra=}"
        )
    information_end = pd.Timestamp(covariance_information_end)
    decision = pd.Timestamp(decision_time)
    if information_end >= decision:
        raise ValueError("Covariance information must end strictly before the decision time")

    extracted: dict[str, pd.Series] = {}
    reference: pd.Series | None = None
    for factor_id in BASE_FACTOR_IDS:
        numeric = _as_float_series(component_sleeves[factor_id], factor_id)
        if reference is None:
            reference = numeric
        else:
            _require_same_index(reference, numeric, factor_id)
        if not bool(np.isfinite(numeric.to_numpy(dtype=float)).all()):
            raise ValueError(f"{factor_id} sleeve must be complete and finite")
        extracted[factor_id] = numeric
    if reference is None or reference.empty:
        raise ValueError("Factor sleeves must not be empty")

    instrument_covariance = _validate_lagged_covariance(
        lagged_instrument_covariance,
        reference.index,
    )
    sleeve_frame = pd.DataFrame(extracted, index=reference.index)
    sleeve_matrix = sleeve_frame.to_numpy(dtype=float)
    sleeve_covariance_values = sleeve_matrix.T @ instrument_covariance @ sleeve_matrix
    targets = np.asarray([FACTOR_RISK_WEIGHTS[name] for name in BASE_FACTOR_IDS], dtype=float)
    allocations, normalized_contributions, portfolio_variance = _risk_budget_allocations(
        sleeve_covariance_values,
        targets,
    )
    allocation_series = pd.Series(
        allocations,
        index=BASE_FACTOR_IDS,
        name="sleeve_allocation",
        dtype=float,
    )
    contribution_series = pd.Series(
        normalized_contributions,
        index=BASE_FACTOR_IDS,
        name="normalized_risk_contribution",
        dtype=float,
    )
    target_positions = sleeve_frame.mul(allocation_series, axis="columns").sum(axis=1)
    target_positions.name = MULTI_FACTOR_ID
    sleeve_covariance = pd.DataFrame(
        sleeve_covariance_values,
        index=BASE_FACTOR_IDS,
        columns=BASE_FACTOR_IDS,
        dtype=float,
    )
    return FixedMultiFactorResult(
        target_positions=target_positions,
        sleeve_allocations=allocation_series,
        normalized_risk_contributions=contribution_series,
        sleeve_covariance=sleeve_covariance,
        portfolio_variance=portfolio_variance,
        covariance_information_end=information_end,
        decision_time=decision,
    )


__all__ = [
    "BASE_FACTOR_IDS",
    "CARRY_ID",
    "DONCHIAN_ID",
    "FACTOR_RISK_WEIGHTS",
    "FactorSignalResult",
    "FixedMultiFactorResult",
    "MISSING_REQUIRED_SIGNAL_INPUT",
    "MULTI_FACTOR_ID",
    "MULTI_FACTOR_SIGNAL_PROXY_ID",
    "REVERSAL_ID",
    "TREND_ID",
    "TSMOM_ID",
    "ZERO_HORIZON_RETURN_SIGN_AMBIGUITY",
    "compute_donchian_breakout",
    "compute_dual_horizon_trend",
    "compute_fixed_multi_factor",
    "compute_fixed_signal_weight_proxy",
    "compute_rate_differential_carry",
    "compute_short_term_reversal",
    "compute_tsmom_composite",
]
