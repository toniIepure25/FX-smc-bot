from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidenceKind,
    RevisionStatus,
    legacy_effr_publication_evidence,
)
from fx_smc_bot.research.rate_vintage_store import (
    V3_SCHEMA_VERSION,
    V4_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageConflictError,
    RateVintageIntegrityError,
    RateVintageStore,
)


@dataclass(frozen=True)
class SyntheticRequest:
    adapter_id: str = "SYNTHETIC_USD_OFFICIAL_V4"
    currency: str = "USD"
    series_id: str = "EFFR"
    source_publisher: str = "Federal Reserve Bank of New York"
    source_endpoint_role: str = "BOUNDED_HISTORICAL_EXPORT"
    start: date = date(2016, 1, 1)
    end: date = date(2016, 1, 31)
    url: str = "https://official.invalid/rates"
    method: str = "GET"
    query_parameters: tuple[tuple[str, str], ...] = (
        ("end", "2016-01-31"),
        ("start", "2016-01-01"),
    )
    request_headers: tuple[tuple[str, str], ...] = (("Accept", "application/json"),)

    @property
    def request_identity(self) -> str:
        payload = {
            "adapter_id": self.adapter_id,
            "currency": self.currency,
            "end": self.end.isoformat(),
            "endpoint_role": self.source_endpoint_role,
            "method": self.method,
            "query_parameters": self.query_parameters,
            "series_id": self.series_id,
            "start": self.start.isoformat(),
            "url": self.url,
            "endpoint_declaration_sha256": None,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True)
class SyntheticSnapshot:
    request: SyntheticRequest
    payload: bytes
    response_headers: tuple[tuple[str, str], ...]
    retrieved_at: datetime
    source_snapshot_sha256: str


@dataclass(frozen=True)
class SyntheticFirewallCertification:
    request_identity: str
    schema_id: str
    rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class SyntheticVersion:
    currency: str
    series_id: str
    observation_date: date
    value: float
    publication_timestamp: datetime | None
    publication_lower_bound: datetime
    publication_upper_bound: datetime
    publication_upper_bound_exclusive: bool
    publication_evidence_kind: PublicationEvidenceKind
    publication_evidence_source: str
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime
    source_publisher: str
    source_document_id: str
    source_endpoint_role: str
    source_snapshot_sha256: str
    parser_version: str
    revision_identifier: str | None
    revision_status: RevisionStatus
    day_count_convention: str
    calendar_id: str
    retrieved_at: datetime
    source_adapter_id: str
    source_request_identity: str
    schema_fingerprint: str
    source_row_ordinal: int


