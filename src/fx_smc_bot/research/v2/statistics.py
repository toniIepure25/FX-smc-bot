"""V2 statistical kernel.

The multiple-testing and risk-adjusted-significance methods are the ones certified and
unit-tested in the A0R3D gate (stationary block-bootstrap White Reality Check, Hansen
SPA, Romano-Wolf step-down, Holm, BH-FDR, PSR, DSR). V2 canonicalises them here and adds
a Combinatorially-Symmetric Cross-Validation (CSCV) Probability of Backtest Overfitting
(PBO) estimator (Bailey, Borwein, Lopez de Prado, Zhu). Reusing the verified numerics
avoids re-deriving subtle bootstrap code; equivalence is pinned by tests.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import (
    REGISTERED_TRIAL_DENOMINATOR as _A0R3D_DENOM,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    _sample_moments as sample_moments,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    bh_fdr,
    bootstrap_family_stats,
    dsr,
    holm_adjust,
    normal_p_value_from_mean,
    psr,
)

__all__ = [
    "bh_fdr",
    "bootstrap_family_stats",
    "dsr",
    "holm_adjust",
    "normal_p_value_from_mean",
    "pbo_cscv",
    "psr",
    "sample_moments",
]


def pbo_cscv(
    return_matrix: pd.DataFrame,
    *,
    n_splits: int = 8,
    min_trials: int = 4,
) -> dict[str, Any]:
    """Probability of Backtest Overfitting via CSCV.

    ``return_matrix`` is a (time x trial) matrix of per-period returns. The series is cut
    into ``n_splits`` contiguous blocks; for every way of assigning half the blocks to
    in-sample (IS) and the complement to out-of-sample (OOS), the IS-best trial's OOS
    performance rank is measured. PBO is the fraction of splits where the IS-best trial
    lands in the bottom half OOS (logit < 0).
    """

    if return_matrix.empty or return_matrix.shape[1] < min_trials:
        return {
            "pbo": "NOT_APPLICABLE",
            "reason": "fewer_than_min_trials_or_empty",
            "n_trials": int(return_matrix.shape[1]) if not return_matrix.empty else 0,
        }
    values = return_matrix.to_numpy(dtype=float)
    t, n = values.shape
    n_splits = max(2, n_splits - (n_splits % 2))
    if t < n_splits * 2:
        return {"pbo": "NOT_APPLICABLE", "reason": "insufficient_time_blocks", "n_periods": int(t)}
    bounds = np.linspace(0, t, n_splits + 1).astype(int)
    blocks = [np.arange(bounds[i], bounds[i + 1]) for i in range(n_splits)]
    half = n_splits // 2
    logits: list[float] = []
    for is_choice in combinations(range(n_splits), half):
        is_idx = np.concatenate([blocks[b] for b in is_choice])
        oos_idx = np.concatenate([blocks[b] for b in range(n_splits) if b not in is_choice])
        is_perf = values[is_idx].mean(axis=0)
        oos_perf = values[oos_idx].mean(axis=0)
        best = int(np.argmax(is_perf))
        # OOS rank of the IS-best trial (1 = worst .. n = best)
        order = np.argsort(np.argsort(oos_perf))
        rank = int(order[best]) + 1
        omega = rank / (n + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1 - omega)))
    logits_arr = np.array(logits, dtype=float)
    pbo = float(np.mean(logits_arr <= 0.0))
    return {
        "pbo": round(pbo, 6),
        "n_splits": n_splits,
        "n_combinations": len(logits),
        "median_logit": round(float(np.median(logits_arr)), 6),
        "reason": "OK",
    }


def default_denominator() -> int:
    """The inherited registered candidate-equivalent denominator ceiling (1200)."""

    return int(_A0R3D_DENOM)


def neighborhood_stability(
    focal_net_bps: float, neighbor_net_bps: list[float]
) -> dict[str, Any]:
    """Fraction of parameter neighbours that keep the sign of the focal net return."""

    if not neighbor_net_bps:
        return {"neighbors": 0, "same_sign_fraction": "NOT_APPLICABLE"}
    focal_sign = 1.0 if focal_net_bps > 0 else (-1.0 if focal_net_bps < 0 else 0.0)
    same = sum(1 for v in neighbor_net_bps if (v > 0) == (focal_net_bps > 0))
    return {
        "neighbors": len(neighbor_net_bps),
        "focal_sign": focal_sign,
        "same_sign_fraction": round(same / len(neighbor_net_bps), 6),
    }
