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

# Updated at the synchronized-tick quote-validity gate: freeze hash changed as a PRE-OUTCOME
# data-quality correction that ADDED the V3_SYNCHRONIZED_TICK_QUOTE_VALIDITY_V1 contract as a
# new frozen component (25 -> 26). It fixes, before any additional tick outcome, the
# zero-tolerance QUOTE-level rule (a crossed ask<bid tick is an INVALID market quote that never
# contributes to OHLC/observed/executable) and the minute/day aggregation semantics.
# Universes A/B/C are UNCHANGED (992/52/1044). No V3 P&L/candidate outcome informed the change.
GOLDEN_FREEZE_HASH = "10c2f71360008ddcb3dd4c0df0ec3da09305dcdffa44047c6d01e64613b88e6d"
GOLDEN_TOTAL_DENOMINATOR = 1044
GOLDEN_EXECUTABLE_ALPHA = 992
GOLDEN_PRICE_ALPHA_ONLY = 52
GOLDEN_COMPONENT_COUNT = 26


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
