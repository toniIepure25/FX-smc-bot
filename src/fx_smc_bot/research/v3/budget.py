"""Hierarchical candidate budget, frozen global denominator and V1/V2/V3 lineage registry.

Budgeting is hierarchical: research domain -> family -> parameter neighbourhood -> instrument
scope, plus a closed set of composition archetypes. The *frozen global candidate-equivalent
denominator* is the number of ADMITTED V3 candidates actually registered for evaluation
(standalone families + composition archetypes); rejected-pre-outcome specs never inflate it.

A cumulative lineage registry records that this program has already spent search budget:
V1 evaluated 8 certified executable trials (0 survivors) and V2 evaluated 336 (0 survivors).
The cumulative program denominator (V1 + V2 + V3) is carried so the multiple-testing account
is never silently reset between versions, honouring the inherited candidate-equivalent
ceiling of 1200 per version.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.compiler import ADMITTED_EXECUTABLE, compile_all
from fx_smc_bot.research.v3.composition import ARCHETYPES, total_composition_candidates
from fx_smc_bot.research.v3.families import DOMAIN_NAMES, FAMILY_INDEX

# Immutable, verified lineage (see V1_FINAL_CLOSURE.md and results/gate_a0r5/*).
V1_EVALUATED = 8
V2_EVALUATED = 336
INHERITED_CANDIDATE_CEILING_PER_VERSION = 1200


def _domain_of(family_id: str) -> str:
    return FAMILY_INDEX[family_id].domain


def budget_payload() -> dict[str, Any]:
    results = compile_all()
    admitted = [r for r in results if r.terminal_state == ADMITTED_EXECUTABLE]

    # Hierarchical roll-up: domain -> family -> candidate_count (standalone only here).
    by_domain: dict[str, dict[str, Any]] = {}
    standalone_total = 0
    executable_standalone = 0
    price_alpha_standalone = 0
    for r in admitted:
        dom = _domain_of(r.family_id)
        node = by_domain.setdefault(
            dom, {"domain_name": DOMAIN_NAMES[dom], "families": {}, "candidate_count": 0}
        )
        node["families"][r.family_id] = r.candidate_count
        node["candidate_count"] += r.candidate_count
        standalone_total += r.candidate_count
        if r.survivor_eligible:
            executable_standalone += r.candidate_count
        elif r.candidate_count:  # admitted, non-eligible, and actually standalone
            price_alpha_standalone += r.candidate_count

    composition_total = total_composition_candidates()
    v3_registered = standalone_total + composition_total
    cumulative = V1_EVALUATED + V2_EVALUATED + v3_registered

    return {
        "artifact_id": "V3_CANDIDATE_BUDGET_V1",
        "budget_hierarchy": ["domain", "family", "parameter_neighborhood", "instrument_scope"],
        "outcome_driven_candidate_deletion": "forbidden",
        "per_domain": by_domain,
        "standalone_candidate_total": standalone_total,
        "executable_standalone_candidates": executable_standalone,
        "price_alpha_only_standalone_candidates": price_alpha_standalone,
        "composition_archetype_count": len(ARCHETYPES),
        "composition_candidate_total": composition_total,
        "v3_registered_candidate_equivalent_denominator": v3_registered,
        "lineage": {
            "V1_evaluated": V1_EVALUATED,
            "V2_evaluated": V2_EVALUATED,
            "V3_registered": v3_registered,
            "cumulative_program_candidate_equivalent": cumulative,
            "inherited_candidate_ceiling_per_version": INHERITED_CANDIDATE_CEILING_PER_VERSION,
            "v3_within_ceiling": v3_registered <= INHERITED_CANDIDATE_CEILING_PER_VERSION,
        },
    }


def global_denominator() -> int:
    return int(budget_payload()["v3_registered_candidate_equivalent_denominator"])


def budget_hash() -> str:
    return canonical_hash(budget_payload())


def lineage_payload() -> dict[str, Any]:
    b = budget_payload()
    return {
        "artifact_id": "V3_LINEAGE_REGISTRY_V1",
        "programs": [
            {"program": "FX_INTRADAY_ALPHA_DISCOVERY_V1", "evaluated": V1_EVALUATED,
             "survivors": 0, "terminal": "CLOSED_NO_CERTIFIED_V1_ALPHA"},
            {"program": "FX_INTRADAY_ALPHA_DISCOVERY_V2", "evaluated": V2_EVALUATED,
             "survivors": 0, "terminal": "V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR"},
            {"program": "FX_INTRADAY_ALPHA_DISCOVERY_V3",
             "registered": b["v3_registered_candidate_equivalent_denominator"],
             "survivors": "PENDING_DISCOVERY", "terminal": "V3_ALPHA_DISCOVERY_READY"},
        ],
        "cumulative_program_candidate_equivalent": b["lineage"][
            "cumulative_program_candidate_equivalent"
        ],
    }


def lineage_hash() -> str:
    return canonical_hash(lineage_payload())
