from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from fx_smc_bot.research.quant_polarity_q0r_data import (
    DEVELOPMENT_INSTRUMENTS,
    REPLICATION_INSTRUMENTS,
    _aggregate_m5,
    _combine_bid_ask,
    _frame_semantic_sha256,
    _parse_side_payload,
    _provider_dates,
    _retry_after_seconds,
    _validate_rows,
    acquire_partition,
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


def test_resumed_manifest_is_counted_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {"rows": 123, "status": "COMPLETE_PENDING_CERTIFICATION"}
    monkeypatch.setattr(
        "fx_smc_bot.research.quant_polarity_q0r_data._existing_partition",
        lambda _authorizations, _partition: manifest,
    )
    result = acquire_partition(
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        MarketPartition("AUDUSD", "bid", 2019, 1),
    )
    assert result["status"] == "COMPLETE"
    assert result["rows"] == 123


def test_canonicalization_is_deterministic_and_spread_aware() -> None:
    partition = MarketPartition("AUDUSD", "bid", 2019, 1)
    timestamps = [
        int(datetime(2019, 1, 2, 0, minute, tzinfo=timezone.utc).timestamp() * 1000)
        for minute in range(5)
    ]
    bid_rows = [
        {"timestamp": timestamp, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}
        for timestamp in timestamps
    ]
    ask_rows = [
        {"timestamp": timestamp, "open": 1.01, "high": 1.11, "low": 0.91, "close": 1.01}
        for timestamp in timestamps
    ]
    bid, _ = _parse_side_payload(json.dumps(bid_rows).encode(), partition)
    ask, _ = _parse_side_payload(
        json.dumps(ask_rows).encode(), MarketPartition("AUDUSD", "ask", 2019, 1)
    )
    first = _combine_bid_ask(bid, ask)
    second = _combine_bid_ask(bid, ask)
    assert _frame_semantic_sha256(first) == _frame_semantic_sha256(second)
    assert len(_aggregate_m5(first)) == 1


def test_nonpositive_spread_is_rejected() -> None:
    timestamp = int(datetime(2019, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [{"timestamp": timestamp, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}]
    bid, _ = _parse_side_payload(
        json.dumps(rows).encode(), MarketPartition("AUDUSD", "bid", 2019, 1)
    )
    ask, _ = _parse_side_payload(
        json.dumps(rows).encode(), MarketPartition("AUDUSD", "ask", 2019, 1)
    )
    with pytest.raises(ValueError, match="spread"):
        _combine_bid_ask(bid, ask)
