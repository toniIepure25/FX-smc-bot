from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from fx_smc_bot.research import rate_alignment as alignment
from fx_smc_bot.research.rate_calendars import (
    BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
    NEW_YORK_FED_BUSINESS_DAY,
)


@dataclass(frozen=True)
class SyntheticVersion:
    currency: str = "USD"
    series_id: str = "SYNTHETIC_OFFICIAL_SERIES"
    observation_date: date = date(2012, 1, 5)
    value: float = 0.001
    publication_timestamp: datetime = datetime(2012, 1, 6, 14, tzinfo=UTC)
    effective_timestamp: datetime = datetime(2012, 1, 5, 5, tzinfo=UTC)
    strategy_availability_timestamp: datetime = datetime(2012, 1, 6, 14, tzinfo=UTC)
    source_snapshot_sha256: str = "a" * 64
    revision_identifier: str = "INITIAL"
    certification_status: str = alignment.CERTIFIED_STATUS
    calendar_id: str = NEW_YORK_FED_BUSINESS_DAY
    version_id: str = "synthetic-version-initial"


def _replace(version: SyntheticVersion, **changes: object) -> SyntheticVersion:
    values = version.__dict__ | changes
    return SyntheticVersion(**values)


def test_execution_timestamp_is_exact_and_dst_aware() -> None:
    winter = alignment.strategy_timestamp(date(2012, 1, 6))
    summer = alignment.strategy_timestamp(date(2012, 7, 6))
    assert (winter.hour, winter.minute, winter.utcoffset().total_seconds()) == (17, 5, -18_000)
    assert (summer.hour, summer.minute, summer.utcoffset().total_seconds()) == (17, 5, -14_400)
    assert winter.astimezone(UTC).hour == 22
    assert summer.astimezone(UTC).hour == 21


