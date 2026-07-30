import numpy as np

from fx_smc_bot.research.quant_polarity_inference import (
    cluster_bootstrap_mean_ci,
    corrected_p_values,
    hansen_spa_p_value,
    matched_entry_permutation_p_value,
    newey_west_factor_alpha,
    romano_wolf_max_t,
)


def test_cluster_bootstrap_is_deterministic() -> None:
    values = [1.0, 2.0, -1.0, 0.5]
    clusters = ["a", "a", "b", "b"]
    first = cluster_bootstrap_mean_ci(values, clusters, iterations=200)
    second = cluster_bootstrap_mean_ci(values, clusters, iterations=200)
    assert first == second


def test_matched_permutation_is_deterministic() -> None:
    first = matched_entry_permutation_p_value([1, 2, 3], [0, 0, 0], iterations=200)
    second = matched_entry_permutation_p_value([1, 2, 3], [0, 0, 0], iterations=200)
    assert first == second


def test_hac_alpha_uses_frozen_lag() -> None:
    returns = np.linspace(-0.1, 0.2, 30)
    factors = np.column_stack([np.linspace(0, 1, 30)] * 4)
    result = newey_west_factor_alpha(returns, factors)
    assert result.lag == 5
    assert result.observations == 30


def test_multiple_testing_adjustments_are_bounded() -> None:
    corrections = corrected_p_values([0.01, 0.04, 0.2])
    assert all(0 <= value <= 1 for values in corrections.values() for value in values)
    adjusted = romano_wolf_max_t([2.0, 1.0], np.zeros((100, 2)))
    assert adjusted == [1 / 101, 1 / 101]


def test_hansen_spa_is_deterministic() -> None:
    excess = np.column_stack((np.linspace(-0.1, 0.2, 40), np.linspace(0.0, 0.1, 40)))
    first = hansen_spa_p_value(excess, iterations=200)
    second = hansen_spa_p_value(excess, iterations=200)
    assert first == second
    assert 0.0 <= first <= 1.0
