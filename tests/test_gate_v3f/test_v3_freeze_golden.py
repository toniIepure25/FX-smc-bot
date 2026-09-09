"""Golden regression lock for the frozen V3 pre-discovery freeze.

Pinning the top-level ``freeze_hash`` locks every component hash (the freeze hash is a pure
function of all of them). Any accidental drift in a contract, registry, protocol, the feature
DAG, the compiler or the denominator changes the freeze hash and fails this test -- which is
exactly what "frozen by hash" means. These values are byte-identical across machines and CPU
architectures because they are hashes of canonical JSON, not of floating-point layout.

Updated at the data-hardening gate: the freeze hash changed as a PRE-OUTCOME integrity
correction (independent program_protocol identity; claim-class universes; portfolio contract;
evidence-derived denominators). No outcome information informed the change.
"""

from __future__ import annotations

from fx_smc_bot.research.v3.budget import global_denominator
from fx_smc_bot.research.v3.freeze import component_hashes, freeze_hash
from fx_smc_bot.research.v3.program_protocol import program_protocol_hash
from fx_smc_bot.research.v3.statistics import statistics_hash
from fx_smc_bot.research.v3.universes import universe_counts

# Updated at the V3.1 data-availability gate: freeze hash changed as a POST-DATA-QUALITY,
# PRE-ALPHA, PERFORMANCE-BLIND protocol amendment that ADDED the
# V3_DATA_AVAILABILITY_AMENDMENT_V1 contract as a new frozen component (26 -> 27). It
# introduces the general UNRESOLVED_DATA_GAP state (all frozen transport/remediation paths
# exhausted, no frozen interpretation resolves, no repair permitted) with explicit
# no-fabrication execution/feature semantics, cross-instrument semantics, a structural
# (threshold-free) dataset admissibility rule and the V3.1 monthly status taxonomy. It
# resolves the single genuine unresolved data gap (USDJPY:2010-01-01) WITHOUT repairing,
# fabricating or silently excluding it. This is a NEW freeze identity: the prior hash
# (10c2f713...) is deliberately NOT preserved. Universes A/B/C are UNCHANGED (992/52/1044).
# No V3 P&L/candidate outcome informed the change.
GOLDEN_FREEZE_HASH = "5587babc9978343fb09469963822003b552b6c44e92dee373599160bdad356fd"
GOLDEN_TOTAL_DENOMINATOR = 1044
GOLDEN_EXECUTABLE_ALPHA = 992
GOLDEN_PRICE_ALPHA_ONLY = 52
GOLDEN_COMPONENT_COUNT = 27


def test_freeze_hash_is_golden() -> None:
    assert freeze_hash() == GOLDEN_FREEZE_HASH


def test_denominators_are_golden() -> None:
    counts = universe_counts()
    assert global_denominator() == GOLDEN_TOTAL_DENOMINATOR
    assert counts["A_executable_alpha"] == GOLDEN_EXECUTABLE_ALPHA
    assert counts["B_price_alpha_only"] == GOLDEN_PRICE_ALPHA_ONLY
    assert counts["C_total_v3_registry"] == GOLDEN_TOTAL_DENOMINATOR


def test_program_and_statistical_protocols_are_distinct() -> None:
    # regression guard for the fixed freeze bug
    assert program_protocol_hash() != statistics_hash()


def test_component_hash_set_is_stable() -> None:
    ch = component_hashes()
    assert len(ch) == GOLDEN_COMPONENT_COUNT
    assert ch["program_protocol"] != ch["statistical_protocol"]
    assert all(len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in ch.values())
