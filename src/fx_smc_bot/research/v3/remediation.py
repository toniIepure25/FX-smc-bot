"""V3 pre-outcome data-integrity remediation contract (V3_DATA_INTEGRITY_REMEDIATION_V1).

This is a FROZEN, pre-outcome contract that fixes -- BEFORE any tick result is observed -- the
rules for remediating the native-integrity-failure day-units via the existing synchronized
Dukascopy tick fallback. It is a *data-integrity correction only*: it changes no candidate
definition, no statistic, no execution hypothesis, and computes no V3 P&L or candidate outcome.

Eligible native-integrity fallback categories (ONLY these two are remediated):

1. NATIVE_ZERO_MARKET_OBSERVATIONS
   Native M1 source exists, but after applying the frozen observation rule (volume>0 per side)
   there are zero genuine bid/ask market observations for the trading day (empty canonical grid).
   Action: attempt full-session Dukascopy synchronized tick fallback.

2. NATIVE_BID_ASK_ORDERING_FAILURE
   Native M1 has one or more observed rows where ask_close < bid_close.
   Action: attempt full-session Dukascopy synchronized tick fallback.

ALL OTHER integrity failures remain INTEGRITY_FAILURE and are NOT automatically remediated.

The strict integrity audit is NOT relaxed. Tick-derived M1 must still satisfy
bid_ask_ordering_violations == 0, scaling_plausibility_ok == true, zero duplicate timestamps,
and valid frozen canonical observation semantics. The zero-tolerance ask>=bid rule remains: an
ask < bid minute is never turned into an accepted executable quote.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

RECONTRACT_ID = "V3_DATA_INTEGRITY_REMEDIATION_V1"

# The ONLY two native-integrity categories eligible for the tick remediation pass.
CAT_ZERO_OBS = "NATIVE_ZERO_MARKET_OBSERVATIONS"
CAT_BIDASK_ORDER = "NATIVE_BID_ASK_ORDERING_FAILURE"
ELIGIBLE_CATEGORIES = (CAT_ZERO_OBS, CAT_BIDASK_ORDER)

# A remediated unit may only reach these terminal states (per the frozen rules below).
REMEDIAL_OUTCOMES = ("CERTIFIED_TICK_FALLBACK", "TERMINAL_DATA_ABSENT", "INTEGRITY_FAILURE")

# Distinct, auditable provenance strings (never reused for the native path).
FALLBACK_REASON_BIDASK = "native_bid_ask_ordering_failure"
FALLBACK_REASON_ZERO_OBS = "native_zero_market_observations"
ABSENT_REASON_CONFIRMED = "confirmed_no_market_observations_native_and_tick"

# tick_state values produced by the (operations) tick-session acquisition.
TICK_HAS_OBS = "has_observations"
TICK_ZERO_OBS = "zero_observations_confirmed"
TICK_TRANSIENT = "unresolved_transient"


def remediation_contract_payload() -> dict[str, Any]:
    """The machine-readable, hashable pre-outcome remediation contract."""

    return {
        "artifact_id": RECONTRACT_ID,
        "class": "PRE_OUTCOME_DATA_INTEGRITY_CORRECTION",
        "no_v3_pnl_used": True,
        "no_candidate_outcomes_used": True,
        "no_candidate_definition_changes": True,
        "no_statistic_changes": True,
        "no_execution_hypothesis_changes": True,
        "strict_audit_relaxed": False,
        "zero_tolerance_ask_ge_bid_preserved": True,
        "eligible_categories": {
            CAT_ZERO_OBS: {
                "definition": "native M1 source exists; after the frozen observation rule "
                              "(volume>0 per side) there are zero genuine bid/ask market "
                              "observations for the trading day (empty canonical grid).",
                "action": "attempt full-session Dukascopy synchronized tick fallback.",
            },
            CAT_BIDASK_ORDER: {
                "definition": ("native M1 has one or more observed rows where "
                               "ask_close < bid_close."),
                "action": "attempt full-session Dukascopy synchronized tick fallback.",
            },
        },
        "non_eligible_policy": "ALL OTHER integrity failures remain INTEGRITY_FAILURE and are "
                               "NOT automatically remediated.",
        "tick_derived_m1_requirements": {
            "bid_ask_ordering_violations": 0,
            "scaling_plausibility_ok": True,
            "duplicate_timestamps": 0,
            "canonical_observation_semantics": "frozen (tick: minute present => observed)",
        },
        "zero_observation_day_rule": {
            "applies_to_category": CAT_ZERO_OBS,
            "inspect_complete_session_only": True,
            "require_all_hours_legitimate_transport_state": True,
            "any_genuine_tick_observations": "aggregate to M1 + strict tick certification",
            "complete_session_zero_observations": {
                "preconditions": ["no unresolved transient transport errors",
                                  "all required session hours accounted for",
                                  "zero decoded ticks"],
                "classification": "TERMINAL_DATA_ABSENT",
                "reason": ABSENT_REASON_CONFIRMED,
            },
            "no_absence_from_provider_silence": True,
            "no_single_missing_hour_absence": True,
            "no_external_holiday_label": True,
        },
        "bid_ask_failure_rule": {
            "applies_to_category": CAT_BIDASK_ORDER,
            "aggregate_synchronized_tick_bid_ask_to_m1": True,
            "apply_same_strict_audit": True,
            "pass": "CERTIFIED_TICK_FALLBACK with provenance {native_source_checksum, "
                    "native_integrity_failure, tick_source_checksums, tick_canonical_checksum, "
                    "fallback_reason=native_bid_ask_ordering_failure}",
            "still_violating": "INTEGRITY_FAILURE (the rule is NOT tuned)",
        },
        "preserve_native_evidence": True,
        "state_machine": {
            "reentry": "INTEGRITY_FAILURE -> IN_PROGRESS (remediation pass) ONLY for the two "
                       "eligible categories; no generic 'integrity failures are ignorable' path.",
            "remedial_outcomes": list(REMEDIAL_OUTCOMES),
        },
    }


def remediation_contract_hash() -> str:
    """Deterministic hash of the pre-outcome remediation contract (fixed before tick results)."""

    return canonical_hash(remediation_contract_payload())


def is_eligible_category(category: str) -> bool:
    return category in ELIGIBLE_CATEGORIES


def decide_remediation_outcome(*, category: str, tick_state: str,
                               tick_audit: dict[str, Any] | None) -> str:
    """Pure, pre-outcome decision: map (category, tick session state, strict tick audit) to the
    terminal unit status. No I/O, no network, no outcome information beyond the tick integrity
    audit. This is the frozen remediation rule.

    ``tick_audit`` is the strict integrity audit of the tick-derived M1 (required when
    ``tick_state`` is ``has_observations``); it is ignored otherwise.
    """

    if category not in ELIGIBLE_CATEGORIES:
        # Non-eligible integrity failures are never remediated.
        return "INTEGRITY_FAILURE"

    if tick_state == TICK_TRANSIENT:
        # Never infer closure/absence from transient provider silence.
        return "RETRYABLE"

    if tick_state == TICK_ZERO_OBS:
        if category == CAT_ZERO_OBS:
            # Complete session, all hours in a legitimate transport state, zero decoded ticks:
            # a confirmed no-market-observations day on BOTH transports.
            return "TERMINAL_DATA_ABSENT"
        # A bid/ask-ordering day had native observations; zero tick observations means there is
        # no synchronized tick data to certify. It is NOT a confirmed closure for this category,
        # and it cannot be certified -> it remains an integrity failure (conservative).
        return "INTEGRITY_FAILURE"

    # tick_state == TICK_HAS_OBS: apply the SAME strict audit to the tick-derived M1.
    if tick_audit is None:
        raise ValueError("tick_audit is required when the tick session has observations")
    if (tick_audit["bid_ask_ordering_violations"] == 0
            and tick_audit["scaling_plausibility_ok"] is True
            and tick_audit["duplicate_timestamps"] == 0):
        return "CERTIFIED_TICK_FALLBACK"
    return "INTEGRITY_FAILURE"
