from __future__ import annotations

import pytest

from fx_smc_bot.research.strategy_alpha_data import (
    RecoveryPartition,
    validate_provider_request,
)


def _validate(
    start: str = "2022-12-01",
    end: str = "2022-12-31",
    instrument: str = "EURUSD",
    partition: RecoveryPartition | None = None,
) -> None:
    selected = partition or RecoveryPartition("EURUSD", 2022, 12, "bid")
    validate_provider_request(
        requested_start=start,
        requested_end=end,
        instrument=instrument,
        partition=selected,
        required_instruments={"EURUSD"},
        planned_partition_ids={"EURUSD:2022-12:BID:M1"},
    )


def test_last_permitted_day_is_accepted() -> None:
    _validate()


@pytest.mark.parametrize("date_value", ["2023-01-01", "2024-01-01", "2025-01-01"])
def test_holdout_dates_are_rejected_before_io(date_value: str) -> None:
    with pytest.raises(ValueError, match="sealed holdout"):
        _validate(end=date_value)


def test_unfrozen_instrument_is_rejected() -> None:
    with pytest.raises(ValueError, match="instrument is not"):
        _validate(instrument="GBPUSD")


def test_unplanned_partition_is_rejected() -> None:
    with pytest.raises(ValueError, match="partition is not"):
        _validate(partition=RecoveryPartition("EURUSD", 2022, 11, "bid"))