def _snapshot() -> tuple[SyntheticSnapshot, SyntheticFirewallCertification]:
    request = SyntheticRequest()
    rows = ({"currency": "USD", "observationDate": "2016-01-04", "seriesId": "EFFR"},)
    payload = json.dumps(
        {"schema": "synthetic-v4", "observations": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    snapshot = SyntheticSnapshot(
        request=request,
        payload=payload,
        response_headers=(("content-type", "application/json"),),
        retrieved_at=datetime(2016, 2, 1, 12, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )
    certification = SyntheticFirewallCertification(
        request_identity=request.request_identity,
        schema_id="synthetic-v4",
        rows=rows,
    )
    return snapshot, certification


def _store(tmp_path: Path) -> tuple[RateVintageStore, SyntheticSnapshot]:
    store = RateVintageStore(tmp_path / "v4.sqlite3", schema_version=V4_SCHEMA_VERSION)
    snapshot, certification = _snapshot()
    store.append_source_snapshot(snapshot, firewall_certification=certification)
    return store, snapshot


def _legacy_version(snapshot: SyntheticSnapshot, *, value: float = 0.0037) -> SyntheticVersion:
    observation = date(2016, 1, 4)
    evidence = legacy_effr_publication_evidence(observation)
    return SyntheticVersion(
        currency="USD",
        series_id="EFFR",
        observation_date=observation,
        value=value,
        publication_timestamp=evidence.actual_publication_timestamp,
        publication_lower_bound=evidence.publication_lower_bound,
        publication_upper_bound=evidence.publication_upper_bound,
        publication_upper_bound_exclusive=evidence.publication_upper_bound_exclusive,
        publication_evidence_kind=evidence.publication_evidence_kind,
        publication_evidence_source=evidence.publication_evidence_source,
        effective_timestamp=evidence.effective_timestamp,
        strategy_availability_timestamp=evidence.strategy_availability_timestamp,
        source_publisher=snapshot.request.source_publisher,
        source_document_id="NY_FED_EFFR_2016-01-04",
        source_endpoint_role=snapshot.request.source_endpoint_role,
        source_snapshot_sha256=snapshot.source_snapshot_sha256,
        parser_version="NY_FED_EFFR_V4_TEST",
        revision_identifier=None,
        revision_status=RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID,
        day_count_convention="ACT_360",
        calendar_id="NEW_YORK_FED_BUSINESS_DAY",
        retrieved_at=snapshot.retrieved_at,
        source_adapter_id=snapshot.request.adapter_id,
        source_request_identity=snapshot.request.request_identity,
        schema_fingerprint=hashlib.sha256(b"synthetic-v4-schema").hexdigest(),
        source_row_ordinal=0,
    )


def _freeze(store: RateVintageStore, version_id: str) -> str:
    store.append_certification(
        version_id,
        status="PASS",
        certified_at=datetime(2016, 2, 1, 13, tzinfo=UTC),
    )
    return store.create_dataset_freeze(
        "SYNTHETIC_V4_FREEZE",
        [version_id],
        created_at=datetime(2016, 2, 2, tzinfo=UTC),
    ).dataset_freeze_id


def test_v4_is_explicit_reopenable_and_clean_database_only(tmp_path: Path) -> None:
    database = tmp_path / "v4.sqlite3"
    store = RateVintageStore(database, schema_version=V4_SCHEMA_VERSION)
    assert store.schema_version == V4_SCHEMA_VERSION
    columns = {
        str(row[1]): (str(row[2]), int(row[3]))
        for row in store._connection.execute("PRAGMA table_info(rate_versions)")
    }
    assert columns["publication_timestamp"] == ("TEXT", 0)
    assert columns["publication_lower_bound"] == ("TEXT", 1)
    assert columns["publication_upper_bound"] == ("TEXT", 1)
    assert columns["publication_evidence_kind"] == ("TEXT", 1)
    assert columns["publication_evidence_source"] == ("TEXT", 1)
    assert columns["revision_identifier"] == ("TEXT", 0)
    assert columns["schema_fingerprint"] == ("TEXT", 1)
    assert columns["source_row_ordinal"] == ("INTEGER", 1)
    indexes = {
        str(row[1]): int(row[4])
        for row in store._connection.execute("PRAGMA index_list(rate_versions)")
    }
    assert indexes["uq_v4_exact_rate_version_identity"] == 1
    store.close()

    with RateVintageStore(database, schema_version=V4_SCHEMA_VERSION) as reopened:
        assert reopened.schema_version == V4_SCHEMA_VERSION
    with pytest.raises(RateVintageIntegrityError, match="in-place schema upgrades"):
        RateVintageStore(database, schema_version=V3_SCHEMA_VERSION)


def test_nullable_identity_replays_and_rejects_conflicting_final_history(
    tmp_path: Path,
) -> None:
    store, snapshot = _store(tmp_path)
    first = _legacy_version(snapshot)
    first_id = store.append_rate_version(first)

    assert store.append_rate_version(first) == first_id
    with pytest.raises(RateVintageConflictError, match="Conflicting final-history"):
        store.append_rate_version(replace(first, value=0.0038))
    assert store.table_counts()["rate_versions"] == 1


def test_partial_unique_index_preserves_exact_identity_conflicts(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    actual = datetime(2016, 1, 5, 14, 30, tzinfo=NEW_YORK_ZONE)
    exact = replace(
        _legacy_version(snapshot),
        publication_timestamp=actual,
        publication_lower_bound=actual,
        publication_upper_bound=actual,
        publication_upper_bound_exclusive=False,
        publication_evidence_kind=PublicationEvidenceKind.EXACT_TIMESTAMP,
        publication_evidence_source="SYNTHETIC_EXACT_PUBLICATION",
        effective_timestamp=actual,
        strategy_availability_timestamp=actual,
        revision_identifier="ORIGINAL-1",
        revision_status=RevisionStatus.ORIGINAL_EXPLICIT,
    )
    store.append_rate_version(exact)

    with pytest.raises(RateVintageConflictError, match="duplicate exact"):
        store.append_rate_version(replace(exact, value=0.004))


def test_freeze_and_get_rate_as_of_round_trip_censored_fields(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version = _legacy_version(snapshot)
    version_id = store.append_rate_version(version)
    freeze_id = _freeze(store, version_id)
    availability = version.strategy_availability_timestamp

    before = store.get_rate_as_of("USD", availability - timedelta(seconds=1), freeze_id)
    at = store.get_rate_as_of("USD", availability, freeze_id)
    assert isinstance(before, MissingRate)
    assert isinstance(at, AvailableRate)
    assert at.version_id == version_id
    assert at.publication_timestamp is None
    assert at.publication_lower_bound == version.publication_lower_bound.astimezone(UTC)
    assert at.publication_upper_bound == version.publication_upper_bound.astimezone(UTC)
    assert at.publication_upper_bound_exclusive is True
    assert at.publication_evidence_kind is PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE
    assert at.publication_evidence_source == version.publication_evidence_source
    assert at.revision_identifier is None
    assert at.schema_fingerprint == version.schema_fingerprint
    assert at.source_row_ordinal == 0

    later_actual = availability + timedelta(days=1)
    store.append_rate_version(
        replace(
            version,
            value=0.0042,
            publication_timestamp=later_actual,
            publication_lower_bound=later_actual,
            publication_upper_bound=later_actual,
            publication_upper_bound_exclusive=False,
            publication_evidence_kind=PublicationEvidenceKind.EXACT_TIMESTAMP,
            publication_evidence_source="SYNTHETIC_EXPLICIT_REVISION",
            effective_timestamp=later_actual,
            strategy_availability_timestamp=later_actual,
            revision_identifier="REVISION-1",
            revision_status=RevisionStatus.REVISED_EXPLICIT,
        )
    )
    replay = store.get_rate_as_of("USD", availability, freeze_id)
    assert isinstance(replay, AvailableRate)
    assert replay.version_id == version_id
    assert replay.value == version.value


def test_v4_rejects_missing_or_incoherent_publication_evidence(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version = _legacy_version(snapshot)
    missing_source = {
        name: getattr(version, name)
        for name in version.__dataclass_fields__
        if name != "publication_evidence_source"
    }
    with pytest.raises(RateVintageIntegrityError, match="publication_evidence_source"):
        store.append_rate_version(missing_source)
    with pytest.raises(RateVintageIntegrityError, match="cannot claim an actual timestamp"):
        store.append_rate_version(
            replace(version, publication_timestamp=version.publication_lower_bound)
        )
    with pytest.raises(RateVintageIntegrityError, match="requires an official revision"):
        store.append_rate_version(
            replace(version, revision_status=RevisionStatus.ORIGINAL_EXPLICIT)
        )
    with pytest.raises(RateVintageIntegrityError, match="requires a null official revision"):
        store.append_rate_version(
            replace(version, revision_identifier="NOT-ALLOWED-FOR-FINAL-HISTORY")
        )


def test_v4_rate_versions_remain_append_only_at_sql_boundary(tmp_path: Path) -> None:
    database = tmp_path / "v4.sqlite3"
    store, snapshot = _store(tmp_path)
    store.append_rate_version(_legacy_version(snapshot))
    store.close()

    connection = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE rate_versions SET value_text = '0.0'")
    connection.close()
