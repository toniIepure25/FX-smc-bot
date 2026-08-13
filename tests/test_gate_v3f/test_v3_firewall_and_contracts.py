"""V3 pre-discovery freeze: firewall, contracts, DAG, compiler, budget and freeze tests.

These tests certify the safety-critical and structural guarantees of the V3 freeze without
touching any 2018+ data: the firewall blocks holdout file reads *and* provider requests
before I/O, the feature DAG is causal and acyclic, the compiler rejects unsupported-input
families, the denominator is frozen within the inherited ceiling, and every frozen hash is
deterministic.
"""

from __future__ import annotations

from datetime import date

import pytest

from fx_smc_bot.research.v3 import budget, compiler, exposure, freeze
from fx_smc_bot.research.v3.acquisition import FirewalledDownloader, acquisition_plan_payload
from fx_smc_bot.research.v3.composition import (
    ARCHETYPES,
    total_composition_candidates,
    validate_archetypes,
)
from fx_smc_bot.research.v3.execution_contract import (
    FULLY_EXECUTABLE,
    PRICE_ALPHA_ONLY,
    executability_class,
)
from fx_smc_bot.research.v3.feature_dag import (
    Causality,
    FeatureNode,
    NanPolicy,
    build_canonical_dag,
)
from fx_smc_bot.research.v3.firewall import (
    HoldoutFirewallError,
    NetworkHoldoutFirewallError,
    V3HoldoutFirewall,
    parse_request_years,
)
from fx_smc_bot.research.v3.horizons import HorizonClass, requires_financing
from fx_smc_bot.research.v3.survivor import PREDICATES

# --------------------------------------------------------------------------------------
# Firewall: files + network
# --------------------------------------------------------------------------------------


def test_firewall_blocks_holdout_file_read() -> None:
    fw = V3HoldoutFirewall()
    with pytest.raises(HoldoutFirewallError):
        fw.guard_path("data/EURUSD/price=bid/year=2018/month=01/data.json")
    fw.guard_path("data/EURUSD/price=bid/year=2017/month=12/data.json")  # allowed
    assert fw.opened_2018_plus_count() == 0


@pytest.mark.parametrize("bad_date", ["2018-01-01", "2019-06-30", "2025-12-31"])
def test_firewall_blocks_holdout_dates(bad_date: str) -> None:
    fw = V3HoldoutFirewall()
    with pytest.raises(NetworkHoldoutFirewallError):
        fw.guard_date(bad_date, context="test")


@pytest.mark.parametrize("ok_date", ["2010-01-01", "2017-12-31"])
def test_firewall_allows_pre_holdout_dates(ok_date: str) -> None:
    fw = V3HoldoutFirewall()
    assert fw.guard_date(ok_date) < date(2018, 1, 1)


def test_firewall_blocks_window_touching_holdout() -> None:
    fw = V3HoldoutFirewall()
    with pytest.raises(NetworkHoldoutFirewallError):
        fw.guard_provider_request("EURUSD", "2017-11-01", "2018-02-01")
    fw.guard_provider_request("EURUSD", "2015-01-01", "2017-12-31")  # allowed
    assert fw.network.blocked_2018_plus_count() == 1


def test_firewall_blocks_dukascopy_holdout_url() -> None:
    fw = V3HoldoutFirewall()
    fw.guard_url("https://datafeed.dukascopy.com/datafeed/EURUSD/2016/05/10/00h_ticks.bi5")
    with pytest.raises(NetworkHoldoutFirewallError):
        fw.guard_url("https://datafeed.dukascopy.com/datafeed/EURUSD/2018/00/01/00h_ticks.bi5")


def test_parse_request_years() -> None:
    assert 2016 in parse_request_years("2016-05-10")
    assert parse_request_years("/EURUSD/2019/03/01/x.bi5") == [2019]
    assert parse_request_years("year=2014") == [2014]


def test_firewall_audit_reports_zero_holdout() -> None:
    fw = V3HoldoutFirewall()
    audit = fw.audit_payload()
    assert audit["2018_plus_market_or_outcome_files_opened"] == 0
    assert audit["2018_plus_provider_requests_issued"] == 0
    assert set(audit["covers"]) == {"file_reads", "provider_network_requests"}