def test_alignment_reports_selected_version_and_full_audit_metadata() -> None:
    version = SyntheticVersion()
    row = alignment.align_rate_for_day(
        [version], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    assert row.selected_rate_version == version.version_id
    assert row.observation_date == date(2012, 1, 5)
    assert row.publication_timestamp == version.publication_timestamp
    assert row.effective_timestamp == version.effective_timestamp
    assert row.availability_timestamp == version.strategy_availability_timestamp
    assert row.age_calendar_days == 1
    assert row.carry_forward_reason == "NO_NEW_CERTIFIED_OFFICIAL_RATE_AVAILABLE"
    assert row.missing_reason is None
    assert row.source_snapshot_sha256 == "a" * 64
    assert row.certification_status == alignment.CERTIFIED_STATUS


def test_future_publication_is_missing_and_never_backfilled() -> None:
    future = _replace(
        SyntheticVersion(),
        publication_timestamp=datetime(2012, 1, 6, 23, tzinfo=UTC),
        strategy_availability_timestamp=datetime(2012, 1, 6, 23, tzinfo=UTC),
    )
    before = alignment.align_rate_for_day(
        [future], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    after = alignment.align_rate_for_day(
        [future], "USD", date(2012, 1, 9), "synthetic-freeze"
    )
    assert before.value is None
    assert before.missing_reason == "NO_CERTIFIED_RATE_AVAILABLE_AS_OF_TIMESTAMP"
    assert after.value == future.value


def test_revision_does_not_leak_backward_and_wins_after_availability() -> None:
    initial = SyntheticVersion()
    revision = _replace(
        initial,
        value=0.002,
        publication_timestamp=datetime(2012, 1, 6, 23, tzinfo=UTC),
        strategy_availability_timestamp=datetime(2012, 1, 6, 23, tzinfo=UTC),
        revision_identifier="REVISION_1",
        source_snapshot_sha256="b" * 64,
        version_id="synthetic-version-revision-1",
    )
    before = alignment.align_rate_for_day(
        [revision, initial], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    after = alignment.align_rate_for_day(
        [initial, revision], "USD", date(2012, 1, 9), "synthetic-freeze"
    )
    assert before.selected_rate_version == initial.version_id
    assert before.value == initial.value
    assert after.selected_rate_version == revision.version_id
    assert after.value == revision.value


def test_uncertified_and_wrong_calendar_versions_fail_closed() -> None:
    uncertified = _replace(SyntheticVersion(), certification_status="REJECTED")
    wrong_calendar = _replace(SyntheticVersion(), calendar_id="TARGET2")
    first = alignment.align_rate_for_day(
        [uncertified], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    second = alignment.align_rate_for_day(
        [wrong_calendar], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    assert first.missing_reason == "NO_CERTIFIED_RATE_VERSION_IN_DATASET_FREEZE"
    assert second.missing_reason == "NO_CERTIFIED_RATE_VERSION_IN_DATASET_FREEZE"


def test_store_pass_status_is_recognized_as_certified() -> None:
    passed = _replace(SyntheticVersion(), certification_status="PASS")
    row = alignment.align_rate_for_day(
        [passed], "USD", date(2012, 1, 6), "synthetic-freeze"
    )
    assert row.value == passed.value
    assert row.certification_status == "PASS"


def test_weekend_carry_has_explicit_source_calendar_reason() -> None:
    version = _replace(
        SyntheticVersion(),
        observation_date=date(2012, 1, 6),
        publication_timestamp=datetime(2012, 1, 6, 15, tzinfo=UTC),
        effective_timestamp=datetime(2012, 1, 6, 5, tzinfo=UTC),
        strategy_availability_timestamp=datetime(2012, 1, 6, 15, tzinfo=UTC),
    )
    row = alignment.align_rate_for_day(
        [version], "USD", date(2012, 1, 9), "synthetic-freeze"
    )
    assert row.age_calendar_days == 3
    assert row.carry_forward_reason == "SOURCE_CALENDAR_CLOSED"


def test_event_rate_carries_only_between_explicit_certified_events() -> None:
    event = date(2012, 1, 17)
    next_event = date(2012, 3, 8)
    version = _replace(
        SyntheticVersion(),
        currency="CAD",
        observation_date=event,
        publication_timestamp=datetime(2012, 1, 17, 15, tzinfo=UTC),
        effective_timestamp=datetime(2012, 1, 17, 15, tzinfo=UTC),
        strategy_availability_timestamp=datetime(2012, 1, 17, 15, tzinfo=UTC),
        calendar_id=BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
    )
    between = alignment.align_rate_for_day(
        [version],
        "CAD",
        date(2012, 2, 1),
        "synthetic-freeze",
        certified_event_dates=frozenset({event, next_event}),
    )
    awaiting = alignment.align_rate_for_day(
        [version],
        "CAD",
        next_event,
        "synthetic-freeze",
        certified_event_dates=frozenset({event, next_event}),
    )
    assert between.carry_forward_reason == "BETWEEN_CERTIFIED_POLICY_EVENTS"
    assert awaiting.carry_forward_reason == "AWAITING_CERTIFIED_POLICY_EVENT_VERSION"


def test_panel_is_deterministic_reports_missing_and_uses_no_interpolation() -> None:
    version = SyntheticVersion()
    days = [date(2012, 1, 6), date(2012, 1, 9)]
    first = alignment.align_rate_panel(
        [version], days, "synthetic-freeze", currencies=("USD", "EUR")
    )
    second = alignment.align_rate_panel(
        [version], reversed(days), "synthetic-freeze", currencies=("USD", "EUR")
    )
    assert first.panel_sha256 == second.panel_sha256
    assert first.status == "BLOCKED_BY_RATE_AVAILABILITY_ALIGNMENT"
    assert first.summary()["missing_count"] == 2
    assert first.summary()["interpolation_used"] is False
    assert first.summary()["backfill_used"] is False
    assert all(row.value == version.value for row in first.rows if row.currency == "USD")
    assert all(row.value is None for row in first.rows if row.currency == "EUR")


def test_panel_requires_explicit_freeze_unique_inputs_and_fx_days() -> None:
    with pytest.raises(ValueError, match="dataset_freeze_id"):
        alignment.align_rate_panel([], [date(2012, 1, 6)], "", currencies=("USD",))
    with pytest.raises(ValueError, match="unique"):
        alignment.align_rate_panel(
            [], [date(2012, 1, 6), date(2012, 1, 6)], "freeze", currencies=("USD",)
        )
    with pytest.raises(ValueError, match="not an explicit FX trading day"):
        alignment.align_rate_panel([], [date(2012, 1, 7)], "freeze", currencies=("USD",))
