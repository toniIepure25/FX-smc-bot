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

# Updated at the observation-provenance gate: freeze hash changed as a PRE-OUTCOME
# data-semantic correction (missing-observation contract + canonical M1 schema v2 + volume
# provenance). Universes A/B/C are UNCHANGED. No V3 P&L/performance informed the change.
GOLDEN_FREEZE_HASH = "5a96fd0e6de8bc74cf98f39f5cf36e018dfb0521fba9f94e5cccd6dae726f6b1"
GOLDEN_TOTAL_DENOMINATOR = 1044
GOLDEN_EXECUTABLE_ALPHA = 992
GOLDEN_PRICE_ALPHA_ONLY = 52
GOLDEN_COMPONENT_COUNT = 24


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
