from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fx_smc_bot.research.rate_vintage_store import (
    SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageConflictError,
    RateVintageIntegrityError,
    RateVintageStore,
)


@dataclass(frozen=True)
class SyntheticRequest:
    adapter_id: str
    request_identity: str


@dataclass(frozen=True)
class SyntheticSnapshot:
    request: SyntheticRequest
    payload: bytes
    response_headers: tuple[tuple[str, str], ...]
    retrieved_at: datetime
    source_snapshot_sha256: str


@dataclass(frozen=True)
class SyntheticRateVersion:
    currency: str
    series_id: str
    observation_date: date
    value: float
    publication_timestamp: datetime
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime
    source_publisher: str
    source_document_id: str
    source_endpoint_role: str
    source_snapshot_sha256: str
    parser_version: str
    revision_identifier: str
    revision_status: str
    day_count_convention: str
    calendar_id: str
    retrieved_at: datetime


def _request() -> SyntheticRequest:
    return SyntheticRequest(
        adapter_id="SYNTHETIC_USD_OFFICIAL_V1",
        request_identity="synthetic-usd-effr-2010",
    )


def _snapshot(
    payload: bytes = b'{"synthetic_schema":"v1"}',
    *,
    retrieved_at: datetime = datetime(2010, 1, 8, 12, tzinfo=UTC),
) -> SyntheticSnapshot:
    return SyntheticSnapshot(
        request=_request(),
        payload=payload,
        response_headers=(("content-type", "application/json"),),
        retrieved_at=retrieved_at,
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _version(
    snapshot: SyntheticSnapshot,
    *,
    observation: date = date(2010, 1, 4),
    value: float = 0.1,
    publication: datetime = datetime(2010, 1, 5, 9, tzinfo=UTC),
    effective: datetime = datetime(2010, 1, 4, tzinfo=UTC),
    revision_identifier: str = "ORIGINAL-1",
    revision_status: str = "ORIGINAL",
    parser_version: str = "synthetic-parser-v1",
) -> SyntheticRateVersion:
    return SyntheticRateVersion(
        currency="USD",
        series_id="EFFR",
        observation_date=observation,
        value=value,
        publication_timestamp=publication,
        effective_timestamp=effective,
        strategy_availability_timestamp=max(publication, effective),
        source_publisher="Synthetic official publisher",
        source_document_id=f"SYNTHETIC-{observation.isoformat()}",
        source_endpoint_role="HISTORICAL_EXPORT",
        source_snapshot_sha256=snapshot.source_snapshot_sha256,
        parser_version=parser_version,
        revision_identifier=revision_identifier,
        revision_status=revision_status,
        day_count_convention="ACT_360",
        calendar_id="NEW_YORK_FED_BUSINESS_DAY",
        retrieved_at=snapshot.retrieved_at,
    )


def _store(tmp_path: Path) -> tuple[RateVintageStore, SyntheticSnapshot]:
    store = RateVintageStore(tmp_path / "synthetic-rate-vintages.sqlite3")
    snapshot = _snapshot()
    store.append_source_snapshot(snapshot)
    return store, snapshot


def _freeze(
    store: RateVintageStore,
    version_ids: list[str],
    freeze_id: str = "SYNTHETIC_FREEZE_V1",
) -> str:
    return store.create_dataset_freeze(
        freeze_id,
        version_ids,
        created_at=datetime(2010, 2, 1, tzinfo=UTC),
        metadata={"fixture": "schema-only"},
    ).dataset_freeze_id


def test_schema_contains_all_gate_tables_and_enforces_append_only(tmp_path: Path) -> None:
    database = tmp_path / "synthetic-rate-vintages.sqlite3"
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(_version(snapshot))
    _freeze(store, [version_id])

    assert store.schema_version == SCHEMA_VERSION
    assert store.table_counts() == {
        "source_snapshots": 1,
        "ingestion_runs": 0,
        "rate_series": 1,
        "rate_observation_identities": 1,
        "rate_versions": 1,
        "availability_events": 1,
        "certification_results": 0,
        "daily_strategy_rate_panel": 0,
        "dataset_freezes": 1,
        "dataset_freeze_versions": 1,
    }
    store.close()

    connection = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE rate_versions SET value_text = '9.9'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM source_snapshots")
    connection.close()


def test_source_payload_and_ingestion_replay_are_idempotent(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    replay = _snapshot(retrieved_at=snapshot.retrieved_at + timedelta(hours=1))

    assert store.append_source_snapshot(snapshot) == store.append_source_snapshot(replay)
    run_args = {
        "adapter_id": "SYNTHETIC_USD_OFFICIAL_V1",
        "started_at": datetime(2010, 1, 8, 12, tzinfo=UTC),
        "completed_at": datetime(2010, 1, 8, 12, 1, tzinfo=UTC),
        "status": "PASS",
        "snapshot_count": 1,
        "details": {"fixture": True},
    }
    assert store.append_ingestion_run("RUN-1", **run_args) == "RUN-1"
    assert store.append_ingestion_run("RUN-1", **run_args) == "RUN-1"
    with pytest.raises(RateVintageConflictError, match="ingestion run"):
        store.append_ingestion_run("RUN-1", **{**run_args, "status": "FAIL"})


def test_initial_publication_is_missing_before_and_available_after(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(_version(snapshot))
    store.append_certification(
        version_id,
        status="PASS",
        certified_at=datetime(2010, 1, 5, 9, 1, tzinfo=UTC),
    )
    freeze_id = _freeze(store, [version_id])

    before = store.get_rate_as_of("USD", datetime(2010, 1, 5, 8, 59, tzinfo=UTC), freeze_id)
    after = store.get_rate_as_of("USD", datetime(2010, 1, 5, 9, 2, tzinfo=UTC), freeze_id)

    assert isinstance(before, MissingRate)
    assert before.reason == "NO_FROZEN_VERSION_AVAILABLE_AS_OF_STRATEGY_TIMESTAMP"
    assert isinstance(after, AvailableRate)
    assert after.value == 0.1
    assert after.certification_status == "PASS"
    assert store.append_daily_strategy_rate(after) == store.append_daily_strategy_rate(after)


def test_same_day_revision_never_backfills_before_revision_time(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    original = store.append_rate_version(_version(snapshot))
    revision = store.append_rate_version(
        _version(
            snapshot,
            value=0.11,
            publication=datetime(2010, 1, 5, 14, 30, tzinfo=UTC),
            revision_identifier="REVISION-1",
            revision_status="REVISED",
        )
    )
    freeze_id = _freeze(store, [original, revision])

    before_revision = store.get_rate_as_of(
        "USD", datetime(2010, 1, 5, 14, 29, tzinfo=UTC), freeze_id
    )
    after_revision = store.get_rate_as_of(
        "USD", datetime(2010, 1, 5, 14, 30, tzinfo=UTC), freeze_id
    )

    assert isinstance(before_revision, AvailableRate)
    assert before_revision.version_id == original
    assert before_revision.value == 0.1
    assert isinstance(after_revision, AvailableRate)
    assert after_revision.version_id == revision
    assert after_revision.value == 0.11


def test_later_historical_revision_does_not_replace_a_newer_observation(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    old_original = store.append_rate_version(_version(snapshot))
    newer = store.append_rate_version(
        _version(
            snapshot,
            observation=date(2010, 1, 5),
            value=0.2,
            publication=datetime(2010, 1, 6, 9, tzinfo=UTC),
            revision_identifier="ORIGINAL-2",
        )
    )
    old_late_revision = store.append_rate_version(
        _version(
            snapshot,
            value=0.15,
            publication=datetime(2010, 1, 7, 15, tzinfo=UTC),
            revision_identifier="HISTORICAL-REVISION-1",
            revision_status="REVISED",
        )
    )
    freeze_id = _freeze(store, [old_original, newer, old_late_revision])

    result = store.get_rate_as_of("USD", datetime(2010, 1, 8, 17, tzinfo=UTC), freeze_id)
    assert isinstance(result, AvailableRate)
    assert result.version_id == newer
    assert result.observation_date == date(2010, 1, 5)


@pytest.mark.parametrize(
    ("publication", "effective", "available"),
    [
        (
            datetime(2010, 1, 5, 9, tzinfo=UTC),
            datetime(2010, 1, 6, 0, tzinfo=UTC),
            datetime(2010, 1, 6, 0, tzinfo=UTC),
        ),
        (
            datetime(2010, 1, 6, 9, tzinfo=UTC),
            datetime(2010, 1, 5, 0, tzinfo=UTC),
            datetime(2010, 1, 6, 9, tzinfo=UTC),
        ),
    ],
)
def test_availability_is_maximum_of_publication_and_effective_time(
    tmp_path: Path,
    publication: datetime,
    effective: datetime,
    available: datetime,
) -> None:
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(
        _version(snapshot, publication=publication, effective=effective)
    )
    freeze_id = _freeze(store, [version_id])

    assert isinstance(
        store.get_rate_as_of("USD", available - timedelta(seconds=1), freeze_id), MissingRate
    )
    selected = store.get_rate_as_of("USD", available, freeze_id)
    assert isinstance(selected, AvailableRate)
    assert selected.strategy_availability_timestamp == available


def test_weekend_and_holiday_carry_use_last_officially_available_rate(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    friday = store.append_rate_version(
        _version(
            snapshot,
            observation=date(2010, 1, 8),
            publication=datetime(2010, 1, 8, 9, tzinfo=UTC),
            effective=datetime(2010, 1, 8, tzinfo=UTC),
        )
    )
    freeze_id = _freeze(store, [friday])

    weekend = store.get_rate_as_of("USD", datetime(2010, 1, 10, 17, tzinfo=UTC), freeze_id)
    holiday = store.get_rate_as_of("USD", datetime(2010, 1, 11, 17, tzinfo=UTC), freeze_id)
    assert isinstance(weekend, AvailableRate)
    assert isinstance(holiday, AvailableRate)
    assert weekend.version_id == holiday.version_id == friday
    assert weekend.carry_forward_reason == "LAST_OFFICIALLY_AVAILABLE_RATE"
    assert holiday.age_in_calendar_days == 3


def test_missing_currency_and_missing_publication_fail_closed(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(_version(snapshot))
    freeze_id = _freeze(store, [version_id])

    assert isinstance(
        store.get_rate_as_of("EUR", datetime(2010, 1, 6, tzinfo=UTC), freeze_id), MissingRate
    )
    invalid = {
        field: getattr(_version(snapshot), field)
        for field in _version(snapshot).__dataclass_fields__
    }
    invalid["publication_timestamp"] = None
    with pytest.raises(RateVintageIntegrityError, match="publication_timestamp"):
        store.append_rate_version(invalid)


def test_duplicate_version_is_idempotent_but_value_or_parser_conflict_is_rejected(
    tmp_path: Path,
) -> None:
    store, snapshot = _store(tmp_path)
    version = _version(snapshot)
    version_id = store.append_rate_version(version)

    assert store.append_rate_version(version) == version_id
    with pytest.raises(RateVintageConflictError, match="duplicate rate version"):
        store.append_rate_version(replace(version, value=0.2))
    with pytest.raises(RateVintageConflictError, match="duplicate rate version"):
        store.append_rate_version(replace(version, parser_version="synthetic-parser-v2"))


def test_freeze_pins_exact_versions_and_conflicting_replay_is_rejected(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    original = store.append_rate_version(_version(snapshot))
    freeze_id = _freeze(store, [original])
    revision = store.append_rate_version(
        _version(
            snapshot,
            value=0.11,
            publication=datetime(2010, 1, 5, 14, 30, tzinfo=UTC),
            revision_identifier="REVISION-1",
            revision_status="REVISED",
        )
    )

    frozen = store.get_rate_as_of("USD", datetime(2010, 1, 6, tzinfo=UTC), freeze_id)
    assert isinstance(frozen, AvailableRate)
    assert frozen.version_id == original
    assert frozen.value == 0.1
    assert _freeze(store, [original]) == freeze_id
    with pytest.raises(RateVintageConflictError, match="dataset freeze"):
        _freeze(store, [original, revision])


def test_invalid_availability_unknown_snapshot_and_unknown_freeze_are_rejected(
    tmp_path: Path,
) -> None:
    store, snapshot = _store(tmp_path)
    version = _version(snapshot)
    invalid_availability = {
        field: getattr(version, field)
        for field in version.__dataclass_fields__
    }
    invalid_availability["strategy_availability_timestamp"] = datetime(
        2010, 1, 5, 8, tzinfo=UTC
    )
    with pytest.raises(RateVintageIntegrityError, match=r"max\(publication, effective\)"):
        store.append_rate_version(invalid_availability)
    with pytest.raises(RateVintageIntegrityError, match="unknown source snapshot"):
        store.append_rate_version(replace(version, source_snapshot_sha256="f" * 64))
    with pytest.raises(RateVintageIntegrityError, match="Unknown dataset freeze"):
        store.get_rate_as_of("USD", datetime(2010, 1, 6, tzinfo=UTC), "UNKNOWN")
