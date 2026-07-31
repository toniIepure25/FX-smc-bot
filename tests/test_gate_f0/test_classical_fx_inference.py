from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from fx_smc_bot.research.classical_fx_inference import (
    PROTOCOL_HAC_LAG,
    PROTOCOL_RESAMPLES,
    PROTOCOL_SEED,
    benjamini_hochberg,
    calculate_return_metrics,
    deflated_sharpe_ratio,
    hansen_spa,
    holm_correction,
    month_cluster_bootstrap_ci,
    newey_west_hac_alpha,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    romano_wolf_max_t,
    stationary_bootstrap_ci,
    white_reality_check,
)

FAST_RESAMPLES = 199


def _sample_family(seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, size=(240, 6))


def _assert_finite_dataclass(result: object) -> None:
    assert dataclasses.is_dataclass(result)
    for field in dataclasses.fields(result):
        value = getattr(result, field.name)
        if isinstance(value, float):
            assert np.isfinite(value)
        elif isinstance(value, tuple) and value and all(isinstance(item, float) for item in value):
            assert np.all(np.isfinite(value))


def test_protocol_defaults_are_frozen() -> None:
    assert PROTOCOL_SEED == 1729
    assert PROTOCOL_RESAMPLES == 10_000
    assert PROTOCOL_HAC_LAG == 5


def test_stationary_bootstrap_is_deterministic_and_contains_point() -> None:
    values = np.sin(np.arange(180) / 9.0) * 0.01
    first = stationary_bootstrap_ci(values, resamples=FAST_RESAMPLES)
    second = stationary_bootstrap_ci(values, resamples=FAST_RESAMPLES)
    assert first == second
    assert first.lower <= first.point_estimate <= first.upper
    _assert_finite_dataclass(first)


def test_month_cluster_bootstrap_is_deterministic() -> None:
    dates = np.arange("2014-01-01", "2015-01-01", dtype="datetime64[D]")
    values = np.cos(np.arange(len(dates)) / 13.0) * 0.005
    first = month_cluster_bootstrap_ci(values, dates, resamples=FAST_RESAMPLES)
    second = month_cluster_bootstrap_ci(values, dates, resamples=FAST_RESAMPLES)
    assert first == second
    assert "CLUSTERS=12" in first.diagnostics


def test_bootstraps_reject_invalid_input() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        stationary_bootstrap_ci([0.0, np.nan], resamples=10)
    with pytest.raises(ValueError, match="two calendar months"):
        month_cluster_bootstrap_ci([0.0, 0.1], ["2012-01-01", "2012-01-02"], resamples=10)


def test_hac_alpha_recovers_intercept_and_is_finite() -> None:
    rng = np.random.default_rng(23)
    controls = rng.normal(0.0, 0.01, size=(800, 3))
    residual = rng.normal(0.0, 0.001, size=800)
    returns = 0.0004 + controls @ np.array([0.2, -0.1, 0.05]) + residual
    result = newey_west_hac_alpha(returns, controls)
    assert result.lag == 5
    assert result.alpha == pytest.approx(0.0004, abs=0.0001)
    assert 0.0 <= result.p_value <= 1.0
    _assert_finite_dataclass(result)


def test_hac_constant_series_reports_degeneracy_conservatively() -> None:
    result = newey_west_hac_alpha(np.zeros(30))
    assert result.standard_error == 0.0
    assert result.t_statistic == 0.0
    assert result.p_value == 1.0
    assert "DEGENERATE_HAC_VARIANCE" in result.diagnostics


def test_family_bootstrap_tests_are_deterministic_under_null() -> None:
    family = _sample_family()
    white_first = white_reality_check(family, resamples=FAST_RESAMPLES)
    white_second = white_reality_check(family, resamples=FAST_RESAMPLES)
    spa_first = hansen_spa(family, resamples=FAST_RESAMPLES)
    spa_second = hansen_spa(family, resamples=FAST_RESAMPLES)
    assert white_first == white_second
    assert spa_first == spa_second
    assert white_first.p_value > 0.01
    assert spa_first.p_value > 0.01
    _assert_finite_dataclass(white_first)
    _assert_finite_dataclass(spa_first)


