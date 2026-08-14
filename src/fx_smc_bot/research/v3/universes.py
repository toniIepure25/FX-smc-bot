"""Frozen V3 claim-class universes A/B/C/D with exact, compiler-derived counts.

Prior artifacts mixed several distinct notions of "denominator". This module makes them
mathematically and operationally unambiguous by defining four frozen universes whose counts
are *computed from the compiler and composition grammar*, never assumed:

* **A — executable scientific-alpha universe**: every FULLY_EXECUTABLE candidate
  (executable standalone families + executable composition archetypes). This, and only this,
  is the denominator consumed by the executable multiple-testing matrix (WRC/SPA/RW/Holm/
  BH-FDR/PSR/DSR/PBO). A candidate here may become an executable scientific survivor.
* **B — price-alpha-only research universe**: H2/H3 candidates whose executability is
  PRICE_ALPHA_ONLY because defensible financing/carry is unsupported. Analysed separately
  against denominator B; a member of B can NEVER become an executable scientific survivor.
* **C — total V3 hypothesis registry**: A ∪ B. C = A + B exactly (disjoint by construction).
* **D — historical V1/V2/V3 lineage accounting**: cross-version candidate counts, controlled
  by the program-level *sequential* procedure (program_protocol.py), NOT by injecting V1/V2
  candidates as imaginary columns into the V3 matrix.

Invariants guarantee that no runtime failure, zero-trade candidate, or observed outcome can
shrink a frozen universe: every count is a pure function of the frozen registries.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.compiler import ADMITTED_EXECUTABLE, compile_all
from fx_smc_bot.research.v3.composition import ARCHETYPES
from fx_smc_bot.research.v3.execution_contract import FULLY_EXECUTABLE, executability_class

# Immutable, verified historical lineage (V1_FINAL_CLOSURE.md, results/gate_a0r5/*).
V1_EVALUATED = 8
V2_EVALUATED = 336

# Which universe each statistical routine is permitted to consume.
DENOMINATOR_EXPOSURE: dict[str, str] = {
    "white_reality_check": "A",
    "hansen_spa": "A",
    "romano_wolf": "A",
    "holm": "A",
    "bh_fdr": "A",
    "psr": "A",
    "dsr": "A",
    "cscv_pbo": "A",
    "price_alpha_descriptive": "B",
    "program_level_sequential": "D",
}


def _standalone_split() -> tuple[int, int]:
    """(executable_standalone, price_alpha_standalone) candidate counts from the compiler."""

    executable = 0
    price_alpha = 0
    for r in compile_all():
        if r.terminal_state != ADMITTED_EXECUTABLE or r.candidate_count == 0:
            continue
        if r.survivor_eligible:
            executable += r.candidate_count
        else:
            price_alpha += r.candidate_count
    return executable, price_alpha


def _composition_split() -> tuple[int, int]:
    """(executable_composition, price_alpha_composition) budgets, split by horizon."""

    executable = 0
    price_alpha = 0
    for arch in ARCHETYPES:
        if executability_class(arch.horizon) == FULLY_EXECUTABLE:
            executable += arch.candidate_budget
        else:
            price_alpha += arch.candidate_budget
    return executable, price_alpha


def universe_counts() -> dict[str, int]:
    exec_std, pa_std = _standalone_split()
    exec_comp, pa_comp = _composition_split()
    a = exec_std + exec_comp
    b = pa_std + pa_comp
    return {
        "A_executable_alpha": a,
        "B_price_alpha_only": b,
        "C_total_v3_registry": a + b,
        "executable_standalone": exec_std,
        "executable_composition": exec_comp,
        "price_alpha_standalone": pa_std,
        "price_alpha_composition": pa_comp,
    }


def assert_invariants(counts: dict[str, int] | None = None) -> None:
    """Fail loudly if the universes are internally inconsistent or non-positive."""

    c = counts or universe_counts()
    if c["A_executable_alpha"] + c["B_price_alpha_only"] != c["C_total_v3_registry"]:
        raise AssertionError("V3_UNIVERSES: A + B must equal C (disjoint claim classes).")
    if c["A_executable_alpha"] <= 0 or c["C_total_v3_registry"] <= 0:
        raise AssertionError("V3_UNIVERSES: executable/total universes must be positive.")
    if c["B_price_alpha_only"] < 0:
        raise AssertionError("V3_UNIVERSES: price-alpha universe cannot be negative.")


def assert_not_shrunk(universe_key: str, observed_count: int) -> None:
    """A frozen universe can never shrink at runtime (outcome/zero-trade/failure independent).

    ``observed_count`` is whatever a downstream routine believes it is about to evaluate; it
    must equal the frozen count. This forbids a runtime error, a zero-trade candidate, or any
    observed outcome from silently reducing the denominator a routine reports.
    """

    frozen = {
        "A": universe_counts()["A_executable_alpha"],
        "B": universe_counts()["B_price_alpha_only"],
        "C": universe_counts()["C_total_v3_registry"],
    }[universe_key]
    if observed_count != frozen:
        raise AssertionError(
            f"V3_UNIVERSES: universe {universe_key} shrank/grew: observed {observed_count} "
            f"!= frozen {frozen}. A frozen universe is outcome-independent and immutable."
        )


def denominator_for(routine: str) -> int:
    """The exact denominator a named statistical routine is permitted to consume."""

    key = DENOMINATOR_EXPOSURE[routine]
    counts = universe_counts()
    if key == "A":
        return counts["A_executable_alpha"]
    if key == "B":
        return counts["B_price_alpha_only"]
    if key == "D":
        return V1_EVALUATED + V2_EVALUATED + counts["C_total_v3_registry"]
    raise KeyError(f"no denominator for universe {key}")


def lineage_accounting() -> dict[str, Any]:
    counts = universe_counts()
    return {
        "rule": "V1/V2 candidates are NOT columns in the V3 WRC/SPA matrix; cross-version "
                "multiplicity is controlled by the program-level sequential procedure "
                "(alpha_program=0.05 split across V1/V2/V3).",
        "V1_evaluated": V1_EVALUATED,
        "V2_evaluated": V2_EVALUATED,
        "V3_total_registry": counts["C_total_v3_registry"],
        "V3_executable_alpha": counts["A_executable_alpha"],
        "cumulative_program_candidate_equivalent": (
            V1_EVALUATED + V2_EVALUATED + counts["C_total_v3_registry"]
        ),
    }


def universes_payload() -> dict[str, Any]:
    counts = universe_counts()
    assert_invariants(counts)
    return {
        "artifact_id": "V3_CLAIM_CLASS_UNIVERSES_V1",
        "universe_A_executable_alpha": {
            "count": counts["A_executable_alpha"],
            "definition": "FULLY_EXECUTABLE standalone + composition candidates",
            "standalone": counts["executable_standalone"],
            "composition": counts["executable_composition"],
            "eligible_for_executable_survivorship": True,
            "consumed_by": [k for k, v in DENOMINATOR_EXPOSURE.items() if v == "A"],
        },
        "universe_B_price_alpha_only": {
            "count": counts["B_price_alpha_only"],
            "definition": "H2/H3 PRICE_ALPHA_ONLY standalone + composition candidates",
            "standalone": counts["price_alpha_standalone"],
            "composition": counts["price_alpha_composition"],
            "eligible_for_executable_survivorship": False,
            "consumed_by": [k for k, v in DENOMINATOR_EXPOSURE.items() if v == "B"],
        },
        "universe_C_total_v3_registry": {
            "count": counts["C_total_v3_registry"],
            "definition": "A + B (disjoint)",
        },
        "universe_D_lineage_accounting": lineage_accounting(),
        "denominator_exposure": DENOMINATOR_EXPOSURE,
        "shrink_invariant": "no runtime failure / zero-trade / outcome can shrink a frozen "
                            "universe; counts are pure functions of the frozen registries.",
    }


def universes_hash() -> str:
    return canonical_hash(universes_payload())