# --------------------------------------------------------------------------------------
# Acquisition downloader is firewalled before any transfer
# --------------------------------------------------------------------------------------


def test_downloader_firewalls_before_fetch() -> None:
    calls: list[str] = []

    def fetch_fn(url: str) -> bytes:
        calls.append(url)
        return b"payload"

    fw = V3HoldoutFirewall()
    dl = FirewalledDownloader(fw, fetch_fn)
    # holdout URL must raise before fetch_fn is ever called
    with pytest.raises(NetworkHoldoutFirewallError):
        dl.fetch(
            "https://datafeed.dukascopy.com/datafeed/EURUSD/2018/00/01/00h_ticks.bi5",
            "EURUSD", date(2018, 1, 1),
        )
    assert calls == []  # no bytes transferred
    # pre-2018 works and checksums
    r = dl.fetch(
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2015/00/01/00h_ticks.bi5",
        "EURUSD", date(2015, 1, 1),
    )
    assert r.bytes == len(b"payload") and len(r.sha256) == 64 and not r.resumed
    # resume: same url is skipped, not re-fetched
    r2 = dl.fetch(
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2015/00/01/00h_ticks.bi5",
        "EURUSD", date(2015, 1, 1),
    )
    assert r2.resumed and len(calls) == 1


def test_acquisition_plan_is_pre_2018_only() -> None:
    plan = acquisition_plan_payload()
    assert all(y < 2018 for y in plan["plan_years"])
    assert plan["totals"]["instrument_years"] == 13 * 8
    assert plan["totals"]["canonical_gib_est"] > 0


# --------------------------------------------------------------------------------------
# Feature DAG: causal + acyclic + deterministic
# --------------------------------------------------------------------------------------


def test_feature_dag_validates_and_is_causal() -> None:
    dag = build_canonical_dag()
    dag.validate()  # raises on any violation
    for node in dag.nodes.values():
        assert node.causality is Causality.CAUSAL_ENDPOINT
        assert node.timestamp_availability == "bar_close_t"


def test_feature_dag_topological_order_parents_first() -> None:
    dag = build_canonical_dag()
    order = dag.topological_order()
    pos = {nid: i for i, nid in enumerate(order)}
    for node in dag.nodes.values():
        for parent in node.parents:
            assert pos[parent] < pos[node.node_id]


def test_feature_dag_hash_deterministic() -> None:
    assert build_canonical_dag().dag_hash() == build_canonical_dag().dag_hash()


def test_feature_dag_rejects_centered_node() -> None:
    dag = build_canonical_dag()
    dag.add(
        FeatureNode("leaky", "centered", ("mid_close",), ("self",), "M1", 60, 60,
                    "bar_close_t", "price", NanPolicy.DROP_WARMUP, "none",
                    Causality.FORBIDDEN_CENTERED, ("MID_OHLC",), ("mid_close",))
    )
    with pytest.raises(ValueError):
        dag.validate()


# --------------------------------------------------------------------------------------
# Compiler: rejects unsupported inputs, no blocked limbo
# --------------------------------------------------------------------------------------


def test_compiler_rejects_tick_and_orderbook_families() -> None:
    p = compiler.compiler_payload()
    rejected = {r["family_id"] for r in p["results"]
                if r["terminal_state"] == compiler.REJECTED_PRE_OUTCOME}
    assert "V3_E_TICK_ARRIVAL_INTENSITY" in rejected
    assert "V3_E_ORDER_BOOK_IMBALANCE" in rejected
    assert p["unresolved_blocked_count"] == 0


def test_compiler_admitted_have_valid_executability() -> None:
    p = compiler.compiler_payload()
    for r in p["results"]:
        if r["terminal_state"] == compiler.ADMITTED_EXECUTABLE:
            assert r["executability_class"] in (FULLY_EXECUTABLE, PRICE_ALPHA_ONLY)


