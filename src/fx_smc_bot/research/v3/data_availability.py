"""V3.1 pre-alpha data-availability amendment (V3_DATA_AVAILABILITY_AMENDMENT_V1).

Class: POST_DATA_QUALITY_PRE_ALPHA_PROTOCOL_AMENDMENT.

This is a genuine scientific-protocol amendment, made AFTER data quality was
established and BEFORE any alpha outcome, and it is PERFORMANCE-BLIND: no V3
strategy outcome, P&L, ranking, Sharpe or survivor test was available when it was
written. It receives a NEW freeze identity (a new frozen component); it does NOT
pretend the prior freeze is unchanged.

It resolves the single genuine unresolved data gap (USDJPY:2010-01-01) WITHOUT
repairing, fabricating or silently excluding it, by introducing a formal, general
state -- UNRESOLVED_DATA_GAP -- with explicit no-fabrication execution/feature
semantics, cross-instrument semantics, a structural (threshold-free) dataset
admissibility rule, and an explicit monthly status taxonomy.

UNRESOLVED_DATA_GAP remains visibly distinct from CERTIFIED_NATIVE,
CERTIFIED_TICK_FALLBACK, TERMINAL_DATA_ABSENT and PROSPECTIVE_EXCLUSION. It is
never relabelled as excluded, never counted as observed/certified, and stays in the
data-quality denominator and lineage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.exposure import exposure_registry_payload
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall

AMENDMENT_ARTIFACT_ID = "V3_DATA_AVAILABILITY_AMENDMENT_V1"
AMENDMENT_CLASS = "POST_DATA_QUALITY_PRE_ALPHA_PROTOCOL_AMENDMENT"

# The new formal day-unit state.
UNRESOLVED_DATA_GAP = "UNRESOLVED_DATA_GAP"

# Day-unit state classes used by the structural admissibility rule.
OBSERVABLE_STATES: tuple[str, ...] = ("CERTIFIED_NATIVE", "CERTIFIED_TICK_FALLBACK")
EXCLUDED_STATES: tuple[str, ...] = ("TERMINAL_DATA_ABSENT",)
UNRESOLVED_STATES: tuple[str, ...] = (UNRESOLVED_DATA_GAP,)
# A dataset is discovery-usable when every required day-unit is in one of these
# terminal discovery-relevant states (plus the explicit no-fabrication semantics).
DISCOVERY_RELEVANT_STATES: tuple[str, ...] = (
    *OBSERVABLE_STATES, *EXCLUDED_STATES, *UNRESOLVED_STATES
)

# Frozen freeze lineage (original V3 -> integrity corrections -> this amendment).
FREEZE_LINEAGE: tuple[dict[str, str], ...] = (
    {
        "stage": "original_v3_freeze",
        "component_count": "24",
        "freeze_hash": "5a96fd0e6de8bc74cf98f39f5cf36e018dfb0521fba9f94e5cccd6dae726f6b1",
    },
    {
        "stage": "data_integrity_remediation_correction",
        "component_count": "25",
        "freeze_hash": "f0ac824e86d13bf325708edddfc074f44c1abd3a99f16873fa56ddd55bf349e3",
    },
    {
        "stage": "synchronized_tick_quote_validity_correction",
        "component_count": "26",
        "freeze_hash": "10c2f71360008ddcb3dd4c0df0ec3da09305dcdffa44047c6d01e64613b88e6d",
    },
)


def amendment_payload() -> dict[str, Any]:
    """The full, hash-addressed text of the V3.1 data-availability amendment."""

    return {
        "artifact_id": AMENDMENT_ARTIFACT_ID,
        "classification": AMENDMENT_CLASS,
        "frozen_pre_alpha": True,
        "performance_blind": True,
        "no_v3_strategy_outcome_available": True,
        "adds_frozen_component": "data_availability_amendment",
        "triggering_issue": {
            "unit": "USDJPY:2010-01-01",
            "description": (
                "A single genuine unresolved provider data gap discovered before any alpha "
                "outcome: the native per-side candle streams are internally inconsistent "
                "(330/1320 minutes with a crossed ask/bid close on a thin New-Year session), "
                "and the independent synchronized-tick transport has zero observations to "
                "certify against. Forensic verdict "
                "USDJPY_2010_01_01_GENUINE_UNRESOLVED_DATA_GAP."
            ),
            "forensic_verdict": "USDJPY_2010_01_01_GENUINE_UNRESOLVED_DATA_GAP",
            "forensic_artifact": "results/gate_v3f/data_gap_forensic_audit.json",
        },
        "why_no_repair_is_acceptable": [
            "The frozen zero-tolerance integrity rule forbids repairing, interpolating or "
            "swapping a day that fails bid/ask ordering.",
            "There is no independent frozen transport (zero synchronized ticks) to repair "
            "against; any reconstructed quote would be fabricated.",
            "Repair would turn a genuine data gap into a fake market observation, violating "
            "the missing-observation contract (imputed is never a real quote).",
        ],
        "why_one_day_does_not_force_abandonment": [
            "The missing-observation semantics already prohibit fabrication and prohibit "
            "treating an unavailable day as a market observation.",
            "A single corrupted/missing market day contributes no market information; the "
            "amendment makes it explicitly unusable rather than fake, so the rest of the "
            "otherwise-valid multi-year dataset remains scientifically usable.",
            "Admissibility is structural (every day-unit in a terminal discovery-relevant "
            "state with explicit no-fabrication semantics), not an arbitrary coverage "
            "threshold such as 'up to N missing days' or '99.9% coverage'.",
        ],
        "unresolved_data_gap_definition": {
            "state": UNRESOLVED_DATA_GAP,
            "definition": (
                "A required instrument-day for which: (1) all frozen transport/remediation "
                "paths have been exhausted; (2) available native data fail frozen integrity "
                "checks; (3) no independent frozen transport can certify the day; (4) no "
                "frozen deterministic interpretation can resolve it; (5) no "
                "repair/interpolation/swap is permitted."
            ),
            "terminal": True,
            "never_re_enters_acquisition": True,
            "never_counted_as_certified": True,
            "never_counted_as_excluded": True,
            "never_counted_as_observed": True,
            "remains_in_data_quality_denominator_and_lineage": True,
            "distinct_from": [
                "CERTIFIED_NATIVE",
                "CERTIFIED_TICK_FALLBACK",
                "TERMINAL_DATA_ABSENT",
                "PROSPECTIVE_EXCLUSION",
            ],
        },
        "unavailable_day_semantics": {
            "scope": "an instrument on an UNRESOLVED_DATA_GAP day",
            "no_entry": True,
            "no_exit": True,
            "no_stop_or_target_fill": True,
            "no_executable_quote": True,
            "no_synthetic_quote": True,
            "no_stateful_market_feature_update": True,
            "no_zero_return_insertion": True,
            "no_spread_volatility_atr_update": True,
            "no_ml_training_example_from_that_instrument_day": True,
            "clock_calendar_time_may_advance": True,
            "pending_order_semantics": (
                "apply the already-frozen missing-observation execution semantics: advance "
                "to the next session-valid executable quote; time advances but execution "
                "does not; do NOT invent a price."
            ),
        },
        "cross_instrument_semantics": {
            "rule": (
                "a timestamp/day is usable in any cross-pair / triangular / factor / "
                "portfolio feature only when EVERY required leg is valid under the frozen "
                "observation semantics (contemporaneous observation of all legs)."
            ),
            "unavailable_leg": (
                "if USDJPY is unavailable, any construction requiring USDJPY treats that "
                "leg as unavailable for that day."
            ),
            "no_stale_quote_substitution": True,
            "no_global_date_drop_for_unrelated_instruments": (
                "do not drop the date globally for unrelated instruments unless a frozen "
                "dependency requires it."
            ),
        },
        "dataset_admissibility_rule": {
            "structural_not_threshold": True,
            "forbidden_thresholds": [
                "up_to_N_missing_days_per_month",
                "minimum_coverage_fraction_e.g._99.9_percent",
            ],
            "usable_when": (
                "every required day-unit is in one of: CERTIFIED_NATIVE, "
                "CERTIFIED_TICK_FALLBACK, TERMINAL_DATA_ABSENT, UNRESOLVED_DATA_GAP; AND "
                "every non-certified state has explicit execution/feature semantics that "
                "prevent fabrication and prevent it from being treated as a market "
                "observation."
            ),
            "unresolved_gap_stays_in_denominator_and_lineage": True,
            "unresolved_gap_not_observed_or_certified": True,
            "unresolved_gap_not_prospectively_excluded": True,
        },
        "monthly_status_taxonomy": {
            "CERTIFIED_COMPLETE": "every required trading date present as a certified day-unit",
            "CERTIFIED_WITH_PROSPECTIVE_ABSENCE": (
                "every required date certified or prospectively excluded "
                "(TERMINAL_DATA_ABSENT); no unresolved date"
            ),
            "USABLE_WITH_UNRESOLVED_DATA_GAP": (
                "every required date certified, prospectively excluded, or explicitly "
                "represented as UNRESOLVED_DATA_GAP; the unresolved day is annotated and "
                "never hashed as observed"
            ),
            "INCOMPLETE_COVERAGE": (
                "a required date is neither present, excluded nor explicitly unresolved "
                "(unexplained) -- blocks usability"
            ),
            "INTEGRITY_FAILURE": "integrity violation on present rows",
        },
        "digest_day_classes": [
            "certified_day",
            "prospectively_excluded_terminal_absence_day",
            "unresolved_data_gap_day",
            "missing_unexplained_day",
        ],
        "never_hash_unresolved_day_as_observed": True,
        "performance_blindness": {
            "2018_plus_provider_requests_issued": 0,
            "2018_plus_market_or_outcome_files_opened": 0,
            "V3_PnL_computations": 0,
            "candidate_outcomes_computed": 0,
            "Sharpe_computed": 0,
            "rankings_computed": 0,
            "survivor_tests_computed": 0,
            "no_candidate_specific_information_influenced_this_amendment": True,
        },
        "freeze_lineage": list(FREEZE_LINEAGE),
        "new_freeze_identity": (
            "recomputed at freeze time (27 components); prior hash NOT preserved"
        ),
    }


def amendment_hash() -> str:
    return canonical_hash(amendment_payload())


def dataset_is_discovery_usable(status_counts: Mapping[str, int]) -> tuple[bool, list[str]]:
    """Structural (threshold-free) V3.1 dataset admissibility.

    A dataset is discovery-usable iff EVERY required day-unit is in a terminal
    discovery-relevant state (certified native, certified tick fallback, prospectively
    excluded terminal absence, or explicitly represented UNRESOLVED_DATA_GAP). Any pending
    state (PLANNED / IN_PROGRESS / RETRYABLE) or an unclassified INTEGRITY_FAILURE violates
    admissibility. No coverage fraction or missing-day count is used.
    """

    violations = [
        f"{state}: {count} unit(s) not in a terminal discovery-relevant state"
        for state, count in sorted(status_counts.items())
        if count > 0 and state not in DISCOVERY_RELEVANT_STATES
    ]
    return (not violations, violations)


def day_execution_semantics(unit_status: str) -> dict[str, Any]:
    """Frozen execution/feature semantics for one day-unit state (V3.1).

    Certified states are the only ones that may execute, update stateful market features,
    or contribute ML training examples. Excluded (TERMINAL_DATA_ABSENT) and
    UNRESOLVED_DATA_GAP days are unavailable: no fill, no synthetic quote, no stateful
    feature update, no zero-return insertion, no ML example; the clock may advance and a
    pending order advances to the next session-valid executable quote (the already-frozen
    missing-observation execution semantics).
    """

    if unit_status in OBSERVABLE_STATES:
        return {
            "entry": True,
            "exit": True,
            "stop_or_target_fill": True,
            "executable_quote": True,
            "synthetic_quote": False,
            "stateful_market_feature_update": True,
            "zero_return_insertion": False,
            "spread_volatility_atr_update": True,
            "ml_training_example": True,
            "clock_may_advance": True,
            "on_pending_order": "execute_on_session_valid_executable_quote",
        }
    if unit_status in EXCLUDED_STATES or unit_status in UNRESOLVED_STATES:
        return {
            "entry": False,
            "exit": False,
            "stop_or_target_fill": False,
            "executable_quote": False,
            "synthetic_quote": False,
            "stateful_market_feature_update": False,
            "zero_return_insertion": False,
            "spread_volatility_atr_update": False,
            "ml_training_example": False,
            "clock_may_advance": True,
            "on_pending_order": "advance_clock_to_next_session_valid_executable_quote",
        }
    raise ValueError(f"no frozen V3.1 day semantics for state {unit_status!r}")


def cross_construction_available(leg_statuses: Mapping[str, str]) -> bool:
    """A cross-pair / triangular / factor / portfolio construction is usable at a
    timestamp/day only when EVERY required leg is observable (certified) at that
    timestamp/day.

    A leg in TERMINAL_DATA_ABSENT or UNRESOLVED_DATA_GAP is unavailable (no
    contemporaneous observation); a stale quote is never substituted. An empty leg set is
    not a construction and is unavailable.
    """

    if not leg_statuses:
        return False
    return all(s in OBSERVABLE_STATES for s in leg_statuses.values())


def performance_blindness_evidence() -> dict[str, Any]:
    """COMPUTED evidence that this amendment is performance-blind.

    The 2018+ file-open count is read from the frozen exposure registry (sealed cells all
    NONE). The firewall is probed live to show a 2018+ request is structurally blocked
    before I/O. The V3 outcome counters are session facts: no discovery has ever run, so
    no P&L / candidate outcome / Sharpe / ranking / survivor test exists.
    """

    exposure = exposure_registry_payload()
    fw = V3HoldoutFirewall()
    net_blocked = False
    try:
        fw.guard_date("2018-01-01", context="v3_1_amendment_blindness_probe")
    except Exception:
        net_blocked = True
    return {
        "2018_plus_provider_requests_issued": 0,
        "2018_plus_market_or_outcome_files_opened":
            exposure["2018_plus_market_or_outcome_files_opened"],
        "sealed_holdout_cells_all_none": exposure["sealed_cells_all_none"],
        "2018_plus_request_blocked_by_firewall": net_blocked,
        "V3_PnL_computations": 0,
        "candidate_outcomes_computed": 0,
        "Sharpe_computed": 0,
        "rankings_computed": 0,
        "survivor_tests_computed": 0,
        "discovery_run_in_this_session": False,
        "note": (
            "No V3 strategy outcome/P&L/ranking was available; no candidate-specific "
            "information influenced this amendment."
        ),
    }
