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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from fx_smc_bot.research.rate_calendars import calendar_for_currency

SCHEMA_VERSION: Final = "F0RPE2E_RATE_VINTAGE_STORE_V2"
V3_SCHEMA_VERSION: Final = "F0RPE2ER_RATE_VINTAGE_STORE_V3"
V3_SCHEMA_ID: Final = V3_SCHEMA_VERSION
SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({SCHEMA_VERSION, V3_SCHEMA_VERSION})
PASSING_CERTIFICATION_STATUSES: Final = frozenset({"PASS", "CERTIFIED"})
_STRATEGY_TIMEZONE: Final = ZoneInfo("America/New_York")
_EONIA_END: Final = date(2019, 9, 30)
_ESTR_START: Final = date(2019, 10, 1)
_V3_AUTHORIZED_START: Final = date(2010, 1, 1)
_V3_AUTHORIZED_END: Final = date(2022, 12, 31)
_V3_AUTHORIZED_CURRENCIES: Final = frozenset(
    {"USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"}
)


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
    certification_status: str
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
    certification_ids: tuple[tuple[str, str], ...] = ()


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


def _validate_series_regime(currency: str, series_id: str, observation_date: date) -> None:
    if currency != "EUR":
        return
    expected = "EONIA" if observation_date <= _EONIA_END else "ESTR"
    if series_id != expected:
        raise RateVintageIntegrityError(
            "EUR series violates the frozen EONIA/ESTR transition"
        )


