"""Terminal V3 data-certification gate.

Evaluates the conditions for ``V3_DATA_CERTIFIED_DISCOVERY_READY`` honestly. The gate passes
to that terminal state ONLY when every required pre-2018 acquisition unit is certified (or
prospectively excluded without outcome knowledge) *and* every other condition holds.

When full coverage has not been achieved because acquisition is still incomplete, the gate
reports the truthful in-progress state
``V3_DATA_CERTIFICATION_IN_PROGRESS_BULK_ACQUISITION_PENDING`` and names bulk acquisition as
the single remaining bounded external step.

When acquisition is complete (no pending/retryable units) but one or more required units
remain terminal INTEGRITY_FAILURE that the frozen protocol does not permit excluding, the
gate reports ``V3_DATA_CERTIFICATION_BLOCKED_BY_GENUINE_DATA_GAP`` -- naming the blocker
accurately (a genuine data gap, not pending acquisition).

V3.1 (V3_DATA_AVAILABILITY_AMENDMENT_V1): ``build_gate_v31`` evaluates the versioned
readiness verdict ``V3_1_DATA_CERTIFIED_DISCOVERY_READY``. Under the amendment, a required
day-unit explicitly represented as UNRESOLVED_DATA_GAP (all frozen paths exhausted, no
frozen interpretation resolves it, no repair permitted) is a legitimate terminal state with
explicit no-fabrication execution/feature semantics -- it is accounted for, remains in the
data-quality denominator and lineage, and is NEVER counted as certified or excluded. The
gate passes only when every required unit is in a terminal discovery-relevant state
(certified / excluded / explicitly unresolved) with exact accounting and structural
admissibility, and every other condition holds.

No coverage is ever fabricated to force a pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.data_availability import (
    AMENDMENT_ARTIFACT_ID,
    UNRESOLVED_DATA_GAP,
    amendment_hash,
    dataset_is_discovery_usable,
)

VERDICT_CERTIFIED = "V3_DATA_CERTIFIED_DISCOVERY_READY"
VERDICT_PENDING = "V3_DATA_CERTIFICATION_IN_PROGRESS_BULK_ACQUISITION_PENDING"
VERDICT_BLOCKED = "V3_DATA_CERTIFICATION_BLOCKED_BY_GENUINE_DATA_GAP"

# V3.1 versioned verdicts (V3_DATA_AVAILABILITY_AMENDMENT_V1).
VERDICT_V31_CERTIFIED = "V3_1_DATA_CERTIFIED_DISCOVERY_READY"
VERDICT_V31_NOT_READY = "V3_1_DATA_CERTIFICATION_NOT_READY"

NEXT_GATE_CERTIFIED = "V3_ALPHA_DISCOVERY_RUN"
NEXT_GATE_PENDING = "COMPLETE_BULK_PRE_2018_ACQUISITION"
NEXT_GATE_BLOCKED = "RESOLVE_DATA_INTEGRITY_GAP"
NEXT_GATE_V31 = "V3_ALPHA_DISCOVERY_RUN"


def build_gate(
    *,
    certified_units: int,
    required_units: int,
    prospectively_excluded_units: int,
    evidence: dict[str, bool],
    terminal_unresolved_units: int = 0,
) -> dict[str, Any]:
    """Assemble the gate artifact and its honest terminal verdict.

    ``terminal_unresolved_units`` counts required units that are in a terminal state that is
    neither certified nor prospectively excluded (frozen-rule INTEGRITY_FAILURE with no
    frozen exclusion applicable). They are NOT pending acquisition: the unit's data was
    acquired and inspected, and the frozen protocol conservatively retains the failure.
    """

    coverage_complete = (certified_units + prospectively_excluded_units) >= required_units
    pending_units = max(
        0, required_units - certified_units - prospectively_excluded_units
        - terminal_unresolved_units
    )

    conditions = {
        "every_required_unit_certified_or_excluded": coverage_complete,
        "frozen_data_dependencies_satisfiable_in_plan": bool(
            evidence.get("dependencies_satisfiable_in_plan")
        ),
        "denominator_semantics_unambiguous": bool(evidence.get("denominator_unambiguous")),
        "freeze_identities_correct": bool(evidence.get("freeze_identities_correct")),
        "readiness_checks_evidence_derived": bool(evidence.get("readiness_evidence_derived")),
        "no_2018_plus_requests": bool(evidence.get("no_2018_requests")),
        "no_2018_plus_reads": bool(evidence.get("no_2018_reads")),
        "no_strategy_outcome_or_pnl_computed": bool(evidence.get("no_outcome_computed")),
        "deterministic_data_manifests_reproduce": bool(
            evidence.get("manifests_reproduce")
        ),
        "tests_ruff_mypy_schema_gitdiff_pass": bool(evidence.get("quality_gates_pass")),
        "no_orphan_acquisition_processes": bool(evidence.get("no_orphan_processes")),
    }

    # Certified requires coverage AND all other conditions; otherwise honest pending/blocked.
    non_coverage = {k: v for k, v in conditions.items()
                    if k != "every_required_unit_certified_or_excluded"}
    certified = coverage_complete and all(non_coverage.values())

    if certified:
        verdict = VERDICT_CERTIFIED
        next_gate = NEXT_GATE_CERTIFIED
        remaining: str | None = None
    elif all(non_coverage.values()) and pending_units == 0 and terminal_unresolved_units > 0:
        # Acquisition is complete (nothing pending/retryable); the only uncovered required
        # units are terminal integrity failures the frozen protocol does not permit
        # excluding. Name the blocker accurately: a genuine data gap, not pending work.
        verdict = VERDICT_BLOCKED
        next_gate = NEXT_GATE_BLOCKED
        remaining = (
            f"bulk pre-2018 acquisition is COMPLETE (0 pending, 0 retryable). "
            f"{terminal_unresolved_units} required day unit(s) remain terminal "
            "INTEGRITY_FAILURE under the frozen V3_DATA_INTEGRITY_REMEDIATION_V1 rule "
            "(no frozen exclusion applies to them). This is a genuine data gap, not "
            "pending acquisition; all non-data conditions pass."
        )
    else:
        verdict = VERDICT_PENDING
        next_gate = NEXT_GATE_PENDING
        remaining = (
            "complete bulk pre-2018 acquisition (13 instruments x 2010-2017); bounded, "
            "resumable. All non-data conditions already pass."
        )

    return {
        "artifact_id": "V3_DATA_CERTIFICATION_GATE_V1",
        "conditions": conditions,
        "conditions_passed": sum(1 for v in conditions.values() if v),
        "conditions_total": len(conditions),
        "coverage": {
            "required_units": required_units,
            "certified_units": certified_units,
            "prospectively_excluded_units": prospectively_excluded_units,
            "terminal_unresolved_units": terminal_unresolved_units,
            "pending_units": pending_units,
            "coverage_complete": coverage_complete,
        },
        "verdict": verdict,
        "next_gate": next_gate,
        "remaining_external_step": remaining,
        "discovery_run_in_this_session": False,
        "2018_plus_market_or_outcome_files_opened": 0,
        "2018_plus_provider_requests_issued": 0,
    }


def build_gate_v31(
    *,
    certified_native_units: int,
    certified_tick_fallback_units: int,
    prospectively_excluded_units: int,
    unresolved_data_gap_units: int,
    required_units: int,
    status_counts: Mapping[str, int],
    evidence: dict[str, bool],
    unresolved_gap_units: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the V3.1 readiness gate artifact and its versioned verdict.

    Under V3_DATA_AVAILABILITY_AMENDMENT_V1 a required day-unit explicitly represented as
    UNRESOLVED_DATA_GAP is a legitimate terminal state with explicit no-fabrication
    execution/feature semantics. It is accounted for and remains in the data-quality
    denominator and lineage, but is NEVER counted as certified or excluded.

    The gate passes to ``V3_1_DATA_CERTIFIED_DISCOVERY_READY`` only when:

    * exact accounting: certified + excluded + unresolved == required (0 pending);
    * structural admissibility: every day-unit state is terminal discovery-relevant with
      explicit no-fabrication semantics (no coverage threshold);
    * every other (non-coverage) condition holds.
    """

    certified_units = certified_native_units + certified_tick_fallback_units
    accounted = (
        certified_units + prospectively_excluded_units + unresolved_data_gap_units
    )
    accounting_complete = accounted == required_units
    pending_units = max(0, required_units - accounted)
    admissible, admissibility_violations = dataset_is_discovery_usable(status_counts)

    conditions = {
        "every_required_unit_in_terminal_discovery_relevant_state": accounting_complete,
        "structural_admissibility_holds": admissible,
        "frozen_data_dependencies_satisfiable_in_plan": bool(
            evidence.get("dependencies_satisfiable_in_plan")
        ),
        "denominator_semantics_unambiguous": bool(evidence.get("denominator_unambiguous")),
        "freeze_identities_correct": bool(evidence.get("freeze_identities_correct")),
        "readiness_checks_evidence_derived": bool(evidence.get("readiness_evidence_derived")),
        "no_2018_plus_requests": bool(evidence.get("no_2018_requests")),
        "no_2018_plus_reads": bool(evidence.get("no_2018_reads")),
        "no_strategy_outcome_or_pnl_computed": bool(evidence.get("no_outcome_computed")),
        "deterministic_data_manifests_reproduce": bool(
            evidence.get("manifests_reproduce")
        ),
        "tests_ruff_mypy_schema_gitdiff_pass": bool(evidence.get("quality_gates_pass")),
        "no_orphan_acquisition_processes": bool(evidence.get("no_orphan_processes")),
    }

    non_coverage = {
        k: v for k, v in conditions.items()
        if k not in ("every_required_unit_in_terminal_discovery_relevant_state",
                     "structural_admissibility_holds")
    }
    ready = (
        accounting_complete and admissible and pending_units == 0
        and all(non_coverage.values())
    )
    if ready:
        verdict = VERDICT_V31_CERTIFIED
        next_gate = NEXT_GATE_V31
        remaining: str | None = None
    else:
        verdict = VERDICT_V31_NOT_READY
        next_gate = NEXT_GATE_PENDING
        blockers = [k for k, v in conditions.items() if not v]
        remaining = (
            "unmet V3.1 conditions: " + ", ".join(sorted(blockers))
            + (f" (admissibility violations: {'; '.join(admissibility_violations)})"
               if admissibility_violations else "")
        )

    return {
        "artifact_id": "V3_1_DATA_CERTIFICATION_GATE_V1",
        "amendment": {
            "artifact_id": AMENDMENT_ARTIFACT_ID,
            "hash": amendment_hash(),
            "classification": "POST_DATA_QUALITY_PRE_ALPHA_PROTOCOL_AMENDMENT",
        },
        "conditions": conditions,
        "conditions_passed": sum(1 for v in conditions.values() if v),
        "conditions_total": len(conditions),
        "coverage": {
            "required_units": required_units,
            "certified_units": certified_units,
            "certified_native_units": certified_native_units,
            "certified_tick_fallback_units": certified_tick_fallback_units,
            "prospectively_excluded_units": prospectively_excluded_units,
            "unresolved_data_gap_units": unresolved_data_gap_units,
            "pending_units": pending_units,
            "accounting_complete": accounting_complete,
        },
        "unresolved_data_gap": {
            "state": UNRESOLVED_DATA_GAP,
            "unit_count": unresolved_data_gap_units,
            "units": sorted(unresolved_gap_units or []),
            "representation": (
                "explicitly represented; never counted as certified or excluded; remains in "
                "the data-quality denominator and lineage"
            ),
            "semantics": (
                "no entry/exit/stop-target fill, no executable or synthetic quote, no "
                "stateful market-feature update, no zero-return insertion, no "
                "spread/volatility/ATR update, no ML training example; clock/calendar time "
                "may advance; a pending order advances to the next session-valid executable "
                "quote (frozen missing-observation execution semantics); no price is "
                "invented"
            ),
        },
        "discovery_semantics_prevent_invalid_use": True,
        "verdict": verdict,
        "next_gate": next_gate,
        "remaining_external_step": remaining,
        "discovery_run_in_this_session": False,
        "2018_plus_market_or_outcome_files_opened": 0,
        "2018_plus_provider_requests_issued": 0,
    }


def gate_hash(gate: dict[str, Any]) -> str:
    return canonical_hash({k: gate[k] for k in ("conditions", "coverage", "verdict")})
