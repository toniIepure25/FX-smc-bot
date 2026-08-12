"""Compiler terminal-state, capability, search-space and materialization tests."""

from __future__ import annotations

from fx_smc_bot.research.v2.capabilities import check_required, is_supported
from fx_smc_bot.research.v2.compiler import ADMITTED, REJECTED, compile_all, compile_spec
from fx_smc_bot.research.v2.materialize import materialization_digest, materialize
from fx_smc_bot.research.v2.search_space import (
    REJECTED_FAMILIES,
    enumerate_admitted_specs,
    enumerate_reject_probes,
)


def test_tick_and_cross_capabilities_unsupported() -> None:
    assert not is_supported("TICK_QUOTE_ARRIVAL_RATE")
    assert not is_supported("JPY_CROSS_INSTRUMENTS")
    assert not is_supported("TRIANGULAR_CROSS_RATE")
    assert is_supported("M1_BIDASK_OHLC")
    ok, missing = check_required(("M1_SPREAD", "TICK_QUOTE_ARRIVAL_RATE"))
    assert not ok and missing == ["TICK_QUOTE_ARRIVAL_RATE"]


def test_compiler_has_only_two_terminal_states_no_blocked() -> None:
    specs = enumerate_admitted_specs() + enumerate_reject_probes()
    for spec in specs:
        result = compile_spec(spec)
        assert result.terminal_state in (ADMITTED, REJECTED)
        assert result.terminal_state != "BLOCKED"


def test_all_admitted_specs_are_admitted_and_probes_rejected() -> None:
    admitted, _ = compile_all(enumerate_admitted_specs())
    assert all(r.terminal_state == ADMITTED for r in admitted)
    assert len(admitted) == len(enumerate_admitted_specs())
    _, rejected = compile_all(enumerate_reject_probes())
    assert len(rejected) == len(enumerate_reject_probes())
    for r in rejected:
        assert r.terminal_state == REJECTED
        assert any("unsupported" in reason for reason in r.reasons)


def test_admitted_trials_have_zero_unresolved_blockers() -> None:
    admitted, rejected = compile_all(enumerate_admitted_specs() + enumerate_reject_probes())
    # By construction there is no BLOCKED bucket at all.
    assert all(r.admitted for r in admitted)
    assert all(not r.admitted for r in rejected)


def test_denominator_within_ceiling_and_not_padded() -> None:
    admitted, _ = compile_all(enumerate_admitted_specs())
    assert 0 < len(admitted) <= 1200


def test_rejected_families_documented() -> None:
    for family in ("F06_CROSS_PAIR_LEAD_LAG", "F07_CURRENCY_FACTOR_RESIDUALS",
                   "F08_TRIANGULAR_CONSISTENCY_RESIDUALS",
                   "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL"):
        assert family in REJECTED_FAMILIES
        assert REJECTED_FAMILIES[family]["reason"]


def test_enumeration_is_deterministic() -> None:
    first = [s.spec_hash() for s in enumerate_admitted_specs()]
    second = [s.spec_hash() for s in enumerate_admitted_specs()]
    assert first == second


def test_materialization_is_byte_stable_and_ids_unique() -> None:
    admitted, _ = compile_all(enumerate_admitted_specs())
    trials_a = materialize(admitted, git_sha="deadbeef")
    trials_b = materialize(admitted, git_sha="deadbeef")
    assert materialization_digest(trials_a) == materialization_digest(trials_b)
    ids = [t["trial_id"] for t in trials_a]
    assert len(ids) == len(set(ids))
    for t in trials_a:
        for key in ("configuration_hash", "semantic_spec_hash", "data_capability_hash",
                    "execution_contract_hash", "statistical_protocol_hash"):
            assert t[key]
        assert not t["provenance"]["config_path"].startswith(("C:", "D:", "/"))
