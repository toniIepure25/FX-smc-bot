from pathlib import Path
from types import SimpleNamespace

import pytest

from fx_smc_bot.research.quant_polarity_data import (
    DEVELOPMENT_YEARS,
    development_partitions,
    development_recovery_protocol,
    validate_recovery_protocol,
)


def test_all_development_pairs_are_supported_by_node_provider() -> None:
    from fx_smc_bot.config import TradingPair
    from fx_smc_bot.data.dukascopy_node_provider import PAIR_TO_INSTRUMENT

    assert {PAIR_TO_INSTRUMENT[TradingPair(value)] for value in {
        "AUDUSD",
        "NZDUSD",
        "USDCAD",
        "USDCHF",
    }} == {"audusd", "nzdusd", "usdcad", "usdchf"}


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


def test_protocol_inventory_never_enumerates_replication_or_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Storage capacity is a host property, not a protocol property. Pin it so
    # this test does not flip to BLOCKED on a nearly full temp volume.
    monkeypatch.setattr(
        "fx_smc_bot.research.quant_polarity_data.shutil.disk_usage",
        lambda _path: SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        ),
    )
    protocol = development_recovery_protocol(tmp_path, "a" * 40)
    inventory = protocol["inventory"]
    assert inventory["parent_directories_enumerated"] is False
    assert inventory["replication_paths_constructed_or_tested"] is False
    assert inventory["holdout_paths_constructed_or_tested"] is False
    assert protocol["guards"]["request_end_lte"] == "2019-12-31"
    assert protocol["status"] == "FROZEN_BEFORE_PROVIDER_ACCESS"
    validate_recovery_protocol(protocol)


def test_protocol_blocks_when_storage_budget_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fx_smc_bot.research.quant_polarity_data.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1 * 1024**3, used=1 * 1024**3, free=0),
    )
    protocol = development_recovery_protocol(tmp_path, "a" * 40)
    assert protocol["status"] == "BLOCKED_BY_STORAGE_BUDGET"
    with pytest.raises(ValueError, match="not frozen"):
        validate_recovery_protocol(protocol)


def test_protocol_hash_tampering_is_rejected(tmp_path: Path) -> None:
    protocol = development_recovery_protocol(tmp_path, "a" * 40)
    protocol["end"] = "2020-01-01"
    try:
        validate_recovery_protocol(protocol)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("Tampered protocol was accepted")
