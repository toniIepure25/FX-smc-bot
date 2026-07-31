"""Outcome-blind publication evidence for interval-censored official rates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from fx_smc_bot.research.rate_calendars import (
    FX_TRADING_DAY,
    NEW_YORK_FED_BUSINESS_DAY,
    calendar_definition,
)

OVERLAY_ID: Final = "F0RPE2ERUSDSRLPA_PUBLICATION_CENSORING_OVERLAY_V1"
NEW_YORK_ZONE: Final = ZoneInfo("America/New_York")
PORTFOLIO_EXECUTION_TIME: Final = time(17, 5)
MODERN_EFFR_START: Final = date(2016, 3, 1)


class PublicationEvidenceKind(StrEnum):
    EXACT_TIMESTAMP = "EXACT_TIMESTAMP"
    BOUNDED_TIME_ENVELOPE = "BOUNDED_TIME_ENVELOPE"
    PUBLICATION_DAY_ENVELOPE = "PUBLICATION_DAY_ENVELOPE"


class RevisionStatus(StrEnum):
    ORIGINAL_EXPLICIT = "ORIGINAL_EXPLICIT"
    REVISED_EXPLICIT = "REVISED_EXPLICIT"
    FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID = (
        "FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID"
    )
    UNKNOWN_REJECTED = "UNKNOWN_REJECTED"


@dataclass(frozen=True, slots=True)
class PublicationEvidence:
    """Separate unknown actual publication from conservative availability."""

    actual_publication_timestamp: datetime | None
    publication_lower_bound: datetime
    publication_upper_bound: datetime
    publication_upper_bound_exclusive: bool
    publication_evidence_kind: PublicationEvidenceKind
    publication_evidence_source: str
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime

    def __post_init__(self) -> None:
        timestamps = (
            self.publication_lower_bound,
            self.publication_upper_bound,
            self.effective_timestamp,
            self.strategy_availability_timestamp,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
            raise ValueError("Publication evidence timestamps must be timezone-aware")
        actual = self.actual_publication_timestamp
        if actual is not None and (actual.tzinfo is None or actual.utcoffset() is None):
            raise ValueError("Actual publication timestamp must be timezone-aware")
        if self.publication_lower_bound > self.publication_upper_bound:
            raise ValueError("Publication lower bound exceeds upper bound")
        if not self.publication_evidence_source.strip():
            raise ValueError("Publication evidence source is required")
        if self.strategy_availability_timestamp < self.publication_upper_bound:
            raise ValueError("Strategy availability precedes publication upper bound")
        if self.strategy_availability_timestamp < self.effective_timestamp:
            raise ValueError("Strategy availability precedes effective timestamp")
        if self.publication_evidence_kind is PublicationEvidenceKind.EXACT_TIMESTAMP:
            if actual is None:
                raise ValueError("Exact evidence requires an actual publication timestamp")
            if not (
                self.publication_lower_bound
                == actual
                == self.publication_upper_bound
            ):
                raise ValueError("Exact evidence bounds must equal the actual timestamp")
            if self.publication_upper_bound_exclusive:
                raise ValueError("Exact timestamp evidence cannot have an exclusive bound")
        elif actual is not None:
            raise ValueError("Censored publication evidence cannot claim an actual timestamp")


def next_new_york_fed_publication_day(
    observation_date: date,
    *,
    additional_closures: frozenset[date] = frozenset(),
) -> date:
    """Return the first authorized NY Fed business day after observation."""
    calendar = calendar_definition(NEW_YORK_FED_BUSINESS_DAY)
    candidate = observation_date + timedelta(days=1)
    while not calendar.is_open(candidate, additional_closures=additional_closures):
        candidate += timedelta(days=1)
    return candidate


def first_portfolio_execution_strictly_after(boundary: datetime) -> datetime:
    """Return the first frozen 17:05 FX execution strictly after a boundary."""
    if boundary.tzinfo is None or boundary.utcoffset() is None:
        raise ValueError("Availability boundary must be timezone-aware")
    local_boundary = boundary.astimezone(NEW_YORK_ZONE)
    trading_calendar = calendar_definition(FX_TRADING_DAY)
    candidate_day = local_boundary.date()
    while True:
        if trading_calendar.is_open(candidate_day):
            candidate = datetime.combine(
                candidate_day,
                PORTFOLIO_EXECUTION_TIME,
                NEW_YORK_ZONE,
            )
            if candidate > local_boundary:
                return candidate
        candidate_day += timedelta(days=1)


def legacy_effr_publication_evidence(
    observation_date: date,
    *,
    additional_closures: frozenset[date] = frozenset(),
) -> PublicationEvidence:
    """Build a publication-day envelope without inventing a legacy clock time."""
    if observation_date >= MODERN_EFFR_START:
        raise ValueError("Legacy EFFR evidence requires observation before 2016-03-01")
    publication_day = next_new_york_fed_publication_day(
        observation_date,
        additional_closures=additional_closures,
    )
    lower = datetime.combine(publication_day, time.min, NEW_YORK_ZONE)
    upper = datetime.combine(publication_day + timedelta(days=1), time.min, NEW_YORK_ZONE)
    return PublicationEvidence(
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=True,
        publication_evidence_kind=PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE,
        publication_evidence_source="NY_FED_LEGACY_EFFR_DAILY_PRIOR_DAY_PUBLICATION_V1",
        effective_timestamp=upper,
        strategy_availability_timestamp=first_portfolio_execution_strictly_after(upper),
    )


def modern_effr_publication_evidence(
    observation_date: date,
    *,
    additional_closures: frozenset[date] = frozenset(),
) -> PublicationEvidence:
    """Build the frozen modern final-history revision-complete envelope."""
    if observation_date < MODERN_EFFR_START:
        raise ValueError("Modern EFFR evidence requires observation on or after 2016-03-01")
    publication_day = next_new_york_fed_publication_day(
        observation_date,
        additional_closures=additional_closures,
    )
    lower = datetime.combine(publication_day, time.min, NEW_YORK_ZONE)
    upper = datetime.combine(publication_day, time(14, 30), NEW_YORK_ZONE)
    return PublicationEvidence(
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=False,
        publication_evidence_kind=PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE,
        publication_evidence_source="NY_FED_MODERN_EFFR_REVISION_WINDOW_V1",
        effective_timestamp=upper,
        strategy_availability_timestamp=first_portfolio_execution_strictly_after(upper),
    )
