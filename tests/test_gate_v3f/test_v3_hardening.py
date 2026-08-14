"""Tests for the V3 data-hardening gate: claim-class universes, protocol independence,
evidence-derived readiness, portfolio contract and financing bar."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.v3 import evidence, universes
from fx_smc_bot.research.v3.compiler import ADMITTED_EXECUTABLE, compile_all
from fx_smc_bot.research.v3.execution_contract import PRICE_ALPHA_ONLY
from fx_smc_bot.research.v3.families import FAMILY_INDEX
from fx_smc_bot.research.v3.horizons import requires_financing
from fx_smc_bot.research.v3.portfolio import portfolio_hash
from fx_smc_bot.research.v3.program_protocol import program_protocol_hash
from fx_smc_bot.research.v3.statistics import statistics_hash


# --- #2 program protocol independence ---
def test_program_protocol_independent_of_statistics() -> None:
    assert program_protocol_hash() != statistics_hash()
    assert program_protocol_hash() == program_protocol_hash()


# --- #3 claim-class universes ---
def test_universe_split_is_exact_and_disjoint() -> None:
    c = universes.universe_counts()
    universes.assert_invariants(c)
    assert c["A_executable_alpha"] + c["B_price_alpha_only"] == c["C_total_v3_registry"]
    assert c["A_executable_alpha"] == 992
    assert c["B_price_alpha_only"] == 52
    assert c["C_total_v3_registry"] == 1044


def test_denominator_exposure_routes_to_correct_universe() -> None:
    assert universes.denominator_for("white_reality_check") == 992
    assert universes.denominator_for("hansen_spa") == 992
    assert universes.denominator_for("price_alpha_descriptive") == 52
    assert universes.denominator_for("program_level_sequential") == 8 + 336 + 1044


def test_frozen_universe_cannot_shrink() -> None:
    c = universes.universe_counts()
    universes.assert_not_shrunk("A", c["A_executable_alpha"])  # exact -> ok
    with pytest.raises(AssertionError):
        universes.assert_not_shrunk("A", c["A_executable_alpha"] - 1)  # zero-trade/failure
    with pytest.raises(AssertionError):
        universes.assert_not_shrunk("C", 0)


def test_price_alpha_universe_never_executable_eligible() -> None:
    # every admitted family whose horizon needs financing must be PRICE_ALPHA_ONLY, not eligible
    for r in compile_all():
        if r.terminal_state != ADMITTED_EXECUTABLE:
            continue
        fam = FAMILY_INDEX[r.family_id]
        if requires_financing(fam.horizon):
            assert not r.survivor_eligible
            assert r.executability_class == PRICE_ALPHA_ONLY


# --- #4 evidence-derived readiness ---
def test_evidence_functions_pass() -> None:
    assert evidence.feature_dag_deterministic()
    assert evidence.cross_pair_alignment_ok()
    assert evidence.no_future_leakage_ok()
    assert evidence.ml_regime_deterministic_ok()


def test_portfolio_contract_hash_stable() -> None:
    assert portfolio_hash() == portfolio_hash()
    assert len(portfolio_hash()) == 64
