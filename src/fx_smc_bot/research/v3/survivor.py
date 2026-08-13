"""Frozen V3 survivor predicates, defined per horizon class.

V2 used a single predicate set. V3 spans horizons whose natural trade counts differ by an
order of magnitude, so a single trade-count floor would be statistically inappropriate. Each
horizon therefore has its own predicate, but every predicate is: frozen pre-outcome,
economically meaningful, cost-aware, statistically defensible, and comparable *within* its
registered family. No threshold may be changed after outcomes are seen.

A further hard rule follows from the financing contract: multi-day (H2/H3) strategies are
``PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE`` and therefore can never be *executable*
scientific survivors; their predicate is evaluated only for clearly-labelled price-alpha
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.execution_contract import FULLY_EXECUTABLE, executability_class
from fx_smc_bot.research.v3.horizons import HORIZON_INDEX, HORIZONS, HorizonClass


@dataclass(frozen=True, slots=True)
class SurvivorPredicate:
    horizon: HorizonClass
    min_trades: int
    min_net_bps_per_trade: float
    min_annualized_dsr: float
    min_deflated_sharpe: float
    fold_robustness_min_fraction: float
    instrument_robustness_min_fraction: float
    survives_cost_stress_multiplier: float
    requires_multiple_testing_significant: bool
    executable_eligible: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon.value,
            "min_trades": self.min_trades,
            "min_net_bps_per_trade": self.min_net_bps_per_trade,
            "min_annualized_dsr": self.min_annualized_dsr,
            "min_deflated_sharpe": self.min_deflated_sharpe,
            "fold_robustness_min_fraction": self.fold_robustness_min_fraction,
            "instrument_robustness_min_fraction": self.instrument_robustness_min_fraction,
            "survives_cost_stress_multiplier": self.survives_cost_stress_multiplier,
            "requires_multiple_testing_significant": self.requires_multiple_testing_significant,
            "executable_eligible": self.executable_eligible,
        }


def _predicate(horizon: HorizonClass, *, min_net_bps: float, min_dsr: float) -> SurvivorPredicate:
    spec = HORIZON_INDEX[horizon]
    return SurvivorPredicate(
        horizon=horizon,
        min_trades=spec.min_survivor_trades,
        min_net_bps_per_trade=min_net_bps,
        min_annualized_dsr=min_dsr,
        min_deflated_sharpe=0.0,  # DSR > 0 after deflation by the frozen denominator
        fold_robustness_min_fraction=0.60,
        instrument_robustness_min_fraction=0.60,
        survives_cost_stress_multiplier=2.0,
        requires_multiple_testing_significant=True,
        executable_eligible=(executability_class(horizon) == FULLY_EXECUTABLE),
    )


# Per-horizon net-edge floors rise with holding cost/turnover asymmetry: short horizons need
# a smaller per-trade edge but many trades; long horizons need a larger per-trade edge.
PREDICATES: dict[HorizonClass, SurvivorPredicate] = {
    HorizonClass.H0_MICRO_INTRADAY: _predicate(
        HorizonClass.H0_MICRO_INTRADAY, min_net_bps=0.15, min_dsr=0.50),
    HorizonClass.H1_SESSION_DAILY: _predicate(
        HorizonClass.H1_SESSION_DAILY, min_net_bps=0.75, min_dsr=0.50),
    HorizonClass.H2_INTRAWEEK: _predicate(
        HorizonClass.H2_INTRAWEEK, min_net_bps=3.0, min_dsr=0.50),
    HorizonClass.H3_INTRAMONTH: _predicate(
        HorizonClass.H3_INTRAMONTH, min_net_bps=8.0, min_dsr=0.50),
}


def survivor_predicates_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_SURVIVOR_PREDICATES_V1",
        "frozen_pre_outcome": True,
        "no_post_result_threshold_changes": True,
        "predicates_by_horizon": {
            h.horizon.value: PREDICATES[h.horizon].as_dict() for h in HORIZONS
        },
        "executable_horizons": [
            h.horizon.value for h in HORIZONS if PREDICATES[h.horizon].executable_eligible
        ],
        "price_alpha_only_horizons": [
            h.horizon.value for h in HORIZONS if not PREDICATES[h.horizon].executable_eligible
        ],
    }


def survivor_hash() -> str:
    return canonical_hash(survivor_predicates_payload())
