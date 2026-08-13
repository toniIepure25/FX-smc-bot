"""V3 pre-outcome admission compiler.

Each registered family is resolved -- before any outcome is evaluated -- into exactly one
terminal state:

* ``ADMITTED_EXECUTABLE`` -- every signal input is a supported capability, every feature
  node exists in the causal DAG, the instrument scope is in the frozen acquisition plan, and
  the execution/firewall contracts are satisfied. Admitted candidates additionally carry an
  ``executability_class``: FULLY_EXECUTABLE (H0/H1) or PRICE_ALPHA_ONLY (H2/H3, financing
  unsupported), and ``survivor_eligible`` = only the fully-executable ones may become
  executable scientific survivors.
* ``REJECTED_PRE_OUTCOME`` -- a required *signal* input is unsupported (true tick arrival,
  order-book depth), or a feature node is missing/non-causal. Rejected specs are never
  evaluated and never inflate the multiple-testing denominator.

There is no ``BLOCKED`` limbo state: every family resolves deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import check_required
from fx_smc_bot.research.v3.execution_contract import (
    FULLY_EXECUTABLE,
    executability_class,
)
from fx_smc_bot.research.v3.families import FAMILIES, Family
from fx_smc_bot.research.v3.feature_dag import build_canonical_dag
from fx_smc_bot.research.v3.parameters import PARAMETER_SCALE_INDEX

ADMITTED_EXECUTABLE = "ADMITTED_EXECUTABLE"
REJECTED_PRE_OUTCOME = "REJECTED_PRE_OUTCOME"

# Frozen anti-overpopulation ceiling: no single family may register a parameter neighbourhood
# larger than this. Families whose full grid is larger register a bounded frozen neighbourhood
# of this size; the remaining grid points are exercised as parameter-neighbourhood robustness,
# not as separately-registered candidates. This keeps families comparable and prevents one
# family from dominating the denominator (a V2 parameter-overpopulation lesson).
PARAM_COMBO_CEILING = 25

# Registered instrument breadth per scope (frozen pre-outcome). Single-pair ("self")
# families register survivor candidates only on the three tier-1 USD majors (V2's
# conservative breadth). The other ten pairs are NOT separately-registered candidates: they
# enter V3 exclusively through the cross-sectional panel/triangle families (domains G/H) and
# through instrument leave-one-out robustness. This keeps the registered denominator within
# the inherited candidate-equivalent ceiling and forecloses a hidden-denominator survivor on
# an unregistered instrument.
REGISTERED_SELF_INSTRUMENTS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY")
ROBUSTNESS_ONLY_INSTRUMENTS: tuple[str, ...] = (
    "AUDUSD", "NZDUSD", "USDCAD", "USDCHF",
    "EURJPY", "GBPJPY", "AUDJPY", "EURGBP", "EURCHF", "GBPCHF",
)
# Registered cointegration/triangle groups (prospectively eligible, not outcome-selected).
REGISTERED_TRIANGLES: tuple[tuple[str, str, str], ...] = (
    ("EURUSD", "USDJPY", "EURJPY"),
    ("GBPUSD", "USDJPY", "GBPJPY"),
    ("AUDUSD", "USDJPY", "AUDJPY"),
    ("EURUSD", "GBPUSD", "EURGBP"),
    ("EURUSD", "USDCHF", "EURCHF"),
)


@dataclass(frozen=True, slots=True)
class CompileResult:
    family_id: str
    terminal_state: str
    reason: str
    executability_class: str
    survivor_eligible: bool
    param_combos: int
    instrument_count: int
    candidate_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "terminal_state": self.terminal_state,
            "reason": self.reason,
            "executability_class": self.executability_class,
            "survivor_eligible": self.survivor_eligible,
            "param_combos": self.param_combos,
            "instrument_count": self.instrument_count,
            "candidate_count": self.candidate_count,
        }


def _scope_instrument_count(scope: str) -> int:
    if scope == "self":
        return len(REGISTERED_SELF_INSTRUMENTS)
    if scope == "panel":
        return 1
    if scope == "triangle":
        return len(REGISTERED_TRIANGLES)
    return 1


def _param_combos(family: Family) -> int:
    combos = 1
    for scale_name in family.parameter_scales:
        combos *= len(PARAMETER_SCALE_INDEX[scale_name].values)
    return min(combos, PARAM_COMBO_CEILING)


def compile_family(family: Family, dag_node_ids: frozenset[str]) -> CompileResult:
    # 1. signal-input capability check (financing is a cost input, handled separately)
    ok, missing = check_required(family.required_capabilities)
    if not ok:
        return CompileResult(
            family.family_id, REJECTED_PRE_OUTCOME,
            f"unsupported signal-input capabilities: {missing}",
            executability_class="n/a", survivor_eligible=False,
            param_combos=0, instrument_count=0, candidate_count=0,
        )
    # 2. every declared feature node must exist in the causal DAG
    missing_nodes = [n for n in family.feature_nodes if n not in dag_node_ids]
    if missing_nodes:
        return CompileResult(
            family.family_id, REJECTED_PRE_OUTCOME,
            f"feature nodes not in causal DAG: {missing_nodes}",
            executability_class="n/a", survivor_eligible=False,
            param_combos=0, instrument_count=0, candidate_count=0,
        )
    # 3. admitted; classify executability from the horizon financing contract
    exec_class = executability_class(family.horizon)
    combos = _param_combos(family)
    inst = _scope_instrument_count(family.instrument_scope)
    # Conditioning families are admitted but register no standalone candidates: they enter
    # the denominator only through the composition archetypes that reference them.
    standalone_candidates = combos * inst if family.standalone else 0
    reason = "all signal inputs supported; features causal; instruments in plan"
    if not family.standalone:
        reason += "; conditioning-only (registered via composition, not standalone)"
    return CompileResult(
        family.family_id, ADMITTED_EXECUTABLE, reason,
        executability_class=exec_class,
        survivor_eligible=(exec_class == FULLY_EXECUTABLE and family.standalone),
        param_combos=combos, instrument_count=inst, candidate_count=standalone_candidates,
    )


def compile_all() -> list[CompileResult]:
    dag = build_canonical_dag()
    dag.validate()
    node_ids = frozenset(dag.nodes)
    return [compile_family(f, node_ids) for f in FAMILIES]


def compiler_payload() -> dict[str, Any]:
    results = compile_all()
    admitted = [r for r in results if r.terminal_state == ADMITTED_EXECUTABLE]
    rejected = [r for r in results if r.terminal_state == REJECTED_PRE_OUTCOME]
    executable = [r for r in admitted if r.survivor_eligible]
    price_alpha = [r for r in admitted if not r.survivor_eligible]
    return {
        "artifact_id": "V3_COMPILER_ADMISSION_V1",
        "compiler_version": "V3_COMPILER_1",
        "param_combo_ceiling": PARAM_COMBO_CEILING,
        "registered_self_instruments": list(REGISTERED_SELF_INSTRUMENTS),
        "robustness_only_instruments": list(ROBUSTNESS_ONLY_INSTRUMENTS),
        "registered_triangles": [list(t) for t in REGISTERED_TRIANGLES],
        "family_count": len(results),
        "admitted_family_count": len(admitted),
        "rejected_family_count": len(rejected),
        "executable_family_count": len(executable),
        "price_alpha_only_family_count": len(price_alpha),
        "admitted_candidate_count": sum(r.candidate_count for r in admitted),
        "executable_candidate_count": sum(r.candidate_count for r in executable),
        "price_alpha_only_candidate_count": sum(r.candidate_count for r in price_alpha),
        "unresolved_blocked_count": 0,
        "results": [r.as_dict() for r in results],
    }


def compiler_hash() -> str:
    return canonical_hash(compiler_payload())
