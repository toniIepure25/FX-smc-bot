from __future__ import annotations

from datetime import date

import pytest

from fx_smc_bot.research.strategy_alpha_data import (
    WARMUP_M5_BARS,
    RecoveryPartition,
    amended_requirement_contract,
    fx_week_boundary_utc,
    session_bounds_utc,
    validate_amended_provider_request,
)


def test_amended_contract_freezes_source_resolutions_and_warmup() -> None:
    contract = amended_requirement_contract()

    assert contract["source_resolution"]["raw_source"] == "DUKASCOPY_TICK_BI5_BID_ASK"
    assert contract["source_resolution"]["canonical_intermediate"] == "UTC_M1_BID_ASK_OHLC"
    assert contract["source_resolution"]["execution_bars"].startswith("DETERMINISTIC_M5")
    assert contract["source_resolution"]["favorable_tick_ordering_used"] is False
    assert WARMUP_M5_BARS == 500
    assert contract["warm_up"]["formula"] == "max(500, 46 + 288)"


def test_amended_guard_rejects_pre_2015_and_usdjpy() -> None:
    partition = RecoveryPartition("EURUSD", 2015, 1, "bid")
    planned = {partition.partition_id}
    with pytest.raises(ValueError, match="precedes the permitted"):
        validate_amended_provider_request(
            requested_start="2014-12-31",
            requested_end="2015-01-01",
            instrument="EURUSD",
            partition=partition,
            planned_partition_ids=planned,
        )
    with pytest.raises(ValueError, match="instrument is not"):
        validate_amended_provider_request(
            requested_start="2015-01-01",
            requested_end="2015-01-31",
            instrument="USDJPY",
            partition=RecoveryPartition("USDJPY", 2015, 1, "bid"),
            planned_partition_ids={"USDJPY:2015-01:BID:M1"},
        )


def test_session_contract_is_local_and_dst_aware() -> None:
    london_winter, london_winter_end = session_bounds_utc(date(2022, 1, 17), "london")
    london_summer, london_summer_end = session_bounds_utc(date(2022, 7, 18), "london")
    ny_winter, ny_winter_end = session_bounds_utc(date(2022, 1, 17), "new_york")
    ny_summer, ny_summer_end = session_bounds_utc(date(2022, 7, 18), "new_york")

    assert (london_winter.hour, london_winter_end.hour) == (8, 11)
    assert (london_summer.hour, london_summer_end.hour) == (7, 10)
    assert (ny_winter.hour, ny_winter_end.hour) == (13, 16)
    assert (ny_summer.hour, ny_summer_end.hour) == (12, 15)


def test_fx_week_and_exit_contract_prohibit_carry() -> None:
    contract = amended_requirement_contract()
    winter_open = fx_week_boundary_utc(date(2022, 1, 16), "open")
    summer_close = fx_week_boundary_utc(date(2022, 7, 15), "close")

    assert winter_open.hour == 22
    assert summer_close.hour == 21
    assert contract["exit_horizon"]["overnight_carry"] is False
    assert contract["exit_horizon"]["rollover_carry"] is False
    assert contract["exit_horizon"]["weekend_carry"] is False
    assert contract["instrument_roles"]["USDJPY"] == "OPTIONAL_DIAGNOSTIC"
