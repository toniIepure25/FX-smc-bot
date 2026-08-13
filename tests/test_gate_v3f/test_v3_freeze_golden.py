"""Golden regression lock for the frozen V3 pre-discovery freeze.

Pinning the top-level ``freeze_hash`` locks every component hash (the freeze hash is a pure
function of all of them). Any accidental drift in a contract, registry, protocol, the feature
DAG, the compiler or the denominator changes the freeze hash and fails this test -- which is
exactly what "frozen by hash" means. These values are byte-identical across machines and CPU
architectures because they are hashes of canonical JSON, not of floating-point layout.
"""

from __future__ import annotations

from fx_smc_bot.research.v3.budget import global_denominator
from fx_smc_bot.research.v3.freeze import component_hashes, freeze_hash

GOLDEN_FREEZE_HASH = "ea8973315820ce220b603d9edc8f74441a10b212d19f4b52c67a01c01de8ea87"
GOLDEN_DENOMINATOR = 1044
GOLDEN_COMPONENT_COUNT = 20


def test_freeze_hash_is_golden() -> None:
    assert freeze_hash() == GOLDEN_FREEZE_HASH


def test_denominator_is_golden() -> None:
    assert global_denominator() == GOLDEN_DENOMINATOR


def test_component_hash_set_is_stable() -> None:
    ch = component_hashes()
    assert len(ch) == GOLDEN_COMPONENT_COUNT
    # every component hash is a 64-hex-char sha256
    assert all(len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in ch.values())
