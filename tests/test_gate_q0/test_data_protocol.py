from pathlib import Path

from fx_smc_bot.research.quant_polarity_data import (
    DEVELOPMENT_YEARS,
    development_partitions,
    development_recovery_protocol,
)


def test_development_partition_plan_is_exact() -> None:
    partitions = development_partitions()
    assert len(partitions) == 480
    assert {partition.instrument for partition in partitions} == {
        "AUDUSD",
        "NZDUSD",
        "USDCAD",
        "USDCHF",
    }
    assert set(DEVELOPMENT_YEARS) == {2015, 2016, 2017, 2018, 2019}
    assert {partition.side for partition in partitions} == {"bid", "ask"}


def test_protocol_inventory_never_enumerates_replication_or_holdout(tmp_path: Path) -> None:
    protocol = development_recovery_protocol(tmp_path, "a" * 40)
    inventory = protocol["inventory"]
    assert inventory["parent_directories_enumerated"] is False
    assert inventory["replication_paths_constructed_or_tested"] is False
    assert inventory["holdout_paths_constructed_or_tested"] is False
    assert protocol["guards"]["request_end_lte"] == "2019-12-31"
    assert protocol["status"] == "FROZEN_BEFORE_PROVIDER_ACCESS"
