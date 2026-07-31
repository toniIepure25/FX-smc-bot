"""Append-only point-in-time persistence for certified official rates.

The store deliberately has no implicit "latest" query.  A strategy lookup must
name both its timestamp and an immutable dataset freeze, so later publications
and revisions cannot leak into an earlier replay.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "F0RPE2E_RATE_VINTAGE_STORE_V1"


class RateVintageStoreError(RuntimeError):
    """Base error for point-in-time store failures."""


class RateVintageConflictError(RateVintageStoreError):
    """Raised when a logical append reuses an identity with different content."""


class RateVintageIntegrityError(RateVintageStoreError):
    """Raised when an input would violate point-in-time integrity."""


@dataclass(frozen=True)
class AvailableRate:
    """A frozen rate version available at one explicit strategy timestamp."""

    currency: str
    strategy_timestamp: datetime
    dataset_freeze_id: str
    version_id: str
    series_id: str
    observation_date: date
    value: float
    publication_timestamp: datetime
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime
    revision_identifier: str
    revision_status: str
    day_count_convention: str
    calendar_id: str
    source_snapshot_sha256: str
    certification_status: str | None
    age_in_calendar_days: int
    carry_forward_reason: str | None


@dataclass(frozen=True)
class MissingRate:
    """Fail-closed result when a freeze has no eligible version as of a timestamp."""

    currency: str
    strategy_timestamp: datetime
    dataset_freeze_id: str
    reason: str


@dataclass(frozen=True)
class DatasetFreeze:
    """Immutable set of exact version IDs used by empirical replay."""

    dataset_freeze_id: str
    created_at: datetime
    freeze_sha256: str
    version_ids: tuple[str, ...]


def _value(record: object, name: str) -> Any:
    if isinstance(record, Mapping):
        try:
            return record[name]
        except KeyError as exc:
            raise RateVintageIntegrityError(f"Missing required field: {name}") from exc
    try:
        return getattr(record, name)
    except AttributeError as exc:
        raise RateVintageIntegrityError(f"Missing required field: {name}") from exc


def _optional_value(record: object, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise RateVintageIntegrityError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RateVintageIntegrityError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _day(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise RateVintageIntegrityError(f"{field} must be a date, not datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise RateVintageIntegrityError(f"{field} must be ISO date") from exc
    raise RateVintageIntegrityError(f"{field} must be a date")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RateVintageIntegrityError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RateVintageIntegrityError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class RateVintageStore:
    """SQLite-backed append-only official-rate vintage store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def __enter__(self) -> RateVintageStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @property
    def schema_version(self) -> str:
        row = self._connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            raise RateVintageIntegrityError("Missing schema version")
        return str(row["value"])

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_snapshots (
                source_snapshot_id INTEGER PRIMARY KEY,
                adapter_id TEXT NOT NULL,
                request_identity TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                source_document_id TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                response_headers_json TEXT NOT NULL,
                UNIQUE(adapter_id, request_identity, payload_sha256)
            );
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                ingestion_run_id TEXT PRIMARY KEY,
                adapter_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_count INTEGER NOT NULL CHECK(snapshot_count >= 0),
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rate_series (
                rate_series_pk INTEGER PRIMARY KEY,
                currency TEXT NOT NULL,
                series_id TEXT NOT NULL,
                source_publisher TEXT NOT NULL,
                day_count_convention TEXT NOT NULL,
                calendar_id TEXT NOT NULL,
                UNIQUE(currency, series_id)
            );
            CREATE TABLE IF NOT EXISTS rate_observation_identities (
                observation_identity_id INTEGER PRIMARY KEY,
                rate_series_pk INTEGER NOT NULL REFERENCES rate_series(rate_series_pk),
                currency TEXT NOT NULL,
                series_id TEXT NOT NULL,
                observation_date TEXT NOT NULL,
                UNIQUE(currency, series_id, observation_date)
            );
            CREATE TABLE IF NOT EXISTS rate_versions (
                version_id TEXT PRIMARY KEY,
                observation_identity_id INTEGER NOT NULL
                    REFERENCES rate_observation_identities(observation_identity_id),
                currency TEXT NOT NULL,
                series_id TEXT NOT NULL,
                observation_date TEXT NOT NULL,
                value_text TEXT NOT NULL,
                publication_timestamp TEXT NOT NULL,
                effective_timestamp TEXT NOT NULL,
                strategy_availability_timestamp TEXT NOT NULL,
                source_publisher TEXT NOT NULL,
                source_document_id TEXT NOT NULL,
                source_endpoint_role TEXT NOT NULL,
                source_snapshot_sha256 TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                revision_identifier TEXT NOT NULL,
                revision_status TEXT NOT NULL,
                day_count_convention TEXT NOT NULL,
                calendar_id TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                UNIQUE(observation_identity_id, publication_timestamp, revision_identifier)
            );
            CREATE TABLE IF NOT EXISTS availability_events (
                availability_event_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL REFERENCES rate_versions(version_id),
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                UNIQUE(version_id, event_type, event_timestamp)
            );
            CREATE TABLE IF NOT EXISTS certification_results (
                certification_result_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL REFERENCES rate_versions(version_id),
                certification_status TEXT NOT NULL,
                certified_at TEXT NOT NULL,
                details_json TEXT NOT NULL,
                UNIQUE(version_id, certification_status, certified_at)
            );
            CREATE TABLE IF NOT EXISTS dataset_freezes (
                dataset_freeze_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                freeze_sha256 TEXT NOT NULL UNIQUE,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dataset_freeze_versions (
                dataset_freeze_id TEXT NOT NULL
                    REFERENCES dataset_freezes(dataset_freeze_id),
                version_id TEXT NOT NULL REFERENCES rate_versions(version_id),
                PRIMARY KEY(dataset_freeze_id, version_id)
            );
            CREATE TABLE IF NOT EXISTS daily_strategy_rate_panel (
                currency TEXT NOT NULL,
                strategy_timestamp TEXT NOT NULL,
                dataset_freeze_id TEXT NOT NULL
                    REFERENCES dataset_freezes(dataset_freeze_id),
                version_id TEXT REFERENCES rate_versions(version_id),
                missing_reason TEXT,
                panel_record_sha256 TEXT NOT NULL,
                PRIMARY KEY(currency, strategy_timestamp, dataset_freeze_id),
                CHECK((version_id IS NULL) <> (missing_reason IS NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_rate_versions_as_of
                ON rate_versions(currency, observation_date, strategy_availability_timestamp);
            CREATE INDEX IF NOT EXISTS idx_freeze_versions_version
                ON dataset_freeze_versions(version_id, dataset_freeze_id);
            """
        )
        self._connection.execute(
            "INSERT OR IGNORE INTO store_metadata(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        existing = self._connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if existing is None or existing["value"] != SCHEMA_VERSION:
            raise RateVintageIntegrityError("Unsupported rate vintage store schema")
        immutable_tables = (
            "source_snapshots",
            "ingestion_runs",
            "rate_series",
            "rate_observation_identities",
            "rate_versions",
            "availability_events",
            "certification_results",
            "dataset_freezes",
            "dataset_freeze_versions",
            "daily_strategy_rate_panel",
        )
        for table in immutable_tables:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"prevent_{operation.lower()}_{table}"
                self._connection.execute(
                    f"""CREATE TRIGGER IF NOT EXISTS {trigger}
                    BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
                )
        self._connection.commit()

    def append_source_snapshot(self, snapshot: object) -> int:
        """Append a snapshot identity, returning its stable row ID on exact replay."""
        request = _optional_value(snapshot, "request")
        adapter_id = _text(
            _optional_value(snapshot, "adapter_id", _optional_value(request, "adapter_id")),
            "adapter_id",
        )
        request_identity = _text(
            _optional_value(
                snapshot,
                "request_identity",
                _optional_value(request, "request_identity"),
            ),
            "request_identity",
        )
        payload_sha256 = _sha256(
            _optional_value(
                snapshot,
                "payload_sha256",
                _optional_value(snapshot, "source_snapshot_sha256"),
            ),
            "payload_sha256",
        )
        source_document_id = _text(
            _optional_value(snapshot, "source_document_id", request_identity),
            "source_document_id",
        )
        retrieved_at = _aware(_value(snapshot, "retrieved_at"), "retrieved_at")
        headers = _optional_value(snapshot, "response_headers", {})
        if isinstance(headers, Mapping):
            normalized_headers = {
                str(key): str(value) for key, value in headers.items()
            }
        elif isinstance(headers, Sequence) and not isinstance(headers, (str, bytes)):
            try:
                normalized_headers = {
                    str(item[0]): str(item[1]) for item in headers
                }
            except (IndexError, TypeError) as exc:
                raise RateVintageIntegrityError(
                    "response_headers must contain key-value pairs"
                ) from exc
        else:
            raise RateVintageIntegrityError("response_headers must contain key-value pairs")
        headers_json = _canonical_json(normalized_headers)
        existing = self._connection.execute(
            """SELECT source_snapshot_id, source_document_id, response_headers_json
            FROM source_snapshots
            WHERE adapter_id = ? AND request_identity = ? AND payload_sha256 = ?""",
            (adapter_id, request_identity, payload_sha256),
        ).fetchone()
        if existing is not None:
            if (
                existing["source_document_id"] != source_document_id
                or existing["response_headers_json"] != headers_json
            ):
                raise RateVintageConflictError("Conflicting source snapshot replay")
            return int(existing["source_snapshot_id"])
        with self._connection:
            cursor = self._connection.execute(
                """INSERT INTO source_snapshots(
                    adapter_id, request_identity, payload_sha256, source_document_id,
                    retrieved_at, response_headers_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    adapter_id,
                    request_identity,
                    payload_sha256,
                    source_document_id,
                    _timestamp(retrieved_at),
                    headers_json,
                ),
            )
        if cursor.lastrowid is None:
            raise RateVintageIntegrityError("SQLite did not return a snapshot row ID")
        return cursor.lastrowid

    def append_ingestion_run(
        self,
        ingestion_run_id: str,
        *,
        adapter_id: str,
        started_at: datetime,
        completed_at: datetime,
        status: str,
        snapshot_count: int,
        details: Mapping[str, object] | None = None,
    ) -> str:
        started = _aware(started_at, "started_at")
        completed = _aware(completed_at, "completed_at")
        if completed < started:
            raise RateVintageIntegrityError("completed_at precedes started_at")
        if snapshot_count < 0:
            raise RateVintageIntegrityError("snapshot_count cannot be negative")
        values = (
            _text(ingestion_run_id, "ingestion_run_id"),
            _text(adapter_id, "adapter_id"),
            _timestamp(started),
            _timestamp(completed),
            _text(status, "status"),
            snapshot_count,
            _canonical_json(details or {}),
        )
        existing = self._connection.execute(
            "SELECT * FROM ingestion_runs WHERE ingestion_run_id = ?", (values[0],)
        ).fetchone()
        if existing is not None:
            if tuple(existing[key] for key in existing.keys()) != values:
                raise RateVintageConflictError("Conflicting ingestion run replay")
            return values[0]
        with self._connection:
            self._connection.execute(
                "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?)", values
            )
        return values[0]

    def append_rate_version(self, version: object) -> str:
        """Append one immutable rate version or return its ID on exact replay."""
        currency = _text(_value(version, "currency"), "currency").upper()
        series_id = _text(_value(version, "series_id"), "series_id")
        observation_date = _day(_value(version, "observation_date"), "observation_date")
        raw_value = _value(version, "value")
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise RateVintageIntegrityError("value must be numeric") from exc
        if not math.isfinite(numeric_value):
            raise RateVintageIntegrityError("value must be finite")
        value_text = repr(numeric_value)
        publication = _aware(
            _value(version, "publication_timestamp"), "publication_timestamp"
        )
        effective = _aware(_value(version, "effective_timestamp"), "effective_timestamp")
        availability = _aware(
            _value(version, "strategy_availability_timestamp"),
            "strategy_availability_timestamp",
        )
        if availability != max(publication, effective):
            raise RateVintageIntegrityError(
                "strategy_availability_timestamp must equal max(publication, effective)"
            )
        retrieved_at = _aware(_value(version, "retrieved_at"), "retrieved_at")
        source_snapshot_sha256 = _sha256(
            _value(version, "source_snapshot_sha256"), "source_snapshot_sha256"
        )
        fields = {
            "currency": currency,
            "series_id": series_id,
            "observation_date": observation_date.isoformat(),
            "value_text": value_text,
            "publication_timestamp": _timestamp(publication),
            "effective_timestamp": _timestamp(effective),
            "strategy_availability_timestamp": _timestamp(availability),
            "source_publisher": _text(
                _value(version, "source_publisher"), "source_publisher"
            ),
            "source_document_id": _text(
                _value(version, "source_document_id"), "source_document_id"
            ),
            "source_endpoint_role": _text(
                _value(version, "source_endpoint_role"), "source_endpoint_role"
            ),
            "source_snapshot_sha256": source_snapshot_sha256,
            "parser_version": _text(_value(version, "parser_version"), "parser_version"),
            "revision_identifier": _text(
                _value(version, "revision_identifier"), "revision_identifier"
            ),
            "revision_status": _text(
                _value(version, "revision_status"), "revision_status"
            ),
            "day_count_convention": _text(
                _value(version, "day_count_convention"), "day_count_convention"
            ),
            "calendar_id": _text(_value(version, "calendar_id"), "calendar_id"),
        }
        snapshot = self._connection.execute(
            "SELECT 1 FROM source_snapshots WHERE payload_sha256 = ? LIMIT 1",
            (source_snapshot_sha256,),
        ).fetchone()
        if snapshot is None:
            raise RateVintageIntegrityError("Rate version references an unknown source snapshot")
        version_id = _content_sha256(fields)
        with self._connection:
            series_pk = self._ensure_series(fields)
            identity_id = self._ensure_observation_identity(
                series_pk, currency, series_id, observation_date
            )
            existing = self._connection.execute(
                """SELECT * FROM rate_versions
                WHERE observation_identity_id = ?
                  AND publication_timestamp = ?
                  AND revision_identifier = ?""",
                (
                    identity_id,
                    fields["publication_timestamp"],
                    fields["revision_identifier"],
                ),
            ).fetchone()
            if existing is not None:
                comparable = {key: existing[key] for key in fields}
                if comparable != fields:
                    raise RateVintageConflictError("Conflicting duplicate rate version")
                return str(existing["version_id"])
            self._connection.execute(
                """INSERT INTO rate_versions(
                    version_id, observation_identity_id, currency, series_id,
                    observation_date, value_text, publication_timestamp,
                    effective_timestamp, strategy_availability_timestamp,
                    source_publisher, source_document_id, source_endpoint_role,
                    source_snapshot_sha256, parser_version, revision_identifier,
                    revision_status, day_count_convention, calendar_id, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    identity_id,
                    *(fields[key] for key in fields),
                    _timestamp(retrieved_at),
                ),
            )
            event_type = (
                "INITIAL_PUBLICATION"
                if fields["revision_status"].upper() in {"INITIAL", "ORIGINAL"}
                else "REVISION"
            )
            event_id = _content_sha256(
                {
                    "version_id": version_id,
                    "event_type": event_type,
                    "event_timestamp": fields["strategy_availability_timestamp"],
                }
            )
            self._connection.execute(
                "INSERT INTO availability_events VALUES (?, ?, ?, ?)",
                (
                    event_id,
                    version_id,
                    event_type,
                    fields["strategy_availability_timestamp"],
                ),
            )
        return version_id

    def _ensure_series(self, fields: Mapping[str, str]) -> int:
        existing = self._connection.execute(
            "SELECT * FROM rate_series WHERE currency = ? AND series_id = ?",
            (fields["currency"], fields["series_id"]),
        ).fetchone()
        expected = (
            fields["source_publisher"],
            fields["day_count_convention"],
            fields["calendar_id"],
        )
        if existing is not None:
            observed = (
                existing["source_publisher"],
                existing["day_count_convention"],
                existing["calendar_id"],
            )
            if observed != expected:
                raise RateVintageConflictError("Conflicting immutable rate-series metadata")
            return int(existing["rate_series_pk"])
        cursor = self._connection.execute(
            """INSERT INTO rate_series(
                currency, series_id, source_publisher, day_count_convention, calendar_id
            ) VALUES (?, ?, ?, ?, ?)""",
            (fields["currency"], fields["series_id"], *expected),
        )
        if cursor.lastrowid is None:
            raise RateVintageIntegrityError("SQLite did not return a rate-series row ID")
        return cursor.lastrowid

    def _ensure_observation_identity(
        self, series_pk: int, currency: str, series_id: str, observation_date: date
    ) -> int:
        observed = observation_date.isoformat()
        existing = self._connection.execute(
            """SELECT observation_identity_id, rate_series_pk
            FROM rate_observation_identities
            WHERE currency = ? AND series_id = ? AND observation_date = ?""",
            (currency, series_id, observed),
        ).fetchone()
        if existing is not None:
            if int(existing["rate_series_pk"]) != series_pk:
                raise RateVintageConflictError("Conflicting observation identity")
            return int(existing["observation_identity_id"])
        cursor = self._connection.execute(
            """INSERT INTO rate_observation_identities(
                rate_series_pk, currency, series_id, observation_date
            ) VALUES (?, ?, ?, ?)""",
            (series_pk, currency, series_id, observed),
        )
        if cursor.lastrowid is None:
            raise RateVintageIntegrityError("SQLite did not return an observation row ID")
        return cursor.lastrowid

    def append_certification(
        self,
        version_id: str,
        *,
        status: str,
        certified_at: datetime,
        details: Mapping[str, object] | None = None,
    ) -> str:
        certified = _aware(certified_at, "certified_at")
        payload = {
            "version_id": _text(version_id, "version_id"),
            "status": _text(status, "status"),
            "certified_at": _timestamp(certified),
            "details": details or {},
        }
        certification_id = _content_sha256(payload)
        values = (
            certification_id,
            payload["version_id"],
            payload["status"],
            payload["certified_at"],
            _canonical_json(payload["details"]),
        )
        existing = self._connection.execute(
            "SELECT * FROM certification_results WHERE certification_result_id = ?",
            (certification_id,),
        ).fetchone()
        if existing is not None:
            return certification_id
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO certification_results VALUES (?, ?, ?, ?, ?)", values
                )
        except sqlite3.IntegrityError as exc:
            raise RateVintageIntegrityError("Certification references an unknown version") from exc
        return certification_id

    def create_dataset_freeze(
        self,
        dataset_freeze_id: str,
        version_ids: Sequence[str],
        *,
        created_at: datetime,
        metadata: Mapping[str, object] | None = None,
    ) -> DatasetFreeze:
        """Freeze an exact, non-empty set of already-persisted version IDs."""
        freeze_id = _text(dataset_freeze_id, "dataset_freeze_id")
        created = _aware(created_at, "created_at")
        pinned = tuple(sorted(set(version_ids)))
        if not pinned:
            raise RateVintageIntegrityError("A dataset freeze must pin at least one version")
        if len(pinned) != len(version_ids):
            raise RateVintageIntegrityError("Dataset freeze contains duplicate version IDs")
        placeholders = ",".join("?" for _ in pinned)
        rows = self._connection.execute(
            f"SELECT version_id FROM rate_versions WHERE version_id IN ({placeholders})", pinned
        ).fetchall()
        if {str(row["version_id"]) for row in rows} != set(pinned):
            raise RateVintageIntegrityError("Dataset freeze references an unknown version")
        metadata_json = _canonical_json(metadata or {})
        freeze_payload = {
            "dataset_freeze_id": freeze_id,
            "created_at": _timestamp(created),
            "version_ids": list(pinned),
            "metadata": json.loads(metadata_json),
        }
        freeze_hash = _content_sha256(freeze_payload)
        existing = self._connection.execute(
            "SELECT * FROM dataset_freezes WHERE dataset_freeze_id = ?", (freeze_id,)
        ).fetchone()
        if existing is not None:
            existing_ids = tuple(
                row["version_id"]
                for row in self._connection.execute(
                    """SELECT version_id FROM dataset_freeze_versions
                    WHERE dataset_freeze_id = ? ORDER BY version_id""",
                    (freeze_id,),
                )
            )
            if (
                existing["created_at"] != freeze_payload["created_at"]
                or existing["metadata_json"] != metadata_json
                or existing["freeze_sha256"] != freeze_hash
                or existing_ids != pinned
            ):
                raise RateVintageConflictError("Conflicting dataset freeze replay")
            return DatasetFreeze(freeze_id, created, freeze_hash, pinned)
        with self._connection:
            self._connection.execute(
                "INSERT INTO dataset_freezes VALUES (?, ?, ?, ?)",
                (freeze_id, freeze_payload["created_at"], freeze_hash, metadata_json),
            )
            self._connection.executemany(
                "INSERT INTO dataset_freeze_versions VALUES (?, ?)",
                ((freeze_id, version_id) for version_id in pinned),
            )
        return DatasetFreeze(freeze_id, created, freeze_hash, pinned)

    def get_rate_as_of(
        self,
        currency: str,
        strategy_timestamp: datetime,
        dataset_freeze_id: str,
    ) -> AvailableRate | MissingRate:
        """Return the newest eligible observation/version pinned by a freeze."""
        normalized_currency = _text(currency, "currency").upper()
        strategy_time = _aware(strategy_timestamp, "strategy_timestamp")
        freeze_id = _text(dataset_freeze_id, "dataset_freeze_id")
        if self._connection.execute(
            "SELECT 1 FROM dataset_freezes WHERE dataset_freeze_id = ?", (freeze_id,)
        ).fetchone() is None:
            raise RateVintageIntegrityError(f"Unknown dataset freeze: {freeze_id}")
        row = self._connection.execute(
            """SELECT rv.*, cr.certification_status
            FROM dataset_freeze_versions AS dfv
            JOIN rate_versions AS rv ON rv.version_id = dfv.version_id
            LEFT JOIN certification_results AS cr
              ON cr.certification_result_id = (
                SELECT inner_cr.certification_result_id
                FROM certification_results AS inner_cr
                WHERE inner_cr.version_id = rv.version_id
                  AND inner_cr.certified_at <= ?
                ORDER BY inner_cr.certified_at DESC, inner_cr.certification_result_id DESC
                LIMIT 1
              )
            WHERE dfv.dataset_freeze_id = ?
              AND rv.currency = ?
              AND rv.strategy_availability_timestamp <= ?
            ORDER BY rv.observation_date DESC,
                     rv.strategy_availability_timestamp DESC,
                     rv.publication_timestamp DESC,
                     rv.version_id DESC
            LIMIT 1""",
            (
                _timestamp(strategy_time),
                freeze_id,
                normalized_currency,
                _timestamp(strategy_time),
            ),
        ).fetchone()
        if row is None:
            return MissingRate(
                currency=normalized_currency,
                strategy_timestamp=strategy_time,
                dataset_freeze_id=freeze_id,
                reason="NO_FROZEN_VERSION_AVAILABLE_AS_OF_STRATEGY_TIMESTAMP",
            )
        observation = date.fromisoformat(str(row["observation_date"]))
        age = (strategy_time.date() - observation).days
        return AvailableRate(
            currency=normalized_currency,
            strategy_timestamp=strategy_time,
            dataset_freeze_id=freeze_id,
            version_id=str(row["version_id"]),
            series_id=str(row["series_id"]),
            observation_date=observation,
            value=float(row["value_text"]),
            publication_timestamp=_parse_timestamp(str(row["publication_timestamp"])),
            effective_timestamp=_parse_timestamp(str(row["effective_timestamp"])),
            strategy_availability_timestamp=_parse_timestamp(
                str(row["strategy_availability_timestamp"])
            ),
            revision_identifier=str(row["revision_identifier"]),
            revision_status=str(row["revision_status"]),
            day_count_convention=str(row["day_count_convention"]),
            calendar_id=str(row["calendar_id"]),
            source_snapshot_sha256=str(row["source_snapshot_sha256"]),
            certification_status=(
                str(row["certification_status"])
                if row["certification_status"] is not None
                else None
            ),
            age_in_calendar_days=age,
            carry_forward_reason=(
                "LAST_OFFICIALLY_AVAILABLE_RATE" if age > 0 else None
            ),
        )

    def append_daily_strategy_rate(
        self, result: AvailableRate | MissingRate
    ) -> str:
        """Persist an idempotent aligned-panel selection without changing the freeze."""
        record = {
            "currency": result.currency,
            "strategy_timestamp": _timestamp(result.strategy_timestamp),
            "dataset_freeze_id": result.dataset_freeze_id,
            "version_id": result.version_id if isinstance(result, AvailableRate) else None,
            "missing_reason": result.reason if isinstance(result, MissingRate) else None,
        }
        record_hash = _content_sha256(record)
        existing = self._connection.execute(
            """SELECT * FROM daily_strategy_rate_panel
            WHERE currency = ? AND strategy_timestamp = ? AND dataset_freeze_id = ?""",
            (record["currency"], record["strategy_timestamp"], record["dataset_freeze_id"]),
        ).fetchone()
        if existing is not None:
            if existing["panel_record_sha256"] != record_hash:
                raise RateVintageConflictError("Conflicting daily strategy-rate replay")
            return record_hash
        with self._connection:
            self._connection.execute(
                "INSERT INTO daily_strategy_rate_panel VALUES (?, ?, ?, ?, ?, ?)",
                (*record.values(), record_hash),
            )
        return record_hash

    def table_counts(self) -> dict[str, int]:
        """Return aggregate counts only; no row-level observations are exposed."""
        tables: Iterable[str] = (
            "source_snapshots",
            "ingestion_runs",
            "rate_series",
            "rate_observation_identities",
            "rate_versions",
            "availability_events",
            "certification_results",
            "daily_strategy_rate_panel",
            "dataset_freezes",
            "dataset_freeze_versions",
        )
        return {
            table: int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
