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
        "global_level": "White Reality Check + Hansen SPA over the full admitted candidate "
                        "matrix; global FWER bound over the frozen denominator",
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
        "global candidate-equivalent denominator = ADMITTED_EXECUTABLE V3 candidates + "
        "inherited V1/V2 lineage; rejected-pre-outcome specs never inflate it; frozen "
        "before outcome evaluation."
    ),
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
