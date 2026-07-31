"""Point-in-time daily rate alignment for Gate F0-RP-E2E.

The module consumes already parsed versions and performs no I/O.  Selection is
strictly as-of 17:05 America/New_York and never uses retrieval time, future
publication, interpolation, or backward filling.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from fx_smc_bot.research.classical_fx_f0rp import AMENDED_CURRENCY_ORDER
from fx_smc_bot.research.rate_calendars import (
    BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
    CALENDAR_VERSION,
    FX_TRADING_DAY,
    calendar_definition,
    calendar_for_currency,
)

EXECUTION_TIMEZONE: Final = "America/New_York"
EXECUTION_LOCAL_TIME: Final = time(17, 5)
CERTIFIED_STATUS: Final = "CERTIFIED"
CERTIFIED_STATUSES: Final = frozenset({CERTIFIED_STATUS, "PASS"})
_NY_ZONE: Final = ZoneInfo(EXECUTION_TIMEZONE)


class RateVersionLike(Protocol):
    """Structural surface required from an immutable rate-vintage record."""

    currency: str
    series_id: str
    observation_date: date
    value: float
    publication_timestamp: datetime
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime
    source_snapshot_sha256: str
    revision_identifier: str
    certification_status: str
    calendar_id: str


@dataclass(frozen=True)
class AlignedRate:
    """One auditable currency/day point-in-time alignment result."""

    currency: str
    trading_day: date
    strategy_timestamp: datetime
    dataset_freeze_id: str
    selected_rate_version: str | None
    series_id: str | None
    value: float | None
    observation_date: date | None
    publication_timestamp: datetime | None
    effective_timestamp: datetime | None
    availability_timestamp: datetime | None
    age_calendar_days: int | None
    carry_forward_reason: str | None
    missing_reason: str | None
    source_snapshot_sha256: str | None
    certification_status: str
    calendar_id: str
    calendar_version: str = CALENDAR_VERSION

    def as_record(self) -> dict[str, object]:
        """Return a canonical JSON-compatible audit record."""
        record = asdict(self)
        for field in (
            "trading_day",
            "observation_date",
            "strategy_timestamp",
            "publication_timestamp",
            "effective_timestamp",
            "availability_timestamp",
        ):
            value = record[field]
            if isinstance(value, datetime):
                record[field] = _format_timestamp(value)
            elif isinstance(value, date):
                record[field] = value.isoformat()
        return record


@dataclass(frozen=True)
class AlignedRatePanel:
    dataset_freeze_id: str
    rows: tuple[AlignedRate, ...]
    panel_sha256: str
    status: str

    def summary(self) -> dict[str, object]:
        missing = sum(row.missing_reason is not None for row in self.rows)
        return {
            "dataset_freeze_id": self.dataset_freeze_id,
            "execution_time": "17:05",
            "execution_timezone": EXECUTION_TIMEZONE,
            "calendar_version": CALENDAR_VERSION,
            "row_count": len(self.rows),
            "missing_count": missing,
            "panel_sha256": self.panel_sha256,
            "interpolation_used": False,
            "backfill_used": False,
            "status": self.status,
        }


def strategy_timestamp(trading_day: date) -> datetime:
    """Construct the frozen execution timestamp with the correct NY DST offset."""
    if not isinstance(trading_day, date):
        raise TypeError("Trading day must be a date")
    return datetime.combine(trading_day, EXECUTION_LOCAL_TIME, _NY_ZONE)


def align_rate_for_day(
    versions: Iterable[RateVersionLike],
    currency: str,
    trading_day: date,
    dataset_freeze_id: str,
    *,
    certified_event_dates: frozenset[date] = frozenset(),
) -> AlignedRate:
    """Select the latest certified version available at the frozen timestamp."""
    _validate_freeze_id(dataset_freeze_id)
    source_calendar = calendar_for_currency(currency)
    timestamp = strategy_timestamp(trading_day)
    timestamp_utc = timestamp.astimezone(UTC)
    currency_versions = tuple(version for version in versions if version.currency == currency)
    certified = tuple(
        version
        for version in currency_versions
        if version.certification_status in CERTIFIED_STATUSES
        and version.calendar_id == source_calendar.calendar_id
    )
    eligible = tuple(
        version
        for version in certified
        if _aware_utc(version.strategy_availability_timestamp) <= timestamp_utc
        and version.observation_date <= trading_day
    )
    if not eligible:
        if not currency_versions:
            reason = "NO_RATE_VERSION_IN_DATASET_FREEZE"
        elif not certified:
            reason = "NO_CERTIFIED_RATE_VERSION_IN_DATASET_FREEZE"
        else:
            reason = "NO_CERTIFIED_RATE_AVAILABLE_AS_OF_TIMESTAMP"
        return _missing_rate(
            currency,
            trading_day,
            timestamp,
            dataset_freeze_id,
            source_calendar.calendar_id,
            reason,
        )

    selected = max(
        eligible,
        key=lambda version: (
            version.observation_date,
            _aware_utc(version.strategy_availability_timestamp),
            _aware_utc(version.publication_timestamp),
            version.revision_identifier,
            version.source_snapshot_sha256,
        ),
    )
    age = (trading_day - selected.observation_date).days
    reason = _carry_forward_reason(
        source_calendar.calendar_id,
        selected.observation_date,
        trading_day,
        certified_event_dates,
    )
    return AlignedRate(
        currency=currency,
        trading_day=trading_day,
        strategy_timestamp=timestamp,
        dataset_freeze_id=dataset_freeze_id,
        selected_rate_version=_version_identity(selected),
        series_id=selected.series_id,
        value=float(selected.value),
        observation_date=selected.observation_date,
        publication_timestamp=_aware_utc(selected.publication_timestamp),
        effective_timestamp=_aware_utc(selected.effective_timestamp),
        availability_timestamp=_aware_utc(selected.strategy_availability_timestamp),
        age_calendar_days=age,
        carry_forward_reason=reason,
        missing_reason=None,
        source_snapshot_sha256=selected.source_snapshot_sha256,
        certification_status=selected.certification_status,
        calendar_id=source_calendar.calendar_id,
    )


def align_rate_panel(
    versions: Sequence[RateVersionLike],
    trading_days: Iterable[date],
    dataset_freeze_id: str,
    *,
    currencies: Sequence[str] = AMENDED_CURRENCY_ORDER,
    certified_event_dates: frozenset[date] = frozenset(),
) -> AlignedRatePanel:
    """Build a deterministic currency-by-FX-day panel without interpolation."""
    _validate_freeze_id(dataset_freeze_id)
    frozen_trading_days = tuple(trading_days)
    if len(set(currencies)) != len(currencies):
        raise ValueError("Currencies must be unique")
    if len(set(frozen_trading_days)) != len(frozen_trading_days):
        raise ValueError("Trading days must be unique")
    fx_calendar = calendar_definition(FX_TRADING_DAY)
    for day in frozen_trading_days:
        if not fx_calendar.is_open(day):
            raise ValueError(f"Date is not an explicit FX trading day: {day.isoformat()}")
    rows = tuple(
        align_rate_for_day(
            versions,
            currency,
            trading_day,
            dataset_freeze_id,
            certified_event_dates=certified_event_dates,
        )
        for trading_day in sorted(frozen_trading_days)
        for currency in currencies
    )
    payload = [row.as_record() for row in rows]
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()
    status = (
        "F0RPE2E_RATE_ALIGNMENT_CERTIFIED"
        if all(row.missing_reason is None for row in rows)
        else "BLOCKED_BY_RATE_AVAILABILITY_ALIGNMENT"
    )
    return AlignedRatePanel(dataset_freeze_id, rows, digest, status)


def _carry_forward_reason(
    calendar_id: str,
    observation_date: date,
    trading_day: date,
    event_dates: frozenset[date],
) -> str:
    if observation_date == trading_day:
        return "CURRENT_CERTIFIED_OFFICIAL_RATE"
    definition = calendar_definition(calendar_id)
    if calendar_id == BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR:
        later_events = tuple(day for day in event_dates if observation_date < day <= trading_day)
        return (
            "AWAITING_CERTIFIED_POLICY_EVENT_VERSION"
            if later_events
            else "BETWEEN_CERTIFIED_POLICY_EVENTS"
        )
    intervening = tuple(
        observation_date.fromordinal(ordinal)
        for ordinal in range(observation_date.toordinal() + 1, trading_day.toordinal())
    )
    if intervening and all(not definition.is_open(day) for day in intervening):
        return "SOURCE_CALENDAR_CLOSED"
    return "NO_NEW_CERTIFIED_OFFICIAL_RATE_AVAILABLE"


def _missing_rate(
    currency: str,
    trading_day: date,
    timestamp: datetime,
    dataset_freeze_id: str,
    calendar_id: str,
    reason: str,
) -> AlignedRate:
    return AlignedRate(
        currency=currency,
        trading_day=trading_day,
        strategy_timestamp=timestamp,
        dataset_freeze_id=dataset_freeze_id,
        selected_rate_version=None,
        series_id=None,
        value=None,
        observation_date=None,
        publication_timestamp=None,
        effective_timestamp=None,
        availability_timestamp=None,
        age_calendar_days=None,
        carry_forward_reason=None,
        missing_reason=reason,
        source_snapshot_sha256=None,
        certification_status="MISSING",
        calendar_id=calendar_id,
    )


def _version_identity(version: RateVersionLike) -> str:
    explicit = getattr(version, "version_id", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    payload = "|".join(
        (
            version.currency,
            version.series_id,
            version.observation_date.isoformat(),
            _format_timestamp(version.publication_timestamp),
            version.revision_identifier,
            version.source_snapshot_sha256,
        )
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Rate timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _validate_freeze_id(dataset_freeze_id: str) -> None:
    if not isinstance(dataset_freeze_id, str) or not dataset_freeze_id.strip():
        raise ValueError("An explicit dataset_freeze_id is required")
