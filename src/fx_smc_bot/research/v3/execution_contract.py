"""V3 execution + financing/carry contract, keyed by horizon class.

Intraday horizons (H0/H1) inherit V2's realistic intraday execution: side-correct bid/ask
fills, per-fill commission+slippage, one-bar entry latency, adverse-first same-bar
resolution and a mandatory NY flat before rollover, so no overnight financing is ever
incurred. These are FULLY_EXECUTABLE.

Multi-day horizons (H2/H3) necessarily hold across daily rollovers, weekends and possibly
holidays, so they incur financing/carry and gap risk. The capability contract marks
``OVERNIGHT_FINANCING_RATES`` UNSUPPORTED: historically-realistic broker swap with
defensible provenance cannot be reconstructed from Dukascopy price data. Therefore, under
the "do not silently assume zero overnight financing" rule, every H2/H3 strategy is marked
``PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE`` and is barred from becoming a scientific
*executable* survivor. Its price-alpha evidence may still be reported, clearly labelled.

If, and only if, a defensible financing series is later acquired (a separate, firewalled
acquisition), the contract can be upgraded and H2/H3 re-classified -- but never by assuming
zero cost.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import is_supported
from fx_smc_bot.research.v3.horizons import HORIZONS, HorizonClass, requires_financing

FULLY_EXECUTABLE = "FULLY_EXECUTABLE"
PRICE_ALPHA_ONLY = "PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE"

FINANCING_CAPABILITY = "OVERNIGHT_FINANCING_RATES"

INTRADAY_EXECUTION: dict[str, Any] = {
    "entry_price_side": "side_correct_long_ask_short_bid",
    "exit_price_side": "side_correct_long_bid_short_ask",
    "min_entry_latency_bars": 1,
    "same_bar_policy": "adverse_first",
    "spread_cost": "side_correct_bid_ask_in_fills",
    "base_commission_slippage_bps_per_fill": 0.10,
    "mandatory_flat_ny": "16:45",
    "rollover_exclusion_ny": "16:30",
    "new_entry_resume_ny": "17:30",
    "missing_quote_policy": "no_synthetic_fill",
    "overnight_financing": "not_incurred_flat_before_rollover",
}

MULTIDAY_EXECUTION: dict[str, Any] = {
    "entry_price_side": "side_correct_long_ask_short_bid",
    "exit_price_side": "side_correct_long_bid_short_ask",
    "min_entry_latency_bars": 1,
    "same_bar_policy": "adverse_first",
    "spread_cost": "side_correct_bid_ask_in_fills",
    "base_commission_slippage_bps_per_fill": 0.10,
    "daily_rollover": "position_carried_across_ny_1700",
    "triple_roll_convention": "wednesday_triple_swap_when_applicable",
    "weekend_gap": "friday_close_to_sunday_open_gap_modelled",
    "holiday_gap": "exchange_holiday_gaps_modelled",
    "quote_outage_policy": "no_synthetic_fill_hold_last_valid_state",
    "overnight_financing": "REQUIRED_BUT_UNSUPPORTED",
    "missing_quote_policy": "no_synthetic_fill",
}


def executability_class(horizon: HorizonClass) -> str:
    """FULLY_EXECUTABLE only when no unsupported financing dependency exists."""

    if requires_financing(horizon) and not is_supported(FINANCING_CAPABILITY):
        return PRICE_ALPHA_ONLY
    return FULLY_EXECUTABLE


def execution_surface(horizon: HorizonClass) -> dict[str, Any]:
    return dict(MULTIDAY_EXECUTION) if requires_financing(horizon) else dict(INTRADAY_EXECUTION)


def execution_contract_payload() -> dict[str, Any]:
    per_horizon = {
        h.horizon.value: {
            "requires_overnight_financing": h.requires_overnight_financing,
            "executability_class": executability_class(h.horizon),
            "cost_model": h.cost_model,
            "execution_surface": execution_surface(h.horizon),
        }
        for h in HORIZONS
    }
    return {
        "artifact_id": "V3_EXECUTION_CONTRACT_V1",
        "cost_stress_multipliers": [1.5, 2.0],
        "financing_capability_supported": is_supported(FINANCING_CAPABILITY),
        "rule": "multi-day strategies without defensible financing are PRICE_ALPHA_ONLY; "
                "never assume zero overnight financing.",
        "per_horizon": per_horizon,
    }


def financing_contract_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_FINANCING_CONTRACT_V1",
        "financing_capability_supported": is_supported(FINANCING_CAPABILITY),
        "components_required_for_executable_multiday": [
            "daily_rollover_swap_long",
            "daily_rollover_swap_short",
            "triple_roll_weekday_convention",
            "weekend_gap_return",
            "holiday_gap_return",
            "carry_interest_differential",
        ],
        "provenance_requirement": "broker/provider swap series with immutable manifest and "
                                  "checksum; not derivable from price data.",
        "current_status": "UNSUPPORTED -> H2/H3 = PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE",
        "consequence": "H2/H3 cannot become scientific executable survivors under this freeze.",
        "fully_executable_horizons": [
            h.horizon.value for h in HORIZONS
            if executability_class(h.horizon) == FULLY_EXECUTABLE
        ],
        "price_alpha_only_horizons": [
            h.horizon.value for h in HORIZONS
            if executability_class(h.horizon) == PRICE_ALPHA_ONLY
        ],
    }


def execution_contract_hash() -> str:
    return canonical_hash(execution_contract_payload())


def financing_contract_hash() -> str:
    return canonical_hash(financing_contract_payload())
