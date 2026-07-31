from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidence,
    PublicationEvidenceKind,
    RevisionStatus,
    legacy_effr_publication_evidence,
    modern_effr_publication_evidence,
)


def test_legacy_uses_day_envelope_and_delays_one_execution() -> None:
    evidence = legacy_effr_publication_evidence(date(2016, 1, 4))

    assert evidence.actual_publication_timestamp is None
    assert evidence.publication_evidence_kind is PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE
    assert evidence.publication_lower_bound == datetime(2016, 1, 5, tzinfo=NEW_YORK_ZONE)
    assert evidence.publication_upper_bound == datetime(2016, 1, 6, tzinfo=NEW_YORK_ZONE)
    assert evidence.publication_upper_bound_exclusive is True
    assert evidence.strategy_availability_timestamp == datetime(
        2016, 1, 6, 17, 5, tzinfo=NEW_YORK_ZONE
    )
    publication_day_execution = datetime(2016, 1, 5, 17, 5, tzinfo=NEW_YORK_ZONE)
    assert publication_day_execution < evidence.strategy_availability_timestamp


def test_modern_is_available_after_revision_boundary_on_publication_day() -> None:
    evidence = modern_effr_publication_evidence(date(2016, 3, 1))

    assert evidence.actual_publication_timestamp is None
    assert evidence.publication_evidence_kind is PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE
    assert evidence.publication_lower_bound == datetime(2016, 3, 2, tzinfo=NEW_YORK_ZONE)
    assert evidence.publication_upper_bound == datetime(
        2016, 3, 2, 14, 30, tzinfo=NEW_YORK_ZONE
    )
    assert evidence.strategy_availability_timestamp == datetime(
        2016, 3, 2, 17, 5, tzinfo=NEW_YORK_ZONE
    )


def test_weekend_and_new_york_fed_holiday_boundaries() -> None:
    weekend = legacy_effr_publication_evidence(date(2016, 1, 8))
    holiday = legacy_effr_publication_evidence(date(2016, 1, 15))

    assert weekend.publication_lower_bound.date() == date(2016, 1, 11)
    assert weekend.strategy_availability_timestamp.date() == date(2016, 1, 12)
    assert holiday.publication_lower_bound.date() == date(2016, 1, 19)
    assert holiday.strategy_availability_timestamp.date() == date(2016, 1, 20)


def test_dst_offset_is_derived_from_execution_and_publication_day() -> None:
    evidence = modern_effr_publication_evidence(date(2016, 3, 11))

    assert evidence.publication_lower_bound.date() == date(2016, 3, 14)
    assert evidence.publication_upper_bound.utcoffset() == timedelta(hours=-4)
    assert evidence.strategy_availability_timestamp.utcoffset() == timedelta(hours=-4)


def test_interval_evidence_cannot_claim_an_actual_timestamp() -> None:
    lower = datetime(2016, 1, 5, tzinfo=NEW_YORK_ZONE)
    upper = datetime(2016, 1, 6, tzinfo=NEW_YORK_ZONE)

    with pytest.raises(ValueError, match="cannot claim an actual timestamp"):
        PublicationEvidence(
            actual_publication_timestamp=lower,
            publication_lower_bound=lower,
            publication_upper_bound=upper,
            publication_upper_bound_exclusive=True,
            publication_evidence_kind=PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE,
            publication_evidence_source="official-source",
            effective_timestamp=upper,
            strategy_availability_timestamp=upper,
        )


def test_strategy_availability_must_follow_upper_and_effective_bounds() -> None:
    lower = datetime(2016, 1, 5, tzinfo=NEW_YORK_ZONE)
    upper = datetime(2016, 1, 6, tzinfo=NEW_YORK_ZONE)

    with pytest.raises(ValueError, match="precedes publication upper bound"):
        PublicationEvidence(
            actual_publication_timestamp=None,
            publication_lower_bound=lower,
            publication_upper_bound=upper,
            publication_upper_bound_exclusive=True,
            publication_evidence_kind=PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE,
            publication_evidence_source="official-source",
            effective_timestamp=upper,
            strategy_availability_timestamp=upper - timedelta(seconds=1),
        )


def test_revision_statuses_include_nullable_final_history_semantics() -> None:
    assert RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value == (
        "FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID"
    )
    assert RevisionStatus.UNKNOWN_REJECTED.value == "UNKNOWN_REJECTED"
