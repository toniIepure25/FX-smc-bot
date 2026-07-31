from __future__ import annotations

from fx_smc_bot.research import classical_fx_f0rp as f0rp
from fx_smc_bot.research.classical_factor_safe_io import (
    FROZEN_CURRENCIES,
    FROZEN_INSTRUMENTS,
)


def test_route_b_is_an_outcome_blind_strict_subset() -> None:
    assert f0rp.NZD_RATE_REMEDIATION_ROUTE == "OUTCOME_BLIND_NZD_EXCLUSION"
    assert f0rp.AMENDED_INSTRUMENTS < FROZEN_INSTRUMENTS
    assert f0rp.AMENDED_CURRENCIES < FROZEN_CURRENCIES
    assert FROZEN_INSTRUMENTS - f0rp.AMENDED_INSTRUMENTS == {"NZDUSD"}
    assert FROZEN_CURRENCIES - f0rp.AMENDED_CURRENCIES == {"NZD"}


def test_amended_development_market_plan_cannot_request_nzdusd() -> None:
    partitions = f0rp.development_market_partitions()
    assert len(partitions) == f0rp.EXPECTED_DEVELOPMENT_MARKET_PARTITIONS == 1_512
    assert len({partition.partition_id for partition in partitions}) == 1_512
    assert {partition.instrument for partition in partitions} == f0rp.AMENDED_INSTRUMENTS
    assert all(partition.instrument != "NZDUSD" for partition in partitions)


def test_amended_development_rate_plan_cannot_request_nzd() -> None:
    partitions = f0rp.development_rate_partitions()
    assert len(partitions) == f0rp.EXPECTED_DEVELOPMENT_RATE_PARTITIONS == 49
    assert len({partition.partition_id for partition in partitions}) == 49
    assert {partition.currency for partition in partitions} == f0rp.AMENDED_CURRENCIES
    assert all(partition.currency != "NZD" for partition in partitions)


def test_amendment_overlay_changes_only_nzd_inclusion() -> None:
    overlay = f0rp.amendment_overlay()
    assert overlay["amendment_id"] == "F0_RATE_PROVENANCE_AMENDMENT_V1"
    assert overlay["factor_family_changed"] is False
    assert overlay["factor_risk_weights_changed"] is False
    assert overlay["portfolio_rules_changed"] is False
    assert overlay["selection_thresholds_changed"] is False
    assert overlay["temporal_partitions_changed"] is False
    assert len(str(overlay["overlay_sha256"])) == 64
