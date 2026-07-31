from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from fx_smc_bot.research.classical_fx_factors import (
    BASE_FACTOR_IDS,
    CARRY_ID,
    DONCHIAN_ID,
    FACTOR_RISK_WEIGHTS,
    MISSING_REQUIRED_SIGNAL_INPUT,
    MULTI_FACTOR_SIGNAL_PROXY_ID,
    REVERSAL_ID,
    TREND_ID,
    TSMOM_ID,
    ZERO_HORIZON_RETURN_SIGN_AMBIGUITY,
    FactorSignalResult,
    compute_donchian_breakout,
    compute_dual_horizon_trend,
    compute_fixed_multi_factor,
    compute_fixed_signal_weight_proxy,
    compute_rate_differential_carry,
    compute_short_term_reversal,
    compute_tsmom_composite,
)


def _prices(size: int = 400) -> pd.Series:
    index = pd.date_range("2000-01-03", periods=size, freq="B")
    values = 1.1 * np.exp(np.linspace(0.0, 0.25, size) + 0.01 * np.sin(np.arange(size)))
    return pd.Series(values, index=index, name="close")


def _assert_future_perturbation_does_not_change_past(
    compute: Callable[[pd.Series], FactorSignalResult],
) -> None:
    original = _prices()
    cutoff = 300
    perturbed = original.copy()
    perturbed.iloc[cutoff + 1 :] *= np.linspace(2.0, 5.0, len(perturbed) - cutoff - 1)
    pd.testing.assert_series_equal(
        compute(original).signal.iloc[: cutoff + 1],
        compute(perturbed).signal.iloc[: cutoff + 1],
    )


@pytest.mark.parametrize(
    "compute",
    [compute_tsmom_composite, compute_short_term_reversal, compute_dual_horizon_trend],
)
def test_close_factors_do_not_look_ahead(
    compute: Callable[[pd.Series], FactorSignalResult],
) -> None:
    _assert_future_perturbation_does_not_change_past(compute)


def test_tsmom_uses_all_frozen_lookbacks_and_t_minus_one() -> None:
    close = pd.Series(np.exp(np.linspace(0.0, 0.25, 260)), dtype=float)
    result = compute_tsmom_composite(close)

    assert result.signal.iloc[:253].isna().all()
    assert result.signal.iloc[253] == 1.0
    assert set(result.signal.dropna().unique()).issubset({-1.0, -0.5, 0.0, 0.5, 1.0})
    assert result.reason.iloc[252] == MISSING_REQUIRED_SIGNAL_INPUT
    assert pd.isna(result.reason.iloc[253])
    assert result.signal.name == TSMOM_ID


def test_tsmom_exact_zero_return_is_unavailable_not_quarter_step() -> None:
    close = pd.Series(np.ones(260), dtype=float)
    result = compute_tsmom_composite(close)
    assert result.signal.iloc[253:].isna().all()
    assert result.reason.iloc[253] == ZERO_HORIZON_RETURN_SIGN_AMBIGUITY


def test_reversal_has_exact_warmup_clips_and_does_not_fill_missing_prices() -> None:
    close = _prices(100)
    close.iloc[80] = close.iloc[79] * 10.0
    result = compute_short_term_reversal(close)

    assert result.signal.iloc[:61].isna().all()
    assert result.signal.iloc[61:].notna().any()
    assert result.signal.dropna().between(-1.0, 1.0).all()
    assert result.signal.iloc[81] == -1.0
    assert result.signal.name == REVERSAL_ID

    missing = close.copy()
    missing.iloc[75] = np.nan
    missing_result = compute_short_term_reversal(missing)
    assert pd.isna(missing_result.signal.iloc[76])
    assert missing_result.reason.iloc[76] == MISSING_REQUIRED_SIGNAL_INPUT


def test_trend_requires_slow_ema_warmup_and_clips() -> None:
    close = pd.Series(np.exp(np.linspace(0.0, 4.0, 260)))
    result = compute_dual_horizon_trend(close)

    assert result.signal.iloc[:200].isna().all()
    assert result.signal.iloc[200:].notna().all()
    assert result.signal.dropna().between(-1.0, 1.0).all()
    assert result.signal.iloc[200] == 1.0
    assert result.signal.name == TREND_ID


def test_donchian_channels_end_at_t_minus_two_and_state_persists() -> None:
    close = pd.Series(np.full(90, 9.5))
    high = pd.Series(np.full(90, 10.0))
    low = pd.Series(np.full(90, 9.0))
    close.iloc[55] = 10.5
    close.iloc[56:60] = 9.5
    close.iloc[60] = 8.5

    result = compute_donchian_breakout(close, high, low)

    assert result.signal.iloc[:56].isna().all()
    assert result.signal.iloc[56] == 1.0
    assert result.signal.iloc[57:61].eq(1.0).all()
    assert result.signal.iloc[61] == -1.0
    assert result.signal.name == DONCHIAN_ID


def test_donchian_does_not_look_ahead_and_missing_input_is_recorded() -> None:
    close = _prices()
    high = close * 1.001
    low = close * 0.999
    cutoff = 300
    original = compute_donchian_breakout(close, high, low)
    changed_close = close.copy()
    changed_high = high.copy()
    changed_low = low.copy()
    changed_close.iloc[cutoff + 1 :] *= 5.0
    changed_high.iloc[cutoff + 1 :] *= 6.0
    changed_low.iloc[cutoff + 1 :] *= 0.2
    changed = compute_donchian_breakout(changed_close, changed_high, changed_low)
    pd.testing.assert_series_equal(
        original.signal.iloc[: cutoff + 1], changed.signal.iloc[: cutoff + 1]
    )

    high.iloc[100] = np.nan
    missing = compute_donchian_breakout(close, high, low)
    assert pd.isna(missing.signal.iloc[102])
    assert missing.reason.iloc[102] == MISSING_REQUIRED_SIGNAL_INPUT


