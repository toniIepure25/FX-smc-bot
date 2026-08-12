"""Survivor predicate, holdout firewall and frozen protocol tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.research.v2.firewall import (
    HoldoutFirewall,
    HoldoutFirewallError,
    classify_year,
    is_forbidden_market_path,
)
from fx_smc_bot.research.v2.protocol import protocol_hash, statistical_protocol_payload
from fx_smc_bot.research.v2.survivor import (
    is_scientific_survivor,
    predicate_hash,
    survivor_predicate_payload,
)

_GOOD = {
    "net_bps": 5.0, "sharpe": 0.9, "trade_count": 200, "active_days": 120,
    "fold_positive_fraction": 0.75, "instrument_loo_positive": True,
    "neighborhood_same_sign_fraction": 0.7, "survives_1_5x": True, "survives_2_0x": True,
    "romano_wolf_p": 0.01, "pbo": 0.2, "holdout_clean": True, "reproduction_pass": True,
}


def test_full_predicate_passes_for_strong_candidate() -> None:
    ok, failed = is_scientific_survivor(_GOOD)
    assert ok and failed == []


def test_ranking_above_losers_is_not_a_survivor() -> None:
    # negative net but "best of a losing batch": must fail net_profitability and more
    loser = dict(_GOOD, net_bps=-3.0, survives_1_5x=False, survives_2_0x=False, sharpe=-0.2)
    ok, failed = is_scientific_survivor(loser)
    assert not ok
    assert "net_profitability" in failed and "cost_stress" in failed


def test_predicate_requires_cost_stress() -> None:
    weak = dict(_GOOD, survives_2_0x=False)
    ok, failed = is_scientific_survivor(weak)
    assert not ok and "cost_stress" in failed


def test_predicate_and_protocol_hashes_are_stable() -> None:
    assert predicate_hash() == predicate_hash()
    assert protocol_hash() == protocol_hash()
    assert survivor_predicate_payload()["predicate_hash"] == predicate_hash()


def test_temporal_split_is_chronological_and_non_overlapping() -> None:
    prog = statistical_protocol_payload()["temporal_progression"]
    conf = prog["internal_confirmation"]["window"]
    val = prog["external_validation"]["window"]
    rep = prog["independent_replication"]["window"]
    assert conf[1] < val[0]  # confirmation strictly before validation
    assert val[1] < rep[0]   # validation strictly before replication
    assert prog["discovery"]["years"] == [2015, 2016, 2017]


def test_firewall_classifies_and_blocks_2018_plus() -> None:
    path_2018 = "data/raw/dukascopy-node/EURUSD/price=bid/year=2018/month=01/data.json"
    assert classify_year(path_2018) == 2018
    assert is_forbidden_market_path("x/year=2019/data.json")
    assert not is_forbidden_market_path("x/year=2017/data.json")
    fw = HoldoutFirewall()
    with pytest.raises(HoldoutFirewallError):
        fw.guard_path("x/year=2018/month=01/data.json")
    assert fw.opened_2018_plus_count() == 0
    assert len(fw.blocked_attempts) == 1


def test_firewall_reads_permitted_development_file_if_present() -> None:
    repo = Path(__file__).resolve().parents[2]
    permitted = (repo / "data" / "raw" / "dukascopy-node" / "EURUSD" / "price=bid"
                 / "year=2015" / "month=01" / "data.json")
    if not permitted.exists():
        pytest.skip("development data not present in this checkout")
    fw = HoldoutFirewall()
    fw.read_market_json(permitted)
    audit = fw.audit_payload()
    assert audit["opened_file_count"] == 1
    assert audit["2018_plus_market_or_outcome_files_opened"] == 0
