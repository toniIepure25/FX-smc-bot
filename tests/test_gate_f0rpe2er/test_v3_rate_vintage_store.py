from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fx_smc_bot.research.rate_vintage_store import (
    SCHEMA_VERSION,
    V3_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageConflictError,
    RateVintageIntegrityError,
    RateVintageStore,
)


@dataclass(frozen=True)
class SyntheticRequest:
    adapter_id: str
    currency: str
    series_id: str
    source_publisher: str
    source_endpoint_role: str
    start: date
    end: date
    url: str
    query_parameters: tuple[tuple[str, str], ...]
    request_headers: tuple[tuple[str, str], ...]
    method: str = "GET"

    @property
    def request_identity(self) -> str:
        record = {
            "adapter_id": self.adapter_id,
            "currency": self.currency,
            "end": self.end.isoformat(),
            "endpoint_role": self.source_endpoint_role,
            "method": self.method,
            "query_parameters": self.query_parameters,
            "series_id": self.series_id,
            "start": self.start.isoformat(),
            "url": self.url,
        }
        encoded = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SyntheticSnapshot:
    request: SyntheticRequest
    payload: bytes
    content_type: str
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
    source_adapter_id: str
    source_request_identity: str


def _request() -> SyntheticRequest:
    return SyntheticRequest(
        adapter_id="SYNTHETIC_USD_OFFICIAL_V2",
        currency="USD",
        series_id="EFFR",
        source_publisher="Synthetic official publisher",
        source_endpoint_role="BOUNDED_HISTORICAL_EXPORT",
        start=date(2010, 1, 1),
        end=date(2010, 1, 31),
        url="https://official.invalid/rates",
        query_parameters=(("end", "2010-01-31"), ("start", "2010-01-01")),
        request_headers=(("Accept", "application/json"),),
    )


