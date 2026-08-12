"""Frozen V2 scientific survivor predicate.

A REVIEW_RANKING is informational only. A candidate is a *scientific survivor* only if it
meets every prospectively-frozen economic and statistical requirement below. Ranking above
other losing candidates never confers survivorship. The predicate is hashed and frozen
before any outcome is inspected and must never be relaxed to manufacture survivors.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SURVIVOR_PREDICATE: dict[str, Any] = {
    "artifact_id": "A0R4_SURVIVOR_PREDICATE_V1",
    "frozen_pre_outcome": True,
    "informational_only_note": "REVIEW_RANKING != SCIENTIFIC_SURVIVOR",
    "requirements": {
        "net_profitability": "discovery net_bps > 0 after full costs",
        "risk_adjusted": "annualised daily Sharpe >= 0.5 on discovery region",
        "sample_sufficiency": "trade_count >= 100 and active_days >= 60",
        "fold_robustness": "positive net_bps in >= 60% of purged walk-forward test folds",
        "instrument_robustness": "positive net_bps under instrument leave-one-out",
        "neighborhood_stability": "sign-stable in >= 60% of parameter neighbours",
        "cost_stress": "net_bps > 0 at both 1.5x and 2.0x cost stress",
        "multiple_testing": "Romano-Wolf step-down p <= 0.05 against frozen denominator",
        "overfitting": "CSCV PBO <= 0.5 (or NOT_APPLICABLE with < 4 trials)",
        "data_integrity": "no 2018+ pre-discovery reads; deterministic reproduction PASS",
    },
    "confirmation_eligibility": (
        "only survivors of the discovery predicate are eligible for the strictly-later "
        "2018-H1 internal confirmation stage; confirmation is a separate gate"
    ),
}


@dataclass(frozen=True, slots=True)
class SurvivorThresholds:
    min_net_bps: float = 0.0
    min_sharpe: float = 0.5
    min_trades: int = 100
    min_active_days: int = 60
    min_fold_positive_fraction: float = 0.60
    min_neighborhood_same_sign: float = 0.60
    max_romano_wolf_p: float = 0.05
    max_pbo: float = 0.50


DEFAULT_THRESHOLDS = SurvivorThresholds()


def is_scientific_survivor(
    candidate: dict[str, Any],
    thresholds: SurvivorThresholds = DEFAULT_THRESHOLDS,
) -> tuple[bool, list[str]]:
    """Evaluate the frozen predicate. Returns ``(is_survivor, failed_requirements)``.

    ``candidate`` must expose: ``net_bps``, ``sharpe``, ``trade_count``, ``active_days``,
    ``fold_positive_fraction``, ``instrument_loo_positive`` (bool),
    ``neighborhood_same_sign_fraction``, ``survives_1_5x`` (bool), ``survives_2_0x``
    (bool), ``romano_wolf_p``, ``pbo`` (float or ``"NOT_APPLICABLE"``),
    ``holdout_clean`` (bool), ``reproduction_pass`` (bool).
    """

    failed: list[str] = []
    if not float(candidate.get("net_bps", -1.0)) > thresholds.min_net_bps:
        failed.append("net_profitability")
    if not float(candidate.get("sharpe", -1.0)) >= thresholds.min_sharpe:
        failed.append("risk_adjusted")
    if not (
        int(candidate.get("trade_count", 0)) >= thresholds.min_trades
        and int(candidate.get("active_days", 0)) >= thresholds.min_active_days
    ):
        failed.append("sample_sufficiency")
    fold_fraction = float(candidate.get("fold_positive_fraction", 0.0))
    if not fold_fraction >= thresholds.min_fold_positive_fraction:
        failed.append("fold_robustness")
    if not bool(candidate.get("instrument_loo_positive", False)):
        failed.append("instrument_robustness")
    neighborhood = float(candidate.get("neighborhood_same_sign_fraction", 0.0))
    if not neighborhood >= thresholds.min_neighborhood_same_sign:
        failed.append("neighborhood_stability")
    cost_ok = bool(candidate.get("survives_1_5x", False)) and bool(
        candidate.get("survives_2_0x", False)
    )
    if not cost_ok:
        failed.append("cost_stress")
    if not float(candidate.get("romano_wolf_p", 1.0)) <= thresholds.max_romano_wolf_p:
        failed.append("multiple_testing")
    pbo = candidate.get("pbo", 1.0)
    if pbo != "NOT_APPLICABLE" and not float(pbo) <= thresholds.max_pbo:
        failed.append("overfitting")
    integrity_ok = bool(candidate.get("holdout_clean", False)) and bool(
        candidate.get("reproduction_pass", False)
    )
    if not integrity_ok:
        failed.append("data_integrity")
    return (not failed, failed)


def predicate_hash() -> str:
    encoded = json.dumps(SURVIVOR_PREDICATE, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def survivor_predicate_payload() -> dict[str, Any]:
    payload = dict(SURVIVOR_PREDICATE)
    payload["thresholds"] = {
        "min_net_bps": DEFAULT_THRESHOLDS.min_net_bps,
        "min_sharpe": DEFAULT_THRESHOLDS.min_sharpe,
        "min_trades": DEFAULT_THRESHOLDS.min_trades,
        "min_active_days": DEFAULT_THRESHOLDS.min_active_days,
        "min_fold_positive_fraction": DEFAULT_THRESHOLDS.min_fold_positive_fraction,
        "min_neighborhood_same_sign": DEFAULT_THRESHOLDS.min_neighborhood_same_sign,
        "max_romano_wolf_p": DEFAULT_THRESHOLDS.max_romano_wolf_p,
        "max_pbo": DEFAULT_THRESHOLDS.max_pbo,
    }
    payload["predicate_hash"] = predicate_hash()
    return payload