def test_family_tests_do_not_claim_constant_null_is_significant() -> None:
    family = np.zeros((80, 6))
    white = white_reality_check(family, resamples=49)
    spa = hansen_spa(family, resamples=49)
    romano = romano_wolf_max_t(family, resamples=49)
    assert white.p_value == 1.0
    assert spa.p_value == 1.0
    assert romano.raw_p_values == (1.0,) * 6
    assert romano.adjusted_p_values == (1.0,) * 6


def test_romano_wolf_is_deterministic_and_adjusted_not_below_raw() -> None:
    family = _sample_family(41)
    family[:, 0] += 0.001
    first = romano_wolf_max_t(family, resamples=FAST_RESAMPLES)
    second = romano_wolf_max_t(family, resamples=FAST_RESAMPLES)
    assert first == second
    assert np.all(np.asarray(first.adjusted_p_values) >= np.asarray(first.raw_p_values))
    assert np.all(np.asarray(first.adjusted_p_values) <= 1.0)


def test_holm_and_bh_match_known_values_and_preserve_order() -> None:
    raw = [0.01, 0.04, 0.03, 0.002]
    holm = holm_correction(raw)
    bh = benjamini_hochberg(raw)
    assert holm.adjusted_p_values == pytest.approx((0.03, 0.06, 0.06, 0.008))
    assert bh.adjusted_p_values == pytest.approx((0.02, 0.04, 0.04, 0.008))
    assert holm.raw_p_values == tuple(raw)
    assert bh.raw_p_values == tuple(raw)
    assert "SENSITIVITY" in bh.method


def test_corrections_reject_invalid_p_values() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        holm_correction([0.1, 1.1])


def test_psr_and_dsr_probabilities_are_finite_and_ordered() -> None:
    rng = np.random.default_rng(101)
    returns = rng.normal(0.0005, 0.01, size=600)
    psr = probabilistic_sharpe_ratio(returns)
    dsr = deflated_sharpe_ratio(returns, [-0.2, 0.0, 0.1, 0.3, 0.5, 0.7])
    assert 0.0 <= dsr.probability <= psr.probability <= 1.0
    assert dsr.reference_sharpe > psr.reference_sharpe
    _assert_finite_dataclass(psr)
    _assert_finite_dataclass(dsr)


def test_psr_constant_series_is_neutral_with_diagnostic() -> None:
    result = probabilistic_sharpe_ratio(np.zeros(20))
    assert result.probability == 0.5
    assert "DEGENERATE_RETURN_VARIANCE" in result.diagnostics


def test_pbo_is_deterministic_and_bounded() -> None:
    family = _sample_family(88)
    first = probability_of_backtest_overfitting(family, slices=6)
    second = probability_of_backtest_overfitting(family, slices=6)
    assert first == second
    assert first.combinations == 20
    assert 0.0 <= first.probability <= 1.0
    assert np.all(np.isfinite(first.logits))


def test_pbo_rejects_non_symmetric_partition() -> None:
    with pytest.raises(ValueError, match="slices must be even"):
        probability_of_backtest_overfitting(_sample_family(), slices=5)


def test_return_metrics_follow_simple_return_conventions() -> None:
    dates = np.arange("2011-01-01", "2013-01-01", dtype="datetime64[D]")
    returns = np.sin(np.arange(len(dates)) / 5.0) * 0.005 + 0.0001
    metrics = calculate_return_metrics(returns, dates)
    assert metrics.observations == len(returns)
    assert metrics.maximum_drawdown >= 0.0
    assert 0.0 <= metrics.time_under_water <= 1.0
    assert 0.0 <= metrics.hit_rate <= 1.0
    assert 0.0 <= metrics.monthly_win_rate <= 1.0
    assert len(metrics.yearly_returns) == 2
    _assert_finite_dataclass(metrics)


def test_return_metrics_report_degenerate_conventions() -> None:
    dates = np.arange("2012-01-01", "2012-01-11", dtype="datetime64[D]")
    metrics = calculate_return_metrics(np.zeros(10), dates)
    assert metrics.sharpe == metrics.sortino == metrics.calmar == 0.0
    assert "DEGENERATE_RETURN_VARIANCE" in metrics.diagnostics
    assert "NO_DOWNSIDE_DEVIATION" in metrics.diagnostics
    assert "NO_DRAWDOWN_FOR_CALMAR" in metrics.diagnostics
