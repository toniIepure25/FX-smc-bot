"""Frozen Gate Q.0 contracts and new-lineage safety guards."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

PROGRAM_ID = "FX_QUANT_POLARITY_META_V1"
LINEAGE_ID = "FX_QUANT_EDGE_DISCOVERY_LINEAGE_V1"
SOURCE_HYPOTHESIS = "FX_SMC_STRATEGY_ALPHA_POSTHOC_QUARANTINE_V1"
RELATIONSHIP = "NEW_INDEPENDENT_LINEAGE"
PREVIOUS_SEAL_ID = "FX_SMC_STRATEGY_ALPHA_LINEAGE_V1"
PREVIOUS_SEAL_HASH = "4879da718c42e030232b9c7cad32e14b97263ead5c6a4e464c53406f2f02303e"
PREVIOUS_SEAL_STATUS = "CLOSED_ALL_CANDIDATES_TIER_C_NO_FORWARD_TEST"

DEVELOPMENT_INSTRUMENTS = ("AUDUSD", "NZDUSD", "USDCAD", "USDCHF")
REPLICATION_INSTRUMENTS = ("EURJPY", "GBPJPY")
ALL_INSTRUMENTS = (*DEVELOPMENT_INSTRUMENTS, *REPLICATION_INSTRUMENTS)
EXCLUDED_OLD_INSTRUMENTS = ("EURUSD", "GBPUSD", "USDJPY")

DEVELOPMENT_START = date(2015, 1, 1)
DEVELOPMENT_END = date(2019, 12, 31)
REPLICATION_START = date(2020, 1, 1)
REPLICATION_END = date(2022, 12, 31)
HOLDOUT_START = date(2023, 1, 1)
HOLDOUT_END = date(2025, 12, 31)

FEATURES = (
    "source_policy_family",
    "source_signal_direction",
    "session",
    "minute_of_session_sine",
    "minute_of_session_cosine",
    "return_12_m5_div_atr",
    "return_48_m5_div_atr",
    "return_288_m5_div_atr",
    "realized_volatility_20",
    "realized_volatility_100",
    "volatility_ratio_20_100",
    "spread_div_trailing_median_spread",
    "atr_14",
    "distance_prior_day_high_div_atr",
    "distance_prior_day_low_div_atr",
    "current_session_range_div_atr",
    "source_policy_event_quality_scalars",
    "missing_indicator_per_optional_event_quality_scalar",
)

PROHIBITED_FEATURES = (
    "instrument_identity",
    "future_returns",
    "future_spread",
    "trade_outcome",
    "year_identifier",
    "target_hit",
    "stop_hit",
    "post_signal_extrema",
    "instrument_specific_fitted_constant",
)

CANDIDATES: tuple[dict[str, str], ...] = (
    {
        "candidate_id": "Q0_INV_SWEEP_V1",
        "source_policy": "SMC_A_SWEEP_REVERSAL_V1",
        "transformation": "REVERSE_TRADE_DIRECTION_ONLY",
    },
    {
        "candidate_id": "Q0_INV_ACCEPTANCE_V1",
        "source_policy": "SMC_B_ACCEPTANCE_CONTINUATION_V1",
        "transformation": "REVERSE_TRADE_DIRECTION_ONLY",
    },
    {
        "candidate_id": "Q0_INV_LONDON_OR_V1",
        "source_policy": "SMC_C_LONDON_OPENING_RANGE_V1",
        "transformation": "REVERSE_TRADE_DIRECTION_ONLY",
    },
    {
        "candidate_id": "Q0_INV_NEWYORK_OR_V1",
        "source_policy": "SMC_C_NEWYORK_OPENING_RANGE_V1",
        "transformation": "REVERSE_TRADE_DIRECTION_ONLY",
    },
    {
        "candidate_id": "Q0_META_POLARITY_ELASTIC_NET_V1",
        "source_policy": "FOUR_FROZEN_SOURCE_POLICIES",
        "transformation": "CHOOSE_ORIGINAL_INVERSE_OR_ABSTAIN",
    },
)

HYPERPARAMETERS = tuple(
    {"inverse_regularization_c": c_value, "l1_ratio": l1_ratio}
    for c_value in (0.01, 0.1, 1.0)
    for l1_ratio in (0.0, 0.5, 1.0)
)

DEVELOPMENT_CRITERIA: dict[str, Any] = {
    "completed_trades_gte": 150,
    "mean_net_r_gt": 0.0,
    "profit_factor_gt": 1.03,
    "stress_1_5x_mean_net_r_gte": 0.0,
    "day_cluster_ci_lower_gte": -0.03,
    "positive_years_gte": 3,
    "development_years": 5,
    "positive_leave_one_year_out_gte": 4,
    "matched_random_alpha_gt": 0.0,
    "pbo_lt": 0.50,
}

TIER_A_CRITERIA: dict[str, Any] = {
    "replication_trades_gte": 150,
    "mean_net_r_gt": 0.0,
    "day_cluster_ci_lower_gt": 0.0,
    "profit_factor_gt": 1.05,
    "stress_1_5x_mean_net_r_gt": 0.0,
    "stress_2_0x_mean_net_r_gte": 0.0,
    "positive_years_required": [2020, 2021, 2022],
    "all_leave_one_year_out_positive": True,
    "matched_random_alpha_gt": 0.0,
    "holm_permutation_p_lt": 0.05,
    "hansen_spa_p_lt": 0.05,
    "factor_hac_alpha_gt": 0.0,
    "factor_hac_p_lt": 0.05,
    "psr_gt": 0.95,
    "dsr_probability_gt": 0.90,
    "pbo_lt": 0.25,
    "maximum_drawdown_lte_r": 20.0,
    "best_five_trade_share_lt": 0.30,
}

TIER_B_CRITERIA: dict[str, Any] = {
    "replication_trades_gte": 150,
    "mean_net_r_gt": 0.0,
    "day_cluster_ci_lower_gte": -0.02,
    "profit_factor_gt": 1.03,
    "stress_1_5x_mean_net_r_gte": 0.0,
    "positive_years_gte": 2,
    "replication_years": 3,
    "matched_random_alpha_gt": 0.0,
    "holm_p_lt": 0.10,
    "hansen_spa_p_lt": 0.10,
    "psr_gt": 0.90,
    "dsr_probability_gt": 0.75,
    "pbo_lt": 0.40,
    "maximum_drawdown_lte_r": 25.0,
}


class BoundaryViolationError(ValueError):
    """Raised before a prohibited data or lineage operation can occur."""


@dataclass(frozen=True)
class OrderIntent:
    instrument: str
    direction: Literal["LONG", "SHORT"]
    signal_time: str
    order_type: str
    entry_price: float
    stop_distance: float
    target_r: float
    expiry_bars: int
    session_cutoff: str


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def authorize_request(
    instrument: str,
    start: date,
    end: date,
    mode: Literal["development", "replication"],
) -> None:
    """Reject an unauthorized provider request before transport or path access."""
    if instrument in EXCLUDED_OLD_INSTRUMENTS:
        raise BoundaryViolationError(f"Old-lineage instrument prohibited: {instrument}")
    if end >= HOLDOUT_START or start >= HOLDOUT_START:
        raise BoundaryViolationError("Dates on or after 2023-01-01 are prohibited in Gate Q.0")
    if end < start:
        raise BoundaryViolationError("Request end precedes start")
    if mode == "development":
        if instrument not in DEVELOPMENT_INSTRUMENTS:
            raise BoundaryViolationError("Development may use only development instruments")
        if start < DEVELOPMENT_START or end > DEVELOPMENT_END:
            raise BoundaryViolationError("Development request outside 2015-2019")
    elif mode == "replication":
        if instrument not in ALL_INSTRUMENTS:
            raise BoundaryViolationError("Replication instrument is outside the frozen universe")
        if start < REPLICATION_START or end > REPLICATION_END:
            raise BoundaryViolationError("Replication request outside 2020-2022")
    else:
        raise BoundaryViolationError(f"Unknown mode: {mode}")


def authorize_explicit_path(path: str, mode: Literal["development", "replication"]) -> None:
    """Reject forbidden paths before any filesystem operation."""
    normalized = path.replace("\\", "/").lower()
    if "_local_ledgers" in normalized or "row_level" in normalized:
        raise BoundaryViolationError("Old or row-level ledger access is prohibited")
    if "holdout" in normalized:
        raise BoundaryViolationError("Holdout storage enumeration is prohibited")
    if any(instrument.lower() in normalized for instrument in EXCLUDED_OLD_INSTRUMENTS):
        raise BoundaryViolationError("Old-lineage instrument path is prohibited")
    years = {int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized)}
    if any(year >= 2023 for year in years):
        raise BoundaryViolationError("Holdout path enumeration is prohibited")
    if mode == "development" and any(year >= 2020 for year in years):
        raise BoundaryViolationError("Replication path cannot be loaded in development mode")


def authorize_training_source(path: str, purpose: str) -> None:
    """Reject prior-lineage artifacts as labels or model-training inputs."""
    normalized = path.replace("\\", "/").lower()
    normalized_purpose = purpose.lower()
    label_or_training_use = "label" in normalized_purpose or "train" in normalized_purpose
    old_result = (
        "results/gate_p" in normalized
        or "strategy_alpha" in normalized
        or "candidate_results" in normalized
        or "row_ledger" in normalized
    )
    if label_or_training_use and old_result:
        raise BoundaryViolationError("Previous-lineage results cannot be training inputs or labels")


def invert_order_intent(intent: OrderIntent) -> OrderIntent:
    """Reverse direction while preserving every other frozen order field."""
    direction: Literal["LONG", "SHORT"] = "SHORT" if intent.direction == "LONG" else "LONG"
    return replace(intent, direction=direction)


def validate_feature_contract(features: tuple[str, ...]) -> dict[str, Any]:
    exact = features == FEATURES
    prohibited = [feature for feature in features if feature in PROHIBITED_FEATURES]
    return {
        "exact_order": exact,
        "prohibited_features": prohibited,
        "status": "PASS" if exact and not prohibited else "FAIL",
    }


def validate_previous_lineage(
    seal: dict[str, Any],
    quarantine: dict[str, Any],
    closure: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "seal_id": seal.get("seal_id") == PREVIOUS_SEAL_ID,
        "seal_hash": seal.get("lineage_seal_hash") == PREVIOUS_SEAL_HASH,
        "seal_status": seal.get("status") == PREVIOUS_SEAL_STATUS,
        "quarantine_id": quarantine.get("quarantine_id") == SOURCE_HYPOTHESIS,
        "old_lineage_closed": str(closure.get("status", "")).startswith("CLOSED_"),
        "relationship_independent": RELATIONSHIP == "NEW_INDEPENDENT_LINEAGE",
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