def test_multiday_is_price_alpha_only() -> None:
    assert executability_class(HorizonClass.H2_INTRAWEEK) == PRICE_ALPHA_ONLY
    assert executability_class(HorizonClass.H3_INTRAMONTH) == PRICE_ALPHA_ONLY
    assert executability_class(HorizonClass.H0_MICRO_INTRADAY) == FULLY_EXECUTABLE
    assert requires_financing(HorizonClass.H2_INTRAWEEK)
    assert not requires_financing(HorizonClass.H1_SESSION_DAILY)


# --------------------------------------------------------------------------------------
# Budget + lineage
# --------------------------------------------------------------------------------------


def test_denominator_within_inherited_ceiling() -> None:
    b = budget.budget_payload()
    d = b["v3_registered_candidate_equivalent_denominator"]
    assert 0 < d <= budget.INHERITED_CANDIDATE_CEILING_PER_VERSION
    assert b["lineage"]["v3_within_ceiling"] is True


def test_lineage_accounts_v1_v2_v3() -> None:
    lin = budget.lineage_payload()
    programs = {p["program"]: p for p in lin["programs"]}
    assert programs["FX_INTRADAY_ALPHA_DISCOVERY_V1"]["evaluated"] == 8
    assert programs["FX_INTRADAY_ALPHA_DISCOVERY_V2"]["evaluated"] == 336
    assert lin["cumulative_program_candidate_equivalent"] == 8 + 336 + budget.global_denominator()


# --------------------------------------------------------------------------------------
# Exposure registry: holdout sealed
# --------------------------------------------------------------------------------------


def test_exposure_registry_holdout_sealed() -> None:
    p = exposure.exposure_registry_payload()  # calls assert_holdout_unexposed internally
    assert p["2018_plus_market_or_outcome_files_opened"] == 0
    assert p["sealed_cells_all_none"] is True
    assert p["counts_by_exposure_class"]["SEALED_HOLDOUT_DATA"] == 13 * 2


# --------------------------------------------------------------------------------------
# Survivor predicates: per-horizon, executable eligibility
# --------------------------------------------------------------------------------------


def test_survivor_predicates_executable_eligibility() -> None:
    assert PREDICATES[HorizonClass.H0_MICRO_INTRADAY].executable_eligible is True
    assert PREDICATES[HorizonClass.H2_INTRAWEEK].executable_eligible is False
    # trade-count floors scale down with horizon
    assert (PREDICATES[HorizonClass.H0_MICRO_INTRADAY].min_trades
            > PREDICATES[HorizonClass.H3_INTRAMONTH].min_trades)


# --------------------------------------------------------------------------------------
# Composition grammar
# --------------------------------------------------------------------------------------


def test_composition_grammar_valid() -> None:
    validate_archetypes()  # raises on any invalid archetype
    for arch in ARCHETYPES:
        assert sum(1 for c in arch.components if c.role == "SIGNAL") == 1
    assert total_composition_candidates() == sum(a.candidate_budget for a in ARCHETYPES)


# --------------------------------------------------------------------------------------
# Freeze: deterministic hashes + verdict gating
# --------------------------------------------------------------------------------------


def test_component_hashes_deterministic() -> None:
    assert freeze.component_hashes() == freeze.component_hashes()
    assert freeze.freeze_hash() == freeze.freeze_hash()


def test_freeze_not_ready_without_external_evidence() -> None:
    m = freeze.build_freeze()
    assert m["verdict"] == freeze.VERDICT_NOT_READY
    assert m["discovery_run_in_this_session"] is False
    assert m["2018_plus_market_or_outcome_files_opened"] == 0


def test_freeze_ready_with_full_evidence() -> None:
    ev = {k: True for k in (
        "new_mac_env_reproducible", "arm64_native_stack",
        "v2_cross_machine_regression_passes", "old_laptop_not_required",
        "pre_2018_reconstructable", "clean_room_reproduction_passes",
        "dry_run_all_horizons_passes", "adversarial_audit_zero_material",
        "peak_memory_fits_16gb", "relevant_tests_pass", "ruff_passes", "mypy_passes",
        "schema_validation_passes", "git_diff_check_passes",
    )}
    m = freeze.build_freeze(ev)
    assert m["verdict"] == freeze.VERDICT_READY
    assert m["next_gate"] == "V3_ALPHA_DISCOVERY_RUN"
    assert m["criteria_passed"] == m["criteria_total"]