def _snapshot(
    request: SyntheticRequest | None = None,
    *,
    retrieved_at: datetime = datetime(2010, 2, 1, 12, tzinfo=UTC),
) -> SyntheticSnapshot:
    document = {
        "schema": "synthetic-v2",
        "observations": [
            {
                "currency": "USD",
                "fixture": "synthetic",
                "observationDate": "2010-01-04",
                "seriesId": "EFFR",
            }
        ],
    }
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return SyntheticSnapshot(
        request=request or _request(),
        payload=payload,
        content_type="application/json",
        response_headers=(("content-type", "application/json"),),
        retrieved_at=retrieved_at,
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _firewall_certification(
    snapshot: SyntheticSnapshot,
) -> SyntheticFirewallCertification:
    document = json.loads(snapshot.payload)
    return SyntheticFirewallCertification(
        request_identity=snapshot.request.request_identity,
        schema_id=str(document["schema"]),
        rows=tuple(document["observations"]),
    )


def _version(
    snapshot: SyntheticSnapshot,
    *,
    observation_date: date = date(2010, 1, 4),
    value: float = 0.1,
    publication: datetime = datetime(2010, 1, 5, 9, tzinfo=UTC),
    revision_identifier: str = "ORIGINAL",
    revision_status: str = "ORIGINAL",
) -> SyntheticVersion:
    effective = datetime.combine(observation_date, datetime.min.time(), tzinfo=UTC)
    return SyntheticVersion(
        currency="USD",
        series_id="EFFR",
        observation_date=observation_date,
        value=value,
        publication_timestamp=publication,
        effective_timestamp=effective,
        strategy_availability_timestamp=max(publication, effective),
        source_publisher="Synthetic official publisher",
        source_document_id=f"SYNTHETIC-{observation_date.isoformat()}",
        source_endpoint_role="BOUNDED_HISTORICAL_EXPORT",
        source_snapshot_sha256=snapshot.source_snapshot_sha256,
        parser_version="synthetic-parser-v2",
        revision_identifier=revision_identifier,
        revision_status=revision_status,
        day_count_convention="ACT_360",
        calendar_id="NEW_YORK_FED_BUSINESS_DAY",
        retrieved_at=snapshot.retrieved_at,
        source_adapter_id=snapshot.request.adapter_id,
        source_request_identity=snapshot.request.request_identity,
    )


def _freeze(store: RateVintageStore, version_ids: list[str]) -> str:
    for version_id in version_ids:
        store.append_certification(
            version_id,
            status="PASS",
            certified_at=datetime(2010, 2, 1, 13, tzinfo=UTC),
            details={"fixture": "synthetic"},
        )
    return store.create_dataset_freeze(
        "SYNTHETIC_V3_FREEZE",
        version_ids,
        created_at=datetime(2010, 2, 2, tzinfo=UTC),
        metadata={"fixture": "synthetic"},
    ).dataset_freeze_id


def _store(tmp_path: Path) -> tuple[RateVintageStore, SyntheticSnapshot]:
    store = RateVintageStore(
        tmp_path / "synthetic-v3.sqlite3", schema_version=V3_SCHEMA_VERSION
    )
    snapshot = _snapshot()
    store.append_source_snapshot(
        snapshot, firewall_certification=_firewall_certification(snapshot)
    )
    return store, snapshot


def test_v3_schema_is_explicit_complete_and_reopenable(tmp_path: Path) -> None:
    database = tmp_path / "synthetic-v3.sqlite3"
    store = RateVintageStore(database, schema_id=V3_SCHEMA_VERSION)
    assert store.schema_version == V3_SCHEMA_VERSION
    store.close()

    reopened = RateVintageStore(database, schema_version=V3_SCHEMA_VERSION)
    table_names = {
        str(row[0])
        for row in reopened._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "source_requests",
        "source_snapshots",
        "ingestion_runs",
        "rate_series",
        "rate_observation_identities",
        "rate_versions",
        "availability_events",
        "certification_results",
        "aligned_daily_rate_panel",
        "dataset_freezes",
    } <= table_names
    reopened.close()


def test_v3_refuses_in_place_upgrade_from_v2(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    RateVintageStore(database).close()

    with pytest.raises(RateVintageIntegrityError, match="new clean database"):
        RateVintageStore(database, schema_version=V3_SCHEMA_VERSION)
    with RateVintageStore(database) as legacy:
        assert legacy.schema_version == SCHEMA_VERSION


def test_exact_request_and_snapshot_replays_are_append_only(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    request = snapshot.request

    assert store.append_source_request(request) == request.request_identity
    conflicting_request = replace(request, source_publisher="Different publisher")
    assert conflicting_request.request_identity == request.request_identity
    with pytest.raises(RateVintageConflictError, match="source request"):
        store.append_source_request(conflicting_request)

    certification = _firewall_certification(snapshot)
    snapshot_id = store.append_source_snapshot(
        snapshot, firewall_certification=certification
    )
    assert snapshot_id == store.append_source_snapshot(
        snapshot, firewall_certification=certification
    )
    with pytest.raises(RateVintageConflictError, match="source snapshot"):
        changed_retrieval = _snapshot(
            request, retrieved_at=snapshot.retrieved_at + timedelta(seconds=1)
        )
        store.append_source_snapshot(
            changed_retrieval,
            firewall_certification=_firewall_certification(changed_retrieval),
        )

    invalid_payload = {
        "request": request,
        "payload": b"different synthetic payload",
        "response_headers": snapshot.response_headers,
        "retrieved_at": snapshot.retrieved_at,
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
    }
    with pytest.raises(RateVintageIntegrityError, match="payload SHA-256"):
        store.append_source_snapshot(
            invalid_payload, firewall_certification=certification
        )


def test_v3_rejects_uncertified_snapshot_without_partial_writes(tmp_path: Path) -> None:
    store = RateVintageStore(
        tmp_path / "uncertified.sqlite3", schema_version=V3_SCHEMA_VERSION
    )
    snapshot = _snapshot()

    with pytest.raises(RateVintageIntegrityError, match="firewall certification"):
        store.append_source_snapshot(snapshot)

    counts = store.table_counts()
    assert counts["source_requests"] == 0
    assert counts["response_firewall_certifications"] == 0
    assert counts["source_snapshots"] == 0


def test_v3_version_requires_exact_registered_request_identity(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version = _version(snapshot)
    assert store.append_rate_version(version)

    unbound = {
        name: getattr(version, name)
        for name in version.__dataclass_fields__
        if name != "source_request_identity"
    }
    with pytest.raises(RateVintageIntegrityError, match="exact source adapter and request"):
        store.append_rate_version(unbound)
    with pytest.raises(RateVintageIntegrityError, match="unknown source snapshot"):
        store.append_rate_version(
            replace(
                version,
                revision_identifier="WRONG-REQUEST",
                source_request_identity="not-the-registered-request",
            )
        )


def test_frozen_certification_and_explicit_as_of_prevent_revision_leakage(
    tmp_path: Path,
) -> None:
    store, snapshot = _store(tmp_path)
    original = store.append_rate_version(_version(snapshot))
    revision = store.append_rate_version(
        _version(
            snapshot,
            value=0.11,
            publication=datetime(2010, 1, 8, 14, tzinfo=UTC),
            revision_identifier="REVISION-1",
            revision_status="REVISED",
        )
    )
    freeze_id = _freeze(store, [original, revision])

    with pytest.raises(TypeError):
        store.get_rate_as_of("USD")  # type: ignore[call-arg]
    before = store.get_rate_as_of(
        "USD", datetime(2010, 1, 8, 13, 59, tzinfo=UTC), freeze_id
    )
    after = store.get_rate_as_of(
        "USD", datetime(2010, 1, 8, 14, tzinfo=UTC), freeze_id
    )
    assert isinstance(before, AvailableRate)
    assert isinstance(after, AvailableRate)
    assert before.version_id == original
    assert after.version_id == revision

    store.append_certification(
        revision,
        status="REJECTED",
        certified_at=datetime(2010, 2, 3, tzinfo=UTC),
    )
    replay = store.get_rate_as_of(
        "USD", datetime(2010, 1, 8, 14, tzinfo=UTC), freeze_id
    )
    assert isinstance(replay, AvailableRate)
    assert replay.version_id == revision
    assert replay.certification_status == "PASS"


def test_v3_aligned_panel_pins_freeze_membership_and_is_append_only(tmp_path: Path) -> None:
    database = tmp_path / "synthetic-v3.sqlite3"
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(_version(snapshot))
    freeze_id = _freeze(store, [version_id])
    selected = store.get_rate_as_of(
        "USD", datetime(2010, 1, 8, 17, tzinfo=UTC), freeze_id
    )
    assert isinstance(selected, AvailableRate)
    record_hash = store.append_aligned_daily_rate(selected)
    assert store.append_daily_strategy_rate(selected) == record_hash
    counts = store.table_counts()
    assert counts["source_requests"] == 1
    assert counts["response_firewall_certifications"] == 1
    assert counts["aligned_daily_rate_panel"] == 1
    assert "daily_strategy_rate_panel" not in counts
    store.close()

    connection = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM aligned_daily_rate_panel")
    connection.close()


def test_v3_missing_result_is_persisted_without_a_latest_fallback(tmp_path: Path) -> None:
    store, snapshot = _store(tmp_path)
    version_id = store.append_rate_version(_version(snapshot))
    freeze_id = _freeze(store, [version_id])
    missing = store.get_rate_as_of(
        "USD", datetime(2010, 1, 5, 8, 59, tzinfo=UTC), freeze_id
    )
    assert isinstance(missing, MissingRate)
    assert store.append_aligned_daily_rate(missing)