def test_rate_carry_is_lagged_clipped_and_missing_safe() -> None:
    index = pd.RangeIndex(5)
    base = pd.Series([0.00, 0.10, np.nan, -0.10, 0.01], index=index)
    quote = pd.Series([0.00, 0.00, 0.00, 0.00, 0.00], index=index)
    result = compute_rate_differential_carry(base, quote)

    expected = pd.Series([np.nan, 0.0, 1.0, np.nan, -1.0], name=CARRY_ID)
    pd.testing.assert_series_equal(result.signal, expected)
    assert result.reason.iloc[3] == MISSING_REQUIRED_SIGNAL_INPUT

    changed = base.copy()
    changed.iloc[4] = 99.0
    assert compute_rate_differential_carry(changed, quote).signal.iloc[4] == result.signal.iloc[4]


def test_fixed_multi_factor_hits_exact_ex_ante_risk_budgets_and_is_deterministic() -> None:
    assert tuple(FACTOR_RISK_WEIGHTS) == BASE_FACTOR_IDS
    assert tuple(FACTOR_RISK_WEIGHTS.values()) == (0.25, 0.15, 0.20, 0.15, 0.25)
    assert sum(FACTOR_RISK_WEIGHTS.values()) == 1.0

    instruments = pd.Index(["A", "B", "C", "D", "E"])
    sleeves = {
        factor_id: pd.Series(
            [1.0 if row == column else 0.0 for row in range(5)],
            index=instruments,
        )
        for column, factor_id in enumerate(BASE_FACTOR_IDS)
    }
    covariance = pd.DataFrame(
        np.diag([1.0, 4.0, 9.0, 16.0, 25.0]),
        index=instruments,
        columns=instruments,
    )
    kwargs = {
        "covariance_information_end": pd.Timestamp("2019-12-31"),
        "decision_time": pd.Timestamp("2020-01-01"),
    }
    first = compute_fixed_multi_factor(sleeves, covariance, **kwargs)
    second = compute_fixed_multi_factor(sleeves, covariance, **kwargs)

    expected = pd.Series(FACTOR_RISK_WEIGHTS, dtype=float)
    allocation = first.sleeve_allocations.to_numpy(dtype=float)
    sleeve_covariance = first.sleeve_covariance.to_numpy(dtype=float)
    marginal_risk = sleeve_covariance @ allocation
    recomputed_contributions = allocation * marginal_risk / (allocation @ marginal_risk)
    np.testing.assert_allclose(
        recomputed_contributions,
        expected.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-11,
    )
    pd.testing.assert_series_equal(
        first.normalized_risk_contributions,
        expected.rename("normalized_risk_contribution"),
        rtol=0.0,
        atol=1e-11,
    )
    pd.testing.assert_series_equal(first.target_positions, second.target_positions)
    pd.testing.assert_series_equal(first.sleeve_allocations, second.sleeve_allocations)
    pd.testing.assert_series_equal(
        first.normalized_risk_contributions,
        second.normalized_risk_contributions,
    )
    assert np.all(first.sleeve_allocations.to_numpy() > 0.0)
    assert first.sleeve_allocations.sum() == pytest.approx(1.0)

    with pytest.raises(ValueError, match="exactly the frozen factors"):
        compute_fixed_multi_factor({TSMOM_ID: sleeves[TSMOM_ID]}, covariance, **kwargs)


def test_nominal_signal_weighting_is_explicitly_only_a_proxy() -> None:
    values = {
        TSMOM_ID: pd.Series([1.0, 1.0]),
        REVERSAL_ID: pd.Series([-1.0, np.nan]),
        TREND_ID: pd.Series([0.5, 0.5]),
        DONCHIAN_ID: pd.Series([0.0, 0.0]),
        CARRY_ID: pd.Series([-0.5, -0.5]),
    }
    result = compute_fixed_signal_weight_proxy(values)
    assert result.signal.iloc[0] == pytest.approx(0.075)
    assert pd.isna(result.signal.iloc[1])
    assert result.reason.iloc[1] == MISSING_REQUIRED_SIGNAL_INPUT
    assert result.signal.name == MULTI_FACTOR_SIGNAL_PROXY_ID


def test_fixed_multi_factor_rejects_non_lagged_covariance() -> None:
    index = pd.Index(["A", "B", "C", "D", "E"])
    sleeves = {
        factor_id: pd.Series(np.eye(5)[column], index=index)
        for column, factor_id in enumerate(BASE_FACTOR_IDS)
    }
    covariance = pd.DataFrame(np.eye(5), index=index, columns=index)
    with pytest.raises(ValueError, match="strictly before"):
        compute_fixed_multi_factor(
            sleeves,
            covariance,
            covariance_information_end="2020-01-01",
            decision_time="2020-01-01",
        )


def test_inputs_must_be_numeric_unique_and_exactly_aligned() -> None:
    with pytest.raises(TypeError, match="numeric"):
        compute_tsmom_composite(pd.Series(["not-a-price"]))
    with pytest.raises(ValueError, match="unique"):
        compute_tsmom_composite(pd.Series([1.0, 2.0], index=[0, 0]))
    with pytest.raises(ValueError, match="same index"):
        compute_rate_differential_carry(pd.Series([0.01], index=[0]), pd.Series([0.01], index=[1]))