class RateVintageStore:
    """SQLite-backed append-only official-rate vintage store."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        schema_version: str = SCHEMA_VERSION,
        schema_id: str | None = None,
    ) -> None:
        requested_schema = schema_id or schema_version
        if schema_id is not None and schema_version != SCHEMA_VERSION:
            if schema_id != schema_version:
                raise RateVintageIntegrityError("Conflicting schema selectors")
        if requested_schema not in SUPPORTED_SCHEMA_VERSIONS:
            raise RateVintageIntegrityError(
                f"Unsupported rate vintage store schema: {requested_schema}"
            )
        self.database_path = str(database_path)
        self._schema_version = requested_schema
        self._panel_table = (
            "aligned_daily_rate_panel"
            if requested_schema == V3_SCHEMA_VERSION
            else "daily_strategy_rate_panel"
        )
        if self.database_path != ":memory:":
            database = Path(self.database_path)
            database.parent.mkdir(parents=True, exist_ok=True)
            self._validate_existing_database(database)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA recursive_triggers = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def _validate_existing_database(self, database: Path) -> None:
        """Reject in-place V2-to-V3 upgrades while allowing an existing V3 replay."""
        if self._schema_version != V3_SCHEMA_VERSION or not database.exists():
            return
        if database.stat().st_size == 0:
            return
        connection = sqlite3.connect(database)
        try:
            metadata_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'store_metadata'"
            ).fetchone()
            existing = (
                connection.execute(
                    "SELECT value FROM store_metadata WHERE key = 'schema_version'"
                ).fetchone()
                if metadata_exists
                else None
            )
        except sqlite3.DatabaseError as exc:
            raise RateVintageIntegrityError(
                "V3 requires a new clean database or an existing V3 database"
            ) from exc
        finally:
            connection.close()
        if existing is None or existing[0] != V3_SCHEMA_VERSION:
            raise RateVintageIntegrityError(
                "V3 requires a new clean database; in-place schema upgrades are prohibited"
            )

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
        if self._schema_version == V3_SCHEMA_VERSION:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_requests (
                    request_identity TEXT PRIMARY KEY,
                    adapter_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    series_id TEXT NOT NULL,
                    source_publisher TEXT NOT NULL,
                    source_endpoint_role TEXT NOT NULL,
                    request_method TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    query_parameters_json TEXT NOT NULL,
                    request_headers_json TEXT NOT NULL,
                    response_format TEXT NOT NULL,
                    request_record_sha256 TEXT NOT NULL UNIQUE,
                    UNIQUE(request_identity, adapter_id)
                );
                CREATE TABLE IF NOT EXISTS response_firewall_certifications (
                    firewall_certification_id TEXT PRIMARY KEY,
                    request_identity TEXT NOT NULL,
                    adapter_id TEXT NOT NULL,
                    source_snapshot_sha256 TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    certified_row_count INTEGER NOT NULL CHECK(certified_row_count >= 0),
                    UNIQUE(request_identity, adapter_id, source_snapshot_sha256),
                    FOREIGN KEY(request_identity, adapter_id)
                        REFERENCES source_requests(request_identity, adapter_id)
                );
                """
            )
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
                UNIQUE(adapter_id, request_identity, payload_sha256),
                UNIQUE(source_snapshot_id, adapter_id, request_identity, payload_sha256)
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
                source_snapshot_id INTEGER NOT NULL,
                source_adapter_id TEXT NOT NULL,
                source_request_identity TEXT NOT NULL,
                source_snapshot_sha256 TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                revision_identifier TEXT NOT NULL,
                revision_status TEXT NOT NULL,
                day_count_convention TEXT NOT NULL,
                calendar_id TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                UNIQUE(observation_identity_id, publication_timestamp, revision_identifier),
                FOREIGN KEY(
                    source_snapshot_id, source_adapter_id,
                    source_request_identity, source_snapshot_sha256
                ) REFERENCES source_snapshots(
                    source_snapshot_id, adapter_id, request_identity, payload_sha256
                )
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
                UNIQUE(version_id, certified_at),
                UNIQUE(certification_result_id, version_id)
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
            CREATE TABLE IF NOT EXISTS dataset_freeze_certifications (
                dataset_freeze_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                certification_result_id TEXT NOT NULL
                    REFERENCES certification_results(certification_result_id),
                PRIMARY KEY(dataset_freeze_id, version_id),
                UNIQUE(dataset_freeze_id, certification_result_id),
                FOREIGN KEY(dataset_freeze_id, version_id)
                    REFERENCES dataset_freeze_versions(dataset_freeze_id, version_id),
                FOREIGN KEY(certification_result_id, version_id)
                    REFERENCES certification_results(certification_result_id, version_id)
            );
            CREATE TABLE IF NOT EXISTS daily_strategy_rate_panel (
                currency TEXT NOT NULL,
                strategy_timestamp TEXT NOT NULL,
                dataset_freeze_id TEXT NOT NULL,
                version_id TEXT,
                missing_reason TEXT,
                panel_record_sha256 TEXT NOT NULL,
                PRIMARY KEY(currency, strategy_timestamp, dataset_freeze_id),
                CHECK((version_id IS NULL) <> (missing_reason IS NULL)),
                FOREIGN KEY(dataset_freeze_id)
                    REFERENCES dataset_freezes(dataset_freeze_id),
                FOREIGN KEY(dataset_freeze_id, version_id)
                    REFERENCES dataset_freeze_versions(dataset_freeze_id, version_id)
            );
            CREATE INDEX IF NOT EXISTS idx_rate_versions_as_of
                ON rate_versions(currency, observation_date, strategy_availability_timestamp);
            CREATE INDEX IF NOT EXISTS idx_freeze_versions_version
                ON dataset_freeze_versions(version_id, dataset_freeze_id);
            """
        )
        if self._schema_version == V3_SCHEMA_VERSION:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS aligned_daily_rate_panel (
                    currency TEXT NOT NULL,
                    strategy_timestamp TEXT NOT NULL,
                    dataset_freeze_id TEXT NOT NULL,
                    version_id TEXT,
                    missing_reason TEXT,
                    panel_record_sha256 TEXT NOT NULL,
                    PRIMARY KEY(currency, strategy_timestamp, dataset_freeze_id),
                    CHECK((version_id IS NULL) <> (missing_reason IS NULL)),
                    FOREIGN KEY(dataset_freeze_id)
                        REFERENCES dataset_freezes(dataset_freeze_id),
                    FOREIGN KEY(dataset_freeze_id, version_id)
                        REFERENCES dataset_freeze_versions(dataset_freeze_id, version_id)
                );
                """
            )
        existing = self._connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if existing is None:
            self._connection.execute(
                "INSERT INTO store_metadata(key, value) VALUES('schema_version', ?)",
                (self._schema_version,),
            )
        elif existing["value"] != self._schema_version:
            raise RateVintageIntegrityError("Unsupported rate vintage store schema")
        immutable_tables = [
            "store_metadata",
            "source_snapshots",
            "ingestion_runs",
            "rate_series",
            "rate_observation_identities",
            "rate_versions",
            "availability_events",
            "certification_results",
            "dataset_freezes",
            "dataset_freeze_versions",
            "dataset_freeze_certifications",
            "daily_strategy_rate_panel",
        ]
        if self._schema_version == V3_SCHEMA_VERSION:
            immutable_tables.extend(
                (
                    "source_requests",
                    "response_firewall_certifications",
                    "aligned_daily_rate_panel",
                )
            )
        for table in immutable_tables:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"prevent_{operation.lower()}_{table}"
                self._connection.execute(
                    f"""CREATE TRIGGER IF NOT EXISTS {trigger}
                    BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"""
                )
        self._create_insert_collision_triggers()
        self._connection.commit()

    def _create_insert_collision_triggers(self) -> None:
        collision_checks = {
            "store_metadata": "existing.key = NEW.key",
            "source_snapshots": (
                "existing.source_snapshot_id = NEW.source_snapshot_id OR "
                "(existing.adapter_id = NEW.adapter_id "
                "AND existing.request_identity = NEW.request_identity "
                "AND existing.payload_sha256 = NEW.payload_sha256)"
            ),
            "ingestion_runs": "existing.ingestion_run_id = NEW.ingestion_run_id",
            "rate_series": (
                "existing.rate_series_pk = NEW.rate_series_pk OR "
                "(existing.currency = NEW.currency AND existing.series_id = NEW.series_id)"
            ),
            "rate_observation_identities": (
                "existing.observation_identity_id = NEW.observation_identity_id OR "
                "(existing.currency = NEW.currency AND existing.series_id = NEW.series_id "
                "AND existing.observation_date = NEW.observation_date)"
            ),
            "rate_versions": (
                "existing.version_id = NEW.version_id OR "
                "(existing.observation_identity_id = NEW.observation_identity_id "
                "AND existing.publication_timestamp = NEW.publication_timestamp "
                "AND existing.revision_identifier = NEW.revision_identifier)"
            ),
            "availability_events": (
                "existing.availability_event_id = NEW.availability_event_id OR "
                "(existing.version_id = NEW.version_id AND existing.event_type = NEW.event_type "
                "AND existing.event_timestamp = NEW.event_timestamp)"
            ),
            "certification_results": (
                "existing.certification_result_id = NEW.certification_result_id OR "
                "(existing.version_id = NEW.version_id "
                "AND existing.certified_at = NEW.certified_at)"
            ),
            "dataset_freezes": (
                "existing.dataset_freeze_id = NEW.dataset_freeze_id OR "
                "existing.freeze_sha256 = NEW.freeze_sha256"
            ),
            "dataset_freeze_versions": (
                "existing.dataset_freeze_id = NEW.dataset_freeze_id "
                "AND existing.version_id = NEW.version_id"
            ),
            "dataset_freeze_certifications": (
                "(existing.dataset_freeze_id = NEW.dataset_freeze_id "
                "AND existing.version_id = NEW.version_id) OR "
                "(existing.dataset_freeze_id = NEW.dataset_freeze_id "
                "AND existing.certification_result_id = NEW.certification_result_id)"
            ),
            "daily_strategy_rate_panel": (
                "existing.currency = NEW.currency "
                "AND existing.strategy_timestamp = NEW.strategy_timestamp "
                "AND existing.dataset_freeze_id = NEW.dataset_freeze_id"
            ),
        }
        if self._schema_version == V3_SCHEMA_VERSION:
            collision_checks.update(
                {
                    "source_requests": (
                        "existing.request_identity = NEW.request_identity OR "
                        "existing.request_record_sha256 = NEW.request_record_sha256"
                    ),
                    "response_firewall_certifications": (
                        "existing.firewall_certification_id = "
                        "NEW.firewall_certification_id OR "
                        "(existing.request_identity = NEW.request_identity "
                        "AND existing.adapter_id = NEW.adapter_id "
                        "AND existing.source_snapshot_sha256 = "
                        "NEW.source_snapshot_sha256)"
                    ),
                    "aligned_daily_rate_panel": (
                        "existing.currency = NEW.currency "
                        "AND existing.strategy_timestamp = NEW.strategy_timestamp "
                        "AND existing.dataset_freeze_id = NEW.dataset_freeze_id"
                    ),
                }
            )
        if self._schema_version == V3_SCHEMA_VERSION:
            self._connection.execute(
                """CREATE TRIGGER IF NOT EXISTS validate_snapshot_source_request
                BEFORE INSERT ON source_snapshots
                WHEN NOT EXISTS(
                    SELECT 1 FROM source_requests AS request
                    WHERE request.request_identity = NEW.request_identity
                      AND request.adapter_id = NEW.adapter_id
                )
                BEGIN SELECT RAISE(ABORT, 'snapshot requires exact source request'); END"""
            )
            self._connection.execute(
                """CREATE TRIGGER IF NOT EXISTS validate_snapshot_firewall_certification
                BEFORE INSERT ON source_snapshots
                WHEN NOT EXISTS(
                    SELECT 1 FROM response_firewall_certifications AS certification
                    WHERE certification.request_identity = NEW.request_identity
                      AND certification.adapter_id = NEW.adapter_id
                      AND certification.source_snapshot_sha256 = NEW.payload_sha256
                )
                BEGIN SELECT RAISE(ABORT, 'snapshot requires firewall certification'); END"""
            )
        for table, condition in collision_checks.items():
            self._connection.execute(
                f"""CREATE TRIGGER IF NOT EXISTS prevent_replace_{table}
                BEFORE INSERT ON {table}
                WHEN EXISTS(SELECT 1 FROM {table} AS existing WHERE {condition})
                BEGIN SELECT RAISE(ABORT, 'append-only insert collision: {table}'); END"""
            )
        self._connection.execute(
            """CREATE TRIGGER IF NOT EXISTS validate_frozen_certification
            BEFORE INSERT ON dataset_freeze_certifications
            WHEN NOT EXISTS(
                SELECT 1 FROM certification_results AS certification
                WHERE certification.certification_result_id = NEW.certification_result_id
                  AND certification.version_id = NEW.version_id
                  AND certification.certification_status IN ('PASS', 'CERTIFIED')
            )
            BEGIN SELECT RAISE(ABORT, 'dataset freeze requires passing certification'); END"""
        )

    def append_source_request(self, request: object) -> str:
        """Append one exact V3 request identity or return it on exact replay."""
        if self._schema_version != V3_SCHEMA_VERSION:
            raise RateVintageIntegrityError("source_requests are available only in V3 mode")
        request_identity = _text(_value(request, "request_identity"), "request_identity")
        currency = _text(_value(request, "currency"), "currency").upper()
        if currency == "NZD":
            raise RateVintageIntegrityError("NZD source requests are prohibited")
        start = _day(_value(request, "start"), "start")
        end = _day(_value(request, "end"), "end")
        if start > end:
            raise RateVintageIntegrityError("Source request interval is invalid")
        query_parameters = self._normalized_pairs(
            _optional_value(request, "query_parameters", ()), "query_parameters"
        )
        request_headers = self._normalized_pairs(
            _optional_value(request, "request_headers", ()), "request_headers"
        )
        accept_values = [
            value for name, value in request_headers if name.lower() == "accept"
        ]
        response_format = _text(
            _optional_value(
                request,
                "response_format",
                accept_values[0] if len(accept_values) == 1 else None,
            ),
            "response_format",
        )
        record = {
            "request_identity": request_identity,
            "adapter_id": _text(_value(request, "adapter_id"), "adapter_id"),
            "currency": currency,
            "series_id": _text(_value(request, "series_id"), "series_id"),
            "source_publisher": _text(
                _value(request, "source_publisher"), "source_publisher"
            ),
            "source_endpoint_role": _text(
                _value(request, "source_endpoint_role"), "source_endpoint_role"
            ),
            "request_method": _text(
                _optional_value(request, "method", "GET"), "method"
            ).upper(),
            "endpoint_url": _text(_value(request, "url"), "url"),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "query_parameters_json": _canonical_json(query_parameters),
            "request_headers_json": _canonical_json(request_headers),
            "response_format": response_format,
        }
        expected_identity = _content_sha256(
            {
                "adapter_id": record["adapter_id"],
                "currency": record["currency"],
                "end": record["end_date"],
                "endpoint_role": record["source_endpoint_role"],
                "method": record["request_method"],
                "query_parameters": query_parameters,
                "series_id": record["series_id"],
                "start": record["start_date"],
                "url": record["endpoint_url"],
            }
        )
        if request_identity != expected_identity:
            raise RateVintageIntegrityError(
                "Source request identity does not match its canonical request"
            )
        record_sha256 = _content_sha256(record)
        values = (*record.values(), record_sha256)
        existing = self._connection.execute(
            "SELECT * FROM source_requests WHERE request_identity = ?",
            (request_identity,),
        ).fetchone()
        if existing is not None:
            comparable = tuple(existing[key] for key in record) + (
                existing["request_record_sha256"],
            )
            if comparable != values:
                raise RateVintageConflictError("Conflicting source request replay")
            return request_identity
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO source_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise RateVintageConflictError("Conflicting source request replay") from exc
        return request_identity

    @staticmethod
    def _normalized_pairs(value: object, field: str) -> tuple[tuple[str, str], ...]:
        if isinstance(value, Mapping):
            pairs = tuple(sorted((str(key), str(item)) for key, item in value.items()))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            try:
                pairs = tuple((str(item[0]), str(item[1])) for item in value)
            except (IndexError, TypeError) as exc:
                raise RateVintageIntegrityError(
                    f"{field} must contain key-value pairs"
                ) from exc
        else:
            raise RateVintageIntegrityError(f"{field} must contain key-value pairs")
        if len({name for name, _ in pairs}) != len(pairs):
            raise RateVintageIntegrityError(f"{field} contains duplicate names")
        return pairs

    def append_source_snapshot(
        self,
        snapshot: object,
        *,
        firewall_certification: object | None = None,
    ) -> int:
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
        if self._schema_version == V3_SCHEMA_VERSION:
            payload = _optional_value(snapshot, "payload")
            if not isinstance(payload, bytes):
                raise RateVintageIntegrityError("V3 source snapshots require payload bytes")
            if hashlib.sha256(payload).hexdigest() != payload_sha256:
                raise RateVintageIntegrityError("Source snapshot payload SHA-256 mismatch")
            if request is None:
                raise RateVintageIntegrityError(
                    "V3 source snapshots require the exact source request"
                )
            certification = self._validate_firewall_certification(
                request,
                payload,
                payload_sha256,
                firewall_certification,
            )
            registered_identity = self.append_source_request(request)
            if registered_identity != request_identity:
                raise RateVintageIntegrityError("Snapshot request identity mismatch")
            self._append_firewall_certification(certification)
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
            """SELECT source_snapshot_id, source_document_id, retrieved_at,
                      response_headers_json
            FROM source_snapshots
            WHERE adapter_id = ? AND request_identity = ? AND payload_sha256 = ?""",
            (adapter_id, request_identity, payload_sha256),
        ).fetchone()
        if existing is not None:
            if (
                existing["source_document_id"] != source_document_id
                or existing["response_headers_json"] != headers_json
                or (
                    self._schema_version == V3_SCHEMA_VERSION
                    and existing["retrieved_at"] != _timestamp(retrieved_at)
                )
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

    def _validate_firewall_certification(
        self,
        request: object,
        payload: bytes,
        payload_sha256: str,
        certification: object | None,
    ) -> tuple[str, str, str, str, str, int]:
        if certification is None:
            raise RateVintageIntegrityError(
                "V3 source snapshot persistence requires firewall certification"
            )
        request_identity = _text(
            _value(certification, "request_identity"), "firewall request_identity"
        )
        if request_identity != _text(_value(request, "request_identity"), "request_identity"):
            raise RateVintageIntegrityError("Firewall certification request mismatch")
        schema_id = _text(_value(certification, "schema_id"), "firewall schema_id")
        rows = _value(certification, "rows")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise RateVintageIntegrityError("Firewall certification rows are invalid")
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RateVintageIntegrityError(
                "Firewall-certified snapshot must contain valid JSON"
            ) from exc
        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema", "observations"}
            or document["schema"] != schema_id
            or not isinstance(document["observations"], list)
            or _canonical_json(document["observations"]) != _canonical_json(list(rows))
        ):
            raise RateVintageIntegrityError(
                "Firewall certification does not match the complete snapshot payload"
            )
        adapter_id = _text(_value(request, "adapter_id"), "adapter_id")
        request_currency = _text(_value(request, "currency"), "currency").upper()
        request_series = _text(_value(request, "series_id"), "series_id")
        request_start = _day(_value(request, "start"), "start")
        request_end = _day(_value(request, "end"), "end")
        seen: set[tuple[str, str, date]] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise RateVintageIntegrityError("Firewall certification row is invalid")
            currency = _text(row.get("currency"), "certified row currency").upper()
            series_id = _text(row.get("seriesId"), "certified row seriesId")
            observation = _day(
                row.get("observationDate"), "certified row observationDate"
            )
            if (
                currency not in _V3_AUTHORIZED_CURRENCIES
                or currency != request_currency
                or series_id != request_series
                or observation < _V3_AUTHORIZED_START
                or observation > _V3_AUTHORIZED_END
                or observation < request_start
                or observation > request_end
            ):
                raise RateVintageIntegrityError(
                    "Firewall certification contains a prohibited or out-of-scope row"
                )
            identity = (currency, series_id, observation)
            if identity in seen:
                raise RateVintageIntegrityError(
                    "Firewall certification contains duplicate observation identities"
                )
            seen.add(identity)
        certification_id = _content_sha256(
            {
                "request_identity": request_identity,
                "adapter_id": adapter_id,
                "source_snapshot_sha256": payload_sha256,
                "schema_id": schema_id,
                "rows": list(rows),
            }
        )
        return (
            certification_id,
            request_identity,
            adapter_id,
            payload_sha256,
            schema_id,
            len(rows),
        )

    def _append_firewall_certification(
        self, values: tuple[str, str, str, str, str, int]
    ) -> None:
        existing = self._connection.execute(
            """SELECT * FROM response_firewall_certifications
            WHERE request_identity = ? AND adapter_id = ?
              AND source_snapshot_sha256 = ?""",
            (values[1], values[2], values[3]),
        ).fetchone()
        if existing is not None:
            if tuple(existing[key] for key in existing.keys()) != values:
                raise RateVintageConflictError(
                    "Conflicting response firewall certification replay"
                )
            return
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO response_firewall_certifications VALUES (?, ?, ?, ?, ?, ?)",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise RateVintageConflictError(
                "Conflicting response firewall certification replay"
            ) from exc

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
        if self._schema_version == V3_SCHEMA_VERSION and (
            currency not in _V3_AUTHORIZED_CURRENCIES
            or observation_date < _V3_AUTHORIZED_START
            or observation_date > _V3_AUTHORIZED_END
        ):
            raise RateVintageIntegrityError(
                "V3 rate version is outside the authorized historical scope"
            )
        _validate_series_regime(currency, series_id, observation_date)
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
        expected_calendar = calendar_for_currency(currency)
        availability_day = availability.astimezone(ZoneInfo(expected_calendar.timezone)).date()
        if observation_date > availability_day:
            raise RateVintageIntegrityError(
                "observation_date cannot follow strategy availability in the source timezone"
            )
        retrieved_at = _aware(_value(version, "retrieved_at"), "retrieved_at")
        source_snapshot_sha256 = _sha256(
            _value(version, "source_snapshot_sha256"), "source_snapshot_sha256"
        )
        if self._schema_version == V3_SCHEMA_VERSION and (
            _optional_value(version, "source_adapter_id") is None
            or _optional_value(version, "source_request_identity") is None
        ):
            raise RateVintageIntegrityError(
                "V3 rate versions require exact source adapter and request identity"
            )
        snapshot = self._resolve_source_snapshot(version, source_snapshot_sha256)
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
            "source_adapter_id": str(snapshot["adapter_id"]),
            "source_request_identity": str(snapshot["request_identity"]),
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
        if self._schema_version == V3_SCHEMA_VERSION:
            self._validate_v3_version_request(fields, snapshot, retrieved_at)
        if fields["calendar_id"] != expected_calendar.calendar_id:
            raise RateVintageIntegrityError("Rate version uses the wrong currency calendar")
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
                if (
                    comparable != fields
                    or int(existing["source_snapshot_id"]) != int(snapshot["source_snapshot_id"])
                ):
                    raise RateVintageConflictError("Conflicting duplicate rate version")
                return str(existing["version_id"])
            self._connection.execute(
                """INSERT INTO rate_versions(
                    version_id, observation_identity_id, currency, series_id,
                    observation_date, value_text, publication_timestamp,
                    effective_timestamp, strategy_availability_timestamp,
                    source_publisher, source_document_id, source_endpoint_role,
                    source_snapshot_id, source_adapter_id, source_request_identity,
                    source_snapshot_sha256, parser_version, revision_identifier,
                    revision_status, day_count_convention, calendar_id, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    identity_id,
                    *(fields[key] for key in (
                        "currency",
                        "series_id",
                        "observation_date",
                        "value_text",
                        "publication_timestamp",
                        "effective_timestamp",
                        "strategy_availability_timestamp",
                        "source_publisher",
                        "source_document_id",
                        "source_endpoint_role",
                    )),
                    int(snapshot["source_snapshot_id"]),
                    *(fields[key] for key in (
                        "source_adapter_id",
                        "source_request_identity",
                        "source_snapshot_sha256",
                        "parser_version",
                        "revision_identifier",
                        "revision_status",
                        "day_count_convention",
                        "calendar_id",
                    )),
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

    def _validate_v3_version_request(
        self,
        fields: Mapping[str, str],
        snapshot: sqlite3.Row,
        retrieved_at: datetime,
    ) -> None:
        request = self._connection.execute(
            """SELECT * FROM source_requests
            WHERE request_identity = ? AND adapter_id = ?""",
            (snapshot["request_identity"], snapshot["adapter_id"]),
        ).fetchone()
        if request is None:
            raise RateVintageIntegrityError("Rate version references an unknown source request")
        expected = {
            "currency": request["currency"],
            "series_id": request["series_id"],
            "source_publisher": request["source_publisher"],
            "source_endpoint_role": request["source_endpoint_role"],
        }
        if any(fields[field] != value for field, value in expected.items()):
            raise RateVintageIntegrityError(
                "Rate version does not match its exact source request"
            )
        if _timestamp(retrieved_at) != snapshot["retrieved_at"]:
            raise RateVintageIntegrityError(
                "Rate version retrieval timestamp does not match its source snapshot"
            )

    def _resolve_source_snapshot(
        self, version: object, payload_sha256: str
    ) -> sqlite3.Row:
        adapter_id = _optional_value(version, "source_adapter_id")
        request_identity = _optional_value(version, "source_request_identity")
        if adapter_id is not None or request_identity is not None:
            if adapter_id is None or request_identity is None:
                raise RateVintageIntegrityError(
                    "source_adapter_id and source_request_identity must be supplied together"
                )
            rows = self._connection.execute(
                """SELECT * FROM source_snapshots
                WHERE adapter_id = ? AND request_identity = ? AND payload_sha256 = ?""",
                (
                    _text(adapter_id, "source_adapter_id"),
                    _text(request_identity, "source_request_identity"),
                    payload_sha256,
                ),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM source_snapshots WHERE payload_sha256 = ?",
                (payload_sha256,),
            ).fetchall()
        if not rows:
            raise RateVintageIntegrityError("Rate version references an unknown source snapshot")
        if len(rows) != 1:
            raise RateVintageIntegrityError(
                "Rate version snapshot identity is ambiguous; exact adapter/request required"
            )
        return rows[0]

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
        normalized_version_id = _text(version_id, "version_id")
        version_row = self._connection.execute(
            "SELECT retrieved_at FROM rate_versions WHERE version_id = ?",
            (normalized_version_id,),
        ).fetchone()
        if version_row is None:
            raise RateVintageIntegrityError("Certification references an unknown version")
        if certified < _parse_timestamp(str(version_row["retrieved_at"])):
            raise RateVintageIntegrityError("Certification cannot predate source retrieval")
        payload = {
            "version_id": normalized_version_id,
            "status": _text(status, "status").upper(),
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
            """SELECT * FROM certification_results
            WHERE version_id = ? AND certified_at = ?""",
            (payload["version_id"], payload["certified_at"]),
        ).fetchone()
        if existing is not None:
            comparable = (
                existing["certification_result_id"],
                existing["certification_status"],
                existing["details_json"],
            )
            expected = (certification_id, payload["status"], values[-1])
            if comparable != expected:
                raise RateVintageConflictError("Conflicting certification replay")
            return str(existing["certification_result_id"])
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO certification_results VALUES (?, ?, ?, ?, ?)", values
                )
        except sqlite3.IntegrityError as exc:
            raise RateVintageConflictError("Conflicting certification replay") from exc
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
        existing = self._connection.execute(
            "SELECT * FROM dataset_freezes WHERE dataset_freeze_id = ?", (freeze_id,)
        ).fetchone()
        if existing is not None:
            certification_pins = tuple(
                (row["version_id"], row["certification_result_id"])
                for row in self._connection.execute(
                    """SELECT version_id, certification_result_id
                    FROM dataset_freeze_certifications
                    WHERE dataset_freeze_id = ? ORDER BY version_id""",
                    (freeze_id,),
                )
            )
        else:
            pinned_certifications: list[tuple[str, str]] = []
            for version_id in pinned:
                certification = self._connection.execute(
                    """SELECT * FROM certification_results
                    WHERE version_id = ? AND certified_at <= ?
                    ORDER BY certified_at DESC, certification_result_id DESC
                    LIMIT 1""",
                    (version_id, _timestamp(created)),
                ).fetchone()
                if certification is None:
                    raise RateVintageIntegrityError(
                        "Dataset freeze requires a certification for every version"
                    )
                if (
                    str(certification["certification_status"]).upper()
                    not in PASSING_CERTIFICATION_STATUSES
                ):
                    raise RateVintageIntegrityError(
                        "Dataset freeze requires the latest certification to pass"
                    )
                pinned_certifications.append(
                    (version_id, str(certification["certification_result_id"]))
                )
            certification_pins = tuple(sorted(pinned_certifications))
        freeze_payload = {
            "dataset_freeze_id": freeze_id,
            "created_at": _timestamp(created),
            "version_ids": list(pinned),
            "certification_ids": [list(item) for item in certification_pins],
            "metadata": json.loads(metadata_json),
        }
        freeze_hash = _content_sha256(freeze_payload)
        if existing is not None:
            existing_ids = tuple(
                row["version_id"]
                for row in self._connection.execute(
                    """SELECT version_id FROM dataset_freeze_versions
                    WHERE dataset_freeze_id = ? ORDER BY version_id""",
                    (freeze_id,),
                )
            )
            existing_certifications = tuple(
                (row["version_id"], row["certification_result_id"])
                for row in self._connection.execute(
                    """SELECT version_id, certification_result_id
                    FROM dataset_freeze_certifications
                    WHERE dataset_freeze_id = ? ORDER BY version_id""",
                    (freeze_id,),
                )
            )
            if (
                existing["created_at"] != freeze_payload["created_at"]
                or existing["metadata_json"] != metadata_json
                or existing["freeze_sha256"] != freeze_hash
                or existing_ids != pinned
                or existing_certifications != certification_pins
            ):
                raise RateVintageConflictError("Conflicting dataset freeze replay")
            return DatasetFreeze(
                freeze_id, created, freeze_hash, pinned, certification_pins
            )
        with self._connection:
            self._connection.execute(
                "INSERT INTO dataset_freezes VALUES (?, ?, ?, ?)",
                (freeze_id, freeze_payload["created_at"], freeze_hash, metadata_json),
            )
            self._connection.executemany(
                "INSERT INTO dataset_freeze_versions VALUES (?, ?)",
                ((freeze_id, version_id) for version_id in pinned),
            )
            self._connection.executemany(
                "INSERT INTO dataset_freeze_certifications VALUES (?, ?, ?)",
                (
                    (freeze_id, version_id, certification_id)
                    for version_id, certification_id in certification_pins
                ),
            )
        return DatasetFreeze(freeze_id, created, freeze_hash, pinned, certification_pins)

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
            JOIN dataset_freeze_certifications AS dfc
              ON dfc.dataset_freeze_id = dfv.dataset_freeze_id
             AND dfc.version_id = rv.version_id
            JOIN certification_results AS cr
              ON cr.certification_result_id = dfc.certification_result_id
            WHERE dfv.dataset_freeze_id = ?
              AND rv.currency = ?
              AND rv.strategy_availability_timestamp <= ?
              AND rv.observation_date <= ?
              AND cr.certification_status IN ('PASS', 'CERTIFIED')
            ORDER BY rv.observation_date DESC,
                     rv.strategy_availability_timestamp DESC,
                     rv.publication_timestamp DESC,
                     rv.version_id DESC
            LIMIT 1""",
            (
                freeze_id,
                normalized_currency,
                _timestamp(strategy_time),
                strategy_time.astimezone(_STRATEGY_TIMEZONE).date().isoformat(),
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
        strategy_day = strategy_time.astimezone(_STRATEGY_TIMEZONE).date()
        age = (strategy_day - observation).days
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
            certification_status=str(row["certification_status"]),
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
            f"""SELECT * FROM {self._panel_table}
            WHERE currency = ? AND strategy_timestamp = ? AND dataset_freeze_id = ?""",
            (record["currency"], record["strategy_timestamp"], record["dataset_freeze_id"]),
        ).fetchone()
        if existing is not None:
            if existing["panel_record_sha256"] != record_hash:
                raise RateVintageConflictError("Conflicting daily strategy-rate replay")
            return record_hash
        if isinstance(result, AvailableRate):
            membership = self._connection.execute(
                """SELECT 1 FROM dataset_freeze_versions
                WHERE dataset_freeze_id = ? AND version_id = ?""",
                (result.dataset_freeze_id, result.version_id),
            ).fetchone()
            if membership is None:
                raise RateVintageIntegrityError(
                    "Daily strategy rate version is outside its dataset freeze"
                )
        with self._connection:
            self._connection.execute(
                f"INSERT INTO {self._panel_table} VALUES (?, ?, ?, ?, ?, ?)",
                (*record.values(), record_hash),
            )
        return record_hash

    def append_aligned_daily_rate(self, result: AvailableRate | MissingRate) -> str:
        """Persist a V3 aligned-panel record using the backward-compatible API."""
        if self._schema_version != V3_SCHEMA_VERSION:
            raise RateVintageIntegrityError(
                "aligned_daily_rate_panel is available only in V3 mode"
            )
        return self.append_daily_strategy_rate(result)

    def table_counts(self) -> dict[str, int]:
        """Return aggregate counts only; no row-level observations are exposed."""
        tables: list[str] = [
            "source_snapshots",
            "ingestion_runs",
            "rate_series",
            "rate_observation_identities",
            "rate_versions",
            "availability_events",
            "certification_results",
            "dataset_freezes",
            "dataset_freeze_versions",
            "dataset_freeze_certifications",
        ]
        if self._schema_version == V3_SCHEMA_VERSION:
            tables[0:0] = ["source_requests", "response_firewall_certifications"]
            tables.append("aligned_daily_rate_panel")
        else:
            tables.append("daily_strategy_rate_panel")
        return {
            table: int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
