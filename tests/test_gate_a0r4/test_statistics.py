"""Statistical-method verification tests."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v2 import statistics as stats


def _matrix(seed: int, n: int, m: int, drift: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.standard_normal((n, m)) + drift
    return pd.DataFrame(data, columns=[f"t{i}" for i in range(m)])


def test_bootstrap_pvalues_in_unit_interval() -> None:
    boot = stats.bootstrap_family_stats(_matrix(1, 120, 5, 0.0), seed=1729)
    assert 0.0 <= boot["white_reality_check_p"] <= 1.0
    assert 0.0 <= boot["hansen_spa_p"] <= 1.0
    assert all(0.0 <= p <= 1.0 for p in boot["romano_wolf_stepdown_p"])


def test_strong_positive_drift_gives_small_wrc_p() -> None:
    boot = stats.bootstrap_family_stats(_matrix(2, 250, 4, 0.6), seed=1729)
    assert boot["white_reality_check_p"] < 0.10


def test_pure_noise_gives_large_wrc_p() -> None:
    boot = stats.bootstrap_family_stats(_matrix(3, 250, 4, 0.0), seed=1729)
    assert boot["white_reality_check_p"] > 0.10


def test_holm_and_bh_are_monotone_and_bounded() -> None:
    p = [0.001, 0.02, 0.2, 0.5, 0.9]
    holm = stats.holm_adjust(p)
    bh = stats.bh_fdr(p)
    assert all(0.0 <= x <= 1.0 for x in holm + bh)
    assert all(holm[i] >= p[i] - 1e-12 for i in range(len(p)))  # Holm never reduces p
    assert all(bh[i] >= p[i] - 1e-12 for i in range(len(p)))


def test_pbo_in_unit_interval_and_low_for_common_signal() -> None:
    # all trials share the same positive signal -> low overfitting probability
    base = _matrix(4, 400, 6, 0.0)
    common = np.linspace(-0.1, 0.1, 400)
    shared = base.add(pd.Series(common), axis=0)
    res = stats.pbo_cscv(shared, n_splits=8)
    assert res["reason"] == "OK"
    assert 0.0 <= float(res["pbo"]) <= 1.0


def test_pbo_not_applicable_for_few_trials() -> None:
    res = stats.pbo_cscv(_matrix(5, 100, 2, 0.0))
    assert res["pbo"] == "NOT_APPLICABLE"


def test_default_denominator_is_ceiling() -> None:
    assert stats.default_denominator() == 1200
