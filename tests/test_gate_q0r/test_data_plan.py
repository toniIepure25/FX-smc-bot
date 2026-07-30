from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from fx_smc_bot.research.quant_polarity_q0r_data import (
    DEVELOPMENT_INSTRUMENTS,
    REPLICATION_INSTRUMENTS,
    _provider_dates,
    _retry_after_seconds,
    _validate_rows,
    planned_partitions,
)
from fx_smc_bot.research.quant_safe_io import MarketPartition


def test_frozen_partition_counts_are_exact() -> None:
    development = planned_partitions(DEVELOPMENT_INSTRUMENTS, 2015, 2019)
    replication = planned_partitions(REPLICATION_INSTRUMENTS, 2020, 2022)
    assert len(development) == 480
    assert len(replication) == 432


def test_provider_month_boundaries_are_explicit_and_exclusive() -> None:
    partition = MarketPartition("AUDUSD", "ask", 2019, 12)
    assert _provider_dates(partition) == ("2019-12-01", "2020-01-01")


def test_retry_after_is_honored_when_exposed() -> None:
    assert _retry_after_seconds("HTTP 429 Retry-After: 7") == 7.0
    assert _retry_after_seconds("timeout") is None


def test_payload_date_containment_and_positive_prices() -> None:
    partition = MarketPartition("AUDUSD", "bid", 2019, 1)
    timestamp = int(datetime(2019, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [{"timestamp": timestamp, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}]
    _validate_rows(partition, rows)
    rows[0]["close"] = 0.0
    with pytest.raises(ValueError, match="non-positive"):
        _validate_rows(partition, rows)


def test_payload_outside_partition_is_rejected() -> None:
    partition = MarketPartition("AUDUSD", "bid", 2019, 1)
    timestamp = int(datetime(2019, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [{"timestamp": timestamp, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}]
    with pytest.raises(ValueError, match="escapes"):
        _validate_rows(partition, rows)


def test_date_type_remains_calendar_based() -> None:
    assert MarketPartition("AUDUSD", "bid", 2019, 2).last_day == date(2019, 2, 28)
