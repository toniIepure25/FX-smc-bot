"""Independent V3 *program* protocol (distinct from the statistical protocol).

The statistical protocol ([`statistics.py`](statistics.py)) governs *how evidence is judged*
(WRC/SPA/Romano-Wolf/Holm/BH-FDR/PSR/DSR/PBO, bootstrap, walk-forward). The *program*
protocol governs *how the research program is run*: its identity, the gate sequence, the
holdout governance, the claim-class universe governance, the program-level (cross-version)
multiplicity procedure, and the freeze/seed governance.

These are genuinely different artifacts and must hash to genuinely different values. A prior
freeze bug aliased ``program_protocol`` to ``statistics_hash()``; this module gives the
program protocol its own content and identity so the freeze manifest carries two distinct,
correctly-scoped hashes.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3 import V3_NEXT_GATE, V3_PROGRAM_ID
from fx_smc_bot.research.v3._hashing import canonical_hash

PROGRAM_PROTOCOL: dict[str, Any] = {
    "artifact_id": "V3_PROGRAM_PROTOCOL_V1",
    "program_id": V3_PROGRAM_ID,
    "frozen_pre_outcome": True,
    "mission": (
        "Prospectively freeze a multi-horizon FX alpha-research factory whose executable "
        "scientific-alpha universe, price-alpha-only research universe, contracts, feature "
        "DAG, statistical protocol and survivor predicates are fixed from methodology alone, "
        "before any V3 outcome is evaluated and without opening any 2018+ byte."
    ),
    "gate_sequence": [
        "V1_CLOSED_NO_CERTIFIED_ALPHA",
        "V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR",
        "V3_ALPHA_DISCOVERY_READY (architecture/protocol freeze)",
        "V3_DATA_CERTIFIED_DISCOVERY_READY (this gate: data certification)",
        V3_NEXT_GATE,
        "V3_HOLDOUT_CONFIRMATION (2018+; strictly later session only)",
    ],
    "holdout_governance": {
        "holdout_year_floor": 2018,
        "rule": "no 2018+ file read and no 2018+ provider request during any readiness stage; "
                "both blocked before I/O by the firewall; counters asserted zero.",
        "confirmation_stage": "deferred to a strictly later session; never in readiness.",
    },
    "claim_class_governance": {
        "universes": {
            "A": "executable scientific-alpha candidate universe (FULLY_EXECUTABLE only)",
            "B": "price-alpha-only research universe (H2/H3 without defensible financing)",
            "C": "total V3 hypothesis registry = A + B",
            "D": "historical V1/V2/V3 lineage accounting",
        },
        "hard_rule": "a candidate in universe B can NEVER become an executable scientific "
                     "survivor; only universe A is eligible for executable survivorship.",
        "authority": "see universes.py; counts derive from the compiler + composition grammar, "
                     "never assumed.",
    },
    "program_level_multiplicity_procedure": {
        "principle": "V1/V2 historical candidates are NOT injected as imaginary columns into "
                     "the V3 WRC/SPA matrix (their aligned return series are not part of the "
                     "V3 evaluation). Cross-version multiplicity is controlled by a separate, "
                     "frozen, prospective *sequential* procedure at the program level.",
        "procedure": "sequential family-wise alpha budget across program versions: a fixed "
                     "program-wide error budget alpha_program = 0.05 is split across versions "
                     "by a frozen Bonferroni-style allocation over the number of versions that "
                     "reach outcome evaluation; V3's executable survivor test consumes its "
                     "allocated slice, evaluated against universe A only.",
        "versions_reaching_outcome": ["V1", "V2", "V3"],
        "alpha_program": 0.05,
        "v3_allocated_alpha": 0.05 / 3,
        "controlled_separately_from_v3_matrix": True,
    },
    "denominator_exposure_rule": (
        "every statistical routine must declare the exact universe/denominator it consumes "
        "(A for executable multiple-testing; B for price-alpha analysis; D for program-level "
        "sequential control); denominators are frozen and cannot be shrunk by a runtime "
        "failure, a zero-trade candidate, or any observed outcome."
    ),
    "freeze_governance": {
        "hashing": "canonical JSON (sorted keys, no insignificant whitespace) -> sha256; "
                   "machine/architecture independent.",
        "seed_policy": "all randomness seeded by frozen per-routine integer seeds; no wall-clock.",
        "immutability": "frozen artifacts are append-only; corrections require a documented "
                        "pre-outcome integrity rationale and a recomputed freeze hash.",
    },
    "discovery_prohibition_in_readiness": {
        "no_v3_pnl": True,
        "no_v3_signal_or_ranking": True,
        "no_small_sample_of_real_v3_pnl": True,
        "acquisition_may": ["download", "parse", "integrity_inspect"],
        "acquisition_must_not": ["compute_v3_signals", "compute_pnl", "rank", "select"],
    },
}


def program_protocol_payload() -> dict[str, Any]:
    payload = dict(PROGRAM_PROTOCOL)
    payload["program_protocol_hash"] = canonical_hash(PROGRAM_PROTOCOL)
    return payload


def program_protocol_hash() -> str:
    return canonical_hash(PROGRAM_PROTOCOL)
