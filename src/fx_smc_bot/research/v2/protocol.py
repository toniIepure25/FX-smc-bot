"""Frozen V2 statistical protocol and prospective temporal split.

Everything in this module is chosen prospectively, from methodology alone, before any
2018+ market data is read. The temporal progression uses the already-inspected
development region for discovery and reserves the never-opened 2018-2019 holdout for a
strictly chronological confirmation -> validation -> replication cascade. The split is
justified by structure (three non-overlapping, strictly later out-of-sample regions),
not by any observed result, and is frozen by hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fx_smc_bot.research.v2.capabilities import DEVELOPMENT_YEARS, SUPPORTED_INSTRUMENTS

STATISTICAL_PROTOCOL: dict[str, Any] = {
    "artifact_id": "A0R4_STATISTICAL_PROTOCOL_V1",
    "frozen_pre_outcome": True,
    "primary_return_unit": "daily_strategy_net_pnl_bps_by_ny_exit_date",
    "temporal_progression": {
        "discovery": {
            "region": "development",
            "instruments": list(SUPPORTED_INSTRUMENTS),
            "years": list(DEVELOPMENT_YEARS),
            "purpose": "search + anti-overfitting; produces exploratory survivor set only",
            "holdout_touched": False,
        },
        "internal_confirmation": {
            "region": "holdout",
            "instruments": list(SUPPORTED_INSTRUMENTS),
            "window": ["2018-01-01", "2018-06-30"],
            "purpose": "first strictly-out-of-sample confirmation of survivor predicate",
        },
        "external_validation": {
            "region": "holdout",
            "instruments": list(SUPPORTED_INSTRUMENTS),
            "window": ["2018-07-01", "2018-12-31"],
            "purpose": "second independent out-of-sample validation window",
        },
        "independent_replication": {
            "region": "holdout",
            "instruments": list(SUPPORTED_INSTRUMENTS),
            "window": ["2019-01-01", "2019-12-31"],
            "purpose": "full independent year for replication",
        },
    },
    "split_justification": (
        "Discovery uses only the already-inspected 2015-2017 development region. The "
        "untouched 2018-2019 holdout is partitioned into three strictly later, "
        "non-overlapping windows (2018-H1, 2018-H2, 2019) giving independent "
        "confirmation, validation and replication. No window boundary is a function of "
        "any observed outcome."
    ),
    "walk_forward": {
        "scheme": "purged_expanding_walk_forward",
        "discovery_train_min_bars": ">= 12 months of M1 within development region",
        "test_stride": "3 months",
        "purge": "label_horizon_bars",
        "embargo": "max_feature_lookback_bars_plus_max_holding_bars",
        "instrument_leave_one_out": True,
        "year_leave_one_out": True,
        "parameter_neighborhood_stability": True,
    },
    "multiple_testing": {
        "registered_candidate_equivalent_denominator_policy": (
            "number of ADMITTED_EXECUTABLE V2 trials actually evaluated on data; "
            "rejected-pre-outcome specs are never evaluated and never inflate the "
            "denominator; capped at the inherited ceiling of 1200"
        ),
        "family_wise_error": ["White Reality Check", "Hansen SPA", "Romano-Wolf step-down"],
        "false_discovery": ["Holm", "BH-FDR"],
        "risk_adjusted": ["PSR", "DSR"],
        "overfitting": ["CSCV PBO"],
        "bootstrap": "stationary_block_bootstrap",
        "bootstrap_iterations": 499,
        "block_length_days": 5,
    },
    "costs": {
        "base_commission_slippage_bps_per_fill": 0.10,
        "spread": "actual side-correct bid/ask captured in fills",
        "cost_stress_multipliers": [1.5, 2.0],
    },
    "seed_policy": "all randomness seeded by a frozen per-model integer seed; no wall-clock",
}


def protocol_hash() -> str:
    encoded = json.dumps(STATISTICAL_PROTOCOL, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def statistical_protocol_payload() -> dict[str, Any]:
    payload = dict(STATISTICAL_PROTOCOL)
    payload["protocol_hash"] = protocol_hash()
    return payload
