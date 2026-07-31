"""Strict, side-effect-free contracts for official financing-rate sources.

Adapters in this package only construct authorized requests and parse immutable
snapshots supplied by an external acquisition layer. They never perform HTTP.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, TypeAlias
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

MAX_REQUEST_DAYS = 370
PROHIBITED_CURRENCY = "NZD"
PROHIBITED_YEARS = frozenset({2023, 2024, 2025})
ALLOWED_REVISION_STATUSES = frozenset({"ORIGINAL", "REVISED", "CORRECTED", "FINAL"})
HeaderPairs: TypeAlias = tuple[tuple[str, str], ...]


class RateSourceError(ValueError):
    """Raised when authorization, source integrity, or parsing fails closed."""


@dataclass(frozen=True, slots=True)
class RateAccessAuthorization:
    authorization_id: str
    adapter_ids: frozenset[str]
    currencies: frozenset[str]
    series_ids: frozenset[str]
    start: date
    end: date
    official_hosts: frozenset[str]

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise RateSourceError("AUTHORIZATION_ID_REQUIRED")
        if self.start > self.end:
            raise RateSourceError("AUTHORIZATION_INTERVAL_INVALID")
        if PROHIBITED_CURRENCY in self.currencies:
            raise RateSourceError("NZD_AUTHORIZATION_PROHIBITED")
        _reject_prohibited_interval(self.start, self.end)

    def authorize(self, request: OfficialRateRequest) -> None:
        if request.adapter_id not in self.adapter_ids:
            raise RateSourceError("ADAPTER_NOT_AUTHORIZED")
        if request.currency not in self.currencies:
            raise RateSourceError("CURRENCY_NOT_AUTHORIZED")
        if request.series_id not in self.series_ids:
            raise RateSourceError("SERIES_NOT_AUTHORIZED")
        if request.start < self.start or request.end > self.end:
            raise RateSourceError("REQUEST_OUTSIDE_AUTHORIZED_INTERVAL")
        host = (urlparse(request.url).hostname or "").lower()
        if host not in self.official_hosts:
            raise RateSourceError("NON_OFFICIAL_HOST")


@dataclass(frozen=True, slots=True)
class OfficialRateRequest:
    adapter_id: str
    currency: str
    series_id: str
    source_publisher: str
    source_endpoint_role: str
    start: date
    end: date
    url: str
    query_parameters: HeaderPairs = ()
    request_headers: HeaderPairs = (("Accept", "application/json"),)
    method: str = "GET"

    def __post_init__(self) -> None:
        if self.currency == PROHIBITED_CURRENCY:
            raise RateSourceError("NZD_REQUEST_PROHIBITED")
        if self.start > self.end:
            raise RateSourceError("REQUEST_INTERVAL_INVALID")
        _reject_prohibited_interval(self.start, self.end)
        if (self.end - self.start).days > MAX_REQUEST_DAYS:
            raise RateSourceError("REQUEST_INTERVAL_NOT_BOUNDED")
        if self.method != "GET":
            raise RateSourceError("ONLY_IDEMPOTENT_GET_ALLOWED")
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query:
            raise RateSourceError("HTTPS_ENDPOINT_WITHOUT_INLINE_QUERY_REQUIRED")
        if tuple(sorted(self.query_parameters)) != self.query_parameters:
            raise RateSourceError("QUERY_PARAMETERS_MUST_BE_SORTED")
        if len({name for name, _ in self.query_parameters}) != len(self.query_parameters):
            raise RateSourceError("DUPLICATE_QUERY_PARAMETER")

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
        return _canonical_sha256(record)


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    request: OfficialRateRequest
    payload: bytes
    content_type: str
    response_headers: HeaderPairs
    retrieved_at: datetime
    source_snapshot_sha256: str

    def __post_init__(self) -> None:
        _require_aware(self.retrieved_at, "RETRIEVED_AT")
        digest = hashlib.sha256(self.payload).hexdigest()
        if self.source_snapshot_sha256 != digest:
            raise RateSourceError("SOURCE_SNAPSHOT_SHA256_MISMATCH")
        if tuple(sorted((key.lower(), value) for key, value in self.response_headers)) != tuple(
            (key.lower(), value) for key, value in self.response_headers
        ):
            raise RateSourceError("RESPONSE_HEADERS_MUST_BE_NORMALIZED_AND_SORTED")


@dataclass(frozen=True, slots=True)
class RateObservationIdentity:
    currency: str
    series_id: str
    observation_date: date


@dataclass(frozen=True, slots=True)
class RateVersion:
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
    source_metadata: HeaderPairs = field(default=())

    def __post_init__(self) -> None:
        if self.currency == PROHIBITED_CURRENCY:
            raise RateSourceError("NZD_VERSION_PROHIBITED")
        if not math.isfinite(self.value):
            raise RateSourceError("NON_FINITE_RATE_VALUE")
        for timestamp, name in (
            (self.publication_timestamp, "PUBLICATION_TIMESTAMP"),
            (self.effective_timestamp, "EFFECTIVE_TIMESTAMP"),
            (self.strategy_availability_timestamp, "STRATEGY_AVAILABILITY_TIMESTAMP"),
            (self.retrieved_at, "RETRIEVED_AT"),
        ):
            _require_aware(timestamp, name)
        expected = max(self.publication_timestamp, self.effective_timestamp)
        if self.strategy_availability_timestamp != expected:
            raise RateSourceError("STRATEGY_AVAILABILITY_MUST_EQUAL_MAX_PUBLICATION_EFFECTIVE")
        if self.revision_status not in ALLOWED_REVISION_STATUSES:
            raise RateSourceError("UNSUPPORTED_REVISION_STATUS")
        if not self.source_document_id.strip() or not self.revision_identifier.strip():
            raise RateSourceError("SOURCE_DOCUMENT_AND_REVISION_REQUIRED")
        _validate_sha256(self.source_snapshot_sha256)

    @property
    def identity(self) -> RateObservationIdentity:
        return RateObservationIdentity(self.currency, self.series_id, self.observation_date)


@dataclass(frozen=True, slots=True)
class RateAvailabilityEvent:
    identity: RateObservationIdentity
    revision_identifier: str
    publication_timestamp: datetime
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime

    def __post_init__(self) -> None:
        expected = max(
            _require_aware(self.publication_timestamp, "PUBLICATION_TIMESTAMP"),
            _require_aware(self.effective_timestamp, "EFFECTIVE_TIMESTAMP"),
        )
        if _require_aware(
            self.strategy_availability_timestamp, "STRATEGY_AVAILABILITY_TIMESTAMP"
        ) != expected:
            raise RateSourceError("AVAILABILITY_EVENT_TIMESTAMP_MISMATCH")


@dataclass(frozen=True, slots=True)
class RateCertification:
    adapter_id: str
    identity: RateObservationIdentity
    revision_identifier: str
    passed: bool
    status: str
    checks: tuple[str, ...]
    reasons: tuple[str, ...] = ()


class OfficialRateAdapter(Protocol):
    adapter_id: str
    currency: str
    series_id: str
    parser_version: str

    def build_requests(
        self,
        start: date,
        end: date,
        authorization: RateAccessAuthorization,
    ) -> Sequence[OfficialRateRequest]: ...

    def parse_snapshot(self, snapshot: SourceSnapshot) -> Sequence[RateVersion]: ...

    def certify_version(self, version: RateVersion) -> RateCertification: ...


def make_request(
    *,
    adapter_id: str,
    currency: str,
    series_id: str,
    publisher: str,
    endpoint_role: str,
    start: date,
    end: date,
    url: str,
    query_parameters: Mapping[str, str],
    authorization: RateAccessAuthorization,
    accept: str = "application/json",
) -> OfficialRateRequest:
    request = OfficialRateRequest(
        adapter_id=adapter_id,
        currency=currency,
        series_id=series_id,
        source_publisher=publisher,
        source_endpoint_role=endpoint_role,
        start=start,
        end=end,
        url=url,
        query_parameters=tuple(sorted(query_parameters.items())),
        request_headers=(("Accept", accept),),
    )
    authorization.authorize(request)
    return request


def strict_json_rows(
    snapshot: SourceSnapshot,
    *,
    schema_id: str,
    required_row_fields: frozenset[str],
) -> tuple[Mapping[str, object], ...]:
    _validate_machine_readable(snapshot, ("application/json",))
    try:
        document = json.loads(snapshot.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RateSourceError("INVALID_JSON_PAYLOAD") from exc
    if not isinstance(document, dict) or set(document) != {"schema", "observations"}:
        raise RateSourceError("SOURCE_SCHEMA_CHANGED")
    if document["schema"] != schema_id or not isinstance(document["observations"], list):
        raise RateSourceError("SOURCE_SCHEMA_CHANGED")
    rows: list[Mapping[str, object]] = []
    for row in document["observations"]:
        if not isinstance(row, dict) or set(row) != required_row_fields:
            raise RateSourceError("SOURCE_ROW_SCHEMA_CHANGED")
        rows.append(row)
    return tuple(rows)


def strict_csv_rows(
    snapshot: SourceSnapshot,
    *,
    required_fields: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    _validate_machine_readable(snapshot, ("text/csv", "application/csv"))
    try:
        text = snapshot.payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RateSourceError("INVALID_CSV_ENCODING") from exc
    reader = csv.DictReader(io.StringIO(text), strict=True)
    if tuple(reader.fieldnames or ()) != required_fields:
        raise RateSourceError("SOURCE_SCHEMA_CHANGED")
    try:
        return tuple(dict(row) for row in reader)
    except csv.Error as exc:
        raise RateSourceError("INVALID_CSV_PAYLOAD") from exc


def version_from_row(
    snapshot: SourceSnapshot,
    row: Mapping[str, object],
    *,
    currency: str,
    expected_series_id: str,
    publisher: str,
    parser_version: str,
    day_count_convention: str,
    calendar_id: str,
    metadata_fields: tuple[str, ...] = (),
) -> RateVersion:
    series_id = required_text(row, "seriesId")
    if series_id != expected_series_id:
        raise RateSourceError("UNEXPECTED_SERIES_ID")
    row_currency = required_text(row, "currency")
    if row_currency != currency:
        raise RateSourceError("UNEXPECTED_CURRENCY")
    observation = parse_date(row.get("observationDate"))
    if observation < snapshot.request.start or observation > snapshot.request.end:
        raise RateSourceError("OBSERVATION_OUTSIDE_AUTHORIZED_INTERVAL")
    publication = parse_timestamp(row.get("publicationTimestamp"), "PUBLICATION_TIMESTAMP")
    effective = parse_timestamp(row.get("effectiveTimestamp"), "EFFECTIVE_TIMESTAMP")
    metadata = tuple((name, required_text(row, name)) for name in metadata_fields)
    return RateVersion(
        currency=currency,
        series_id=series_id,
        observation_date=observation,
        value=parse_finite_rate(row.get("value")),
        publication_timestamp=publication,
        effective_timestamp=effective,
        strategy_availability_timestamp=max(publication, effective),
        source_publisher=publisher,
        source_document_id=required_text(row, "sourceDocumentId"),
        source_endpoint_role=snapshot.request.source_endpoint_role,
        source_snapshot_sha256=snapshot.source_snapshot_sha256,
        parser_version=parser_version,
        revision_identifier=required_text(row, "revisionIdentifier"),
        revision_status=required_text(row, "revisionStatus"),
        day_count_convention=day_count_convention,
        calendar_id=calendar_id,
        retrieved_at=snapshot.retrieved_at,
        source_metadata=metadata,
    )


def reject_duplicate_versions(versions: Sequence[RateVersion]) -> tuple[RateVersion, ...]:
    seen: dict[tuple[RateObservationIdentity, datetime, str], RateVersion] = {}
    for version in versions:
        key = (version.identity, version.publication_timestamp, version.revision_identifier)
        previous = seen.get(key)
        if previous is not None:
            if previous != version:
                raise RateSourceError("DUPLICATE_CONFLICTING_RATE_VERSION")
            continue
        seen[key] = version
    return tuple(
        sorted(
            seen.values(),
            key=lambda item: (
                item.observation_date,
                item.publication_timestamp,
                item.revision_identifier,
            ),
        )
    )


def certify_common(
    version: RateVersion,
    *,
    adapter_id: str,
    currency: str,
    series_ids: frozenset[str],
    publisher: str,
    parser_version: str,
    day_count_convention: str,
    calendar_id: str,
    publication_zone: str,
    endpoint_roles: frozenset[str],
) -> RateCertification:
    reasons: list[str] = []
    checks = (
        "OFFICIAL_SOURCE_IDENTITY",
        "SCHEMA",
        "PARSER",
        "TIMEZONE",
        "PUBLICATION_RULE",
        "EFFECTIVE_RULE",
        "REVISION_RULE",
        "CALENDAR",
        "POINT_IN_TIME_AVAILABILITY",
    )
    if version.currency != currency or version.series_id not in series_ids:
        reasons.append("IDENTITY_MISMATCH")
    if version.source_publisher != publisher:
        reasons.append("PUBLISHER_MISMATCH")
    if version.parser_version != parser_version:
        reasons.append("PARSER_VERSION_MISMATCH")
    if version.day_count_convention != day_count_convention:
        reasons.append("DAY_COUNT_MISMATCH")
    if version.calendar_id != calendar_id:
        reasons.append("CALENDAR_MISMATCH")
    if version.source_endpoint_role not in endpoint_roles:
        reasons.append("ENDPOINT_ROLE_MISMATCH")
    if not timestamp_matches_zone(version.publication_timestamp, publication_zone):
        reasons.append("PUBLICATION_TIMEZONE_MISMATCH")
    if not -20.0 <= version.value <= 100.0:
        reasons.append("RATE_OUT_OF_RANGE")
    status = "PASS" if not reasons else "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
    return RateCertification(
        adapter_id=adapter_id,
        identity=version.identity,
        revision_identifier=version.revision_identifier,
        passed=not reasons,
        status=status,
        checks=checks,
        reasons=tuple(reasons),
    )


def combine_certification(
    certification: RateCertification, extra_reasons: Sequence[str]
) -> RateCertification:
    reasons = tuple((*certification.reasons, *extra_reasons))
    return RateCertification(
        adapter_id=certification.adapter_id,
        identity=certification.identity,
        revision_identifier=certification.revision_identifier,
        passed=not reasons,
        status="PASS" if not reasons else "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
        checks=certification.checks,
        reasons=reasons,
    )


def required_text(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RateSourceError(f"{field_name.upper()}_REQUIRED")
    return value


def parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise RateSourceError("OBSERVATION_DATE_REQUIRED")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RateSourceError("INVALID_OBSERVATION_DATE") from exc
    _reject_prohibited_interval(parsed, parsed)
    return parsed


def parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RateSourceError(f"{label}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RateSourceError(f"INVALID_{label}") from exc
    return _require_aware(parsed, label)


def parse_finite_rate(value: object) -> float:
    if isinstance(value, bool):
        raise RateSourceError("RATE_VALUE_MUST_BE_NUMERIC")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RateSourceError("RATE_VALUE_MUST_BE_NUMERIC") from exc
    if not math.isfinite(parsed):
        raise RateSourceError("NON_FINITE_RATE_VALUE")
    if not -20.0 <= parsed <= 100.0:
        raise RateSourceError("RATE_OUT_OF_RANGE")
    return parsed


def timestamp_matches_zone(timestamp: datetime, zone_name: str) -> bool:
    expected = timestamp.astimezone(ZoneInfo(zone_name)).utcoffset()
    return timestamp.utcoffset() == expected


def _validate_machine_readable(snapshot: SourceSnapshot, allowed_types: tuple[str, ...]) -> None:
    beginning = snapshot.payload.lstrip()[:32].lower()
    if beginning.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        raise RateSourceError("HTML_ERROR_PAGE_REJECTED")
    media_type = snapshot.content_type.split(";", maxsplit=1)[0].strip().lower()
    if media_type not in allowed_types:
        raise RateSourceError("UNEXPECTED_CONTENT_TYPE")


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RateSourceError(f"{label}_MUST_BE_TIMEZONE_AWARE")
    return value


def _reject_prohibited_interval(start: date, end: date) -> None:
    if any(year in PROHIBITED_YEARS for year in range(start.year, end.year + 1)):
        raise RateSourceError("QUARANTINED_2023_2025_INTERVAL_PROHIBITED")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RateSourceError("INVALID_SOURCE_SNAPSHOT_SHA256")


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()
