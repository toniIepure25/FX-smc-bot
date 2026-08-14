"""Frozen V3 hierarchical statistical protocol.

V3 retains the full V2 multiple-testing machinery (White Reality Check, Hansen SPA,
Romano-Wolf step-down, Holm, BH-FDR, PSR, DSR, CSCV PBO) and adds an explicit *hierarchical*
error-control structure matched to the family-of-families search:

    global  ->  domain  ->  family  ->  candidate

The family-wise correction is applied within each family; a family-level gatekeeping test
(Romano-Wolf on the family's candidates) must pass before any candidate in that family is
eligible, and a domain-level and global-level correction bound the cross-family and
program-wide error. This is chosen because a flat correction over a heterogeneous,
hierarchically-budgeted universe is either too weak (ignores structure) or too conservative
(treats independent hypotheses as exchangeable). The structure is frozen here *before* any
V3 outcome is evaluated, and it is emphatically not chosen to maximise survivors.

The global candidate-equivalent denominator counts every ADMITTED_EXECUTABLE V3 candidate
plus the inherited V1/V2 lineage (see :mod:`budget`), so the program-wide error account is
never silently reset between versions.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

STATISTICAL_PROTOCOL: dict[str, Any] = {
    "artifact_id": "V3_STATISTICAL_PROTOCOL_V1",
    "frozen_pre_outcome": True,
    "primary_return_unit": "daily_strategy_net_pnl_bps_by_ny_exit_date",
    "hierarchy": ["global", "domain", "family", "candidate"],
    "hierarchical_error_control": {
        "family_level_gatekeeper": "Romano-Wolf step-down within family; family eligible "
                                   "only if >=1 candidate significant at family FWER",
        "domain_level": "BH-FDR across family-level gatekeeper p-values within a domain",
        "global_level": "White Reality Check + Hansen SPA over the executable candidate "
                        "matrix (claim-class universe A only); global FWER bound over the "
                        "frozen denominator |A|",
        "consistency_rule": "a candidate is significant only if it passes candidate-, "
                            "family-, domain- and global-level control simultaneously",
    },
    "family_wise_error": ["White Reality Check", "Hansen SPA", "Romano-Wolf step-down"],
    "false_discovery": ["Holm", "BH-FDR"],
    "risk_adjusted": ["PSR", "DSR"],
    "overfitting": ["CSCV PBO"],
    "bootstrap": "stationary_block_bootstrap",
    "bootstrap_iterations": 999,
    "block_length_days": 5,
    "seed_policy": "all randomness seeded by a frozen per-test integer seed; no wall-clock",
    "denominator_policy": (
        "the executable multiple-testing matrix consumes claim-class universe A (executable "
        "scientific-alpha candidates) ONLY; price-alpha-only candidates (universe B) are "
        "analysed separately against |B| and can never be executable survivors; V1/V2 "
        "historical candidates are NOT columns in the V3 matrix and are controlled by the "
        "program-level sequential procedure (see program_protocol.py). Rejected-pre-outcome "
        "specs never inflate any universe; all counts are frozen pre-outcome (see universes.py)."
    ),
    "denominator_exposure": {
        "executable_multiple_testing": "universe_A",
        "price_alpha_analysis": "universe_B",
        "cross_version_multiplicity": "program_level_sequential (universe_D lineage)",
        "authority": "universes.py (counts derived from compiler + composition, not assumed)",
    },
    "walk_forward": {
        "scheme": "purged_expanding_walk_forward",
        "purge": "label_horizon_bars",
        "embargo": "max_feature_lookback_bars_plus_max_holding_bars",
        "instrument_leave_one_out": True,
        "year_leave_one_out": True,
        "session_leave_one_out_when_relevant": True,
        "parameter_neighborhood_stability": True,
    },
    "robustness_battery": [
        "instrument_leave_one_out",
        "year_leave_one_out",
        "session_leave_one_out",
        "parameter_neighborhood_stability",
        "cost_stress_1_5x_2_0x",
        "spread_stress",
        "delayed_entry_stress",
        "execution_degradation",
        "regime_robustness",
        "subperiod_stability",
        "overnight_cost_stress_multiday",
        "weekend_gap_stress_multiday",
    ],
    "holdout_confirmation": {
        "status": "DEFERRED_UNTIL_V3_DISCOVERY_RUN",
        "region": "sealed_2018_plus",
        "touched_during_readiness": False,
    },
}


def statistical_protocol_payload() -> dict[str, Any]:
    payload = dict(STATISTICAL_PROTOCOL)
    payload["protocol_hash"] = canonical_hash(STATISTICAL_PROTOCOL)
    return payload


def statistics_hash() -> str:
    return canonical_hash(STATISTICAL_PROTOCOL)
