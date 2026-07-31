"""Fail-closed structural inspection of bounded official JSON responses.

The inspector is deliberately not a parser and does not expose observation
values.  It accepts a snapshot only after the frozen endpoint declaration,
authorization, request bounds, content type, JSON encoding, and every date in
the complete response have passed validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, NoReturn, cast

from fx_smc_bot.research.rate_sources.base import (
    V2_AUTHORIZED_END,
    V2_AUTHORIZED_START,
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
    SourceSnapshot,
)

INSPECTOR_ID: Final = "F0RPE2ERUSDSR_OFFICIAL_RESPONSE_SHAPE_V1"
_JSON_MEDIA_TYPES: Final = frozenset({"application/json", "text/json"})
_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:$|[Tt ][0-9])")
_DATE_FIELD_SUFFIXES: Final = (
    "date",
    "datetime",
    "timestamp",
    "asof",
    "lastupdate",
)


class OfficialResponseShapeError(RateSourceError):
    """Sanitized failure that never includes a payload value or fragment."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RowContainerShape:
    """Value-free structural summary of one candidate row container."""

    path: str
    row_count: int
    row_object_key_names: tuple[str, ...]
    field_json_types: tuple[tuple[str, tuple[str, ...]], ...]
    nullable_fields: tuple[str, ...]
    stable_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "row_object_key_names": list(self.row_object_key_names),
            "field_json_types": {
                name: list(json_types) for name, json_types in self.field_json_types
            },
            "nullable_fields": list(self.nullable_fields),
            "stable_fields": list(self.stable_fields),
            "optional_fields": list(self.optional_fields),
        }

    def fingerprint_record(self) -> dict[str, object]:
        """Return only cardinality-independent schema attributes."""

        record = self.to_record()
        del record["row_count"]
        return record


@dataclass(frozen=True, slots=True)
class OfficialResponseShape:
    """Sanitized descriptor safe to persist as structural evidence."""

    content_type: str
    payload_encoding: str
    top_level_json_type: str
    top_level_key_names: tuple[str, ...]
    row_containers: tuple[RowContainerShape, ...]
    schema_fingerprint: str
    payload_byte_count: int
    row_count: int
    minimum_response_date: str
    maximum_response_date: str

    @property
    def candidate_row_container_paths(self) -> tuple[str, ...]:
        return tuple(container.path for container in self.row_containers)

    def to_record(self) -> dict[str, object]:
        """Serialize only the Phase 3 allowlisted structural fields."""

        return {
            "content_type": self.content_type,
            "payload_encoding": self.payload_encoding,
            "top_level_json_type": self.top_level_json_type,
            "top_level_key_names": list(self.top_level_key_names),
            "candidate_row_container_paths": list(
                self.candidate_row_container_paths
            ),
            "row_containers": [container.to_record() for container in self.row_containers],
            "schema_fingerprint": self.schema_fingerprint,
            "payload_byte_count": self.payload_byte_count,
            "row_count": self.row_count,
            "minimum_response_date": self.minimum_response_date,
            "maximum_response_date": self.maximum_response_date,
        }


class OfficialResponseShapeInspector:
    """Inspect complete snapshots under one explicit access authorization."""

    def __init__(self, authorization: RateAccessAuthorization) -> None:
        self.inspector_id = INSPECTOR_ID
        self.authorization = authorization

    def inspect(self, snapshot: SourceSnapshot) -> OfficialResponseShape:
        """Return a descriptor only when every fail-closed check succeeds."""

        request = snapshot.request
        declaration = self._validate_request(request)
        content_type = _media_type(snapshot.content_type)
        declared_content_type = _media_type(declaration.accept_media_type)
        if declared_content_type not in _JSON_MEDIA_TYPES:
            _fail("DECLARATION_NOT_JSON")
        if content_type != declared_content_type:
            _fail("HTTP_CONTENT_TYPE_NOT_DECLARED_JSON")

        payload_encoding, document = _decode_json(snapshot.payload)
        if not isinstance(document, dict | list):
            _fail("TOP_LEVEL_JSON_CONTAINER_REQUIRED")

        response_dates: list[date] = []
        candidate_rows: dict[str, list[Mapping[str, object]]] = {}
        _walk_document(document, "$", None, response_dates, candidate_rows)
        if not response_dates:
            _fail("RESPONSE_DATE_REQUIRED")
        if not candidate_rows:
            _fail("CANDIDATE_ROW_CONTAINER_REQUIRED")

        row_containers = tuple(
            _summarize_container(path, rows)
            for path, rows in sorted(candidate_rows.items())
        )
        top_level_keys = (
            tuple(sorted(cast(dict[str, object], document)))
            if isinstance(document, dict)
            else ()
        )
        top_level_type = _json_type(document)
        fingerprint = _schema_fingerprint(
            content_type=content_type,
            payload_encoding=payload_encoding,
            top_level_json_type=top_level_type,
            top_level_key_names=top_level_keys,
            row_containers=row_containers,
        )
        return OfficialResponseShape(
            content_type=content_type,
            payload_encoding=payload_encoding,
            top_level_json_type=top_level_type,
            top_level_key_names=top_level_keys,
            row_containers=row_containers,
            schema_fingerprint=fingerprint,
            payload_byte_count=len(snapshot.payload),
            row_count=sum(container.row_count for container in row_containers),
            minimum_response_date=min(response_dates).isoformat(),
            maximum_response_date=max(response_dates).isoformat(),
        )

    def _validate_request(self, request: OfficialRateRequest) -> OfficialNumericalEndpoint:
        declaration = request.endpoint_declaration
        if declaration is None:
            _fail("ALLOWLISTED_ENDPOINT_DECLARATION_REQUIRED")
        if (
            request.start < V2_AUTHORIZED_START
            or request.end > V2_AUTHORIZED_END
            or request.start > request.end
        ):
            _fail("REQUEST_OUTSIDE_2010_2022")
        try:
            self.authorization.authorize(request)
            declaration.validate_request(request)
        except RateSourceError:
            _fail("DECLARATION_OR_REQUEST_AUTHORIZATION_FAILED")
        request_accept = dict(request.request_headers).get("Accept")
        if request_accept != declaration.accept_media_type:
            _fail("REQUEST_ACCEPT_HEADER_MISMATCH")
        if declaration.response_format.lower() != "json":
            _fail("DECLARATION_NOT_JSON")
        return declaration


def inspect_official_json_response(
    snapshot: SourceSnapshot,
    authorization: RateAccessAuthorization,
) -> OfficialResponseShape:
    """Convenience entry point for a single authorized snapshot."""

    return OfficialResponseShapeInspector(authorization).inspect(snapshot)


def _decode_json(payload: bytes) -> tuple[str, object]:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        _fail("JSON_ENCODING_NOT_UTF8")
    encoding = "utf-8-sig" if payload.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        text = payload.decode(encoding)
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("INVALID_UTF8_JSON")
    return encoding, document


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_JSON_OBJECT_KEY")
        result[key] = value
    return result


def _reject_nonstandard_number(_: str) -> NoReturn:
    _fail("NONSTANDARD_JSON_NUMBER")


def _walk_document(
    value: object,
    path: str,
    field_name: str | None,
    response_dates: list[date],
    candidate_rows: dict[str, list[Mapping[str, object]]],
) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            _walk_document(
                value[key],
                _child_path(path, key),
                key,
                response_dates,
                candidate_rows,
            )
        return
    if isinstance(value, list):
        mapping_items = [item for item in value if isinstance(item, Mapping)]
        if mapping_items and len(mapping_items) != len(value):
            _fail("HETEROGENEOUS_OBJECT_ARRAY")
        if not value or len(mapping_items) == len(value):
            rows = candidate_rows.setdefault(path, [])
            rows.extend(cast(list[Mapping[str, object]], mapping_items))
        for item in value:
            _walk_document(item, f"{path}[*]", None, response_dates, candidate_rows)
        return
    if value is None:
        return
    if not isinstance(value, str):
        if field_name is not None and _is_date_field(field_name):
            _fail("DATE_FIELD_MUST_BE_ISO_STRING_OR_NULL")
        return

    match = _ISO_DATE_PREFIX.match(value)
    if match is None:
        if field_name is not None and _is_date_field(field_name):
            _fail("DATE_FIELD_MUST_BE_ISO_STRING_OR_NULL")
        return
    try:
        discovered = date.fromisoformat(match.group(1))
        if len(value) > 10:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("INVALID_RESPONSE_DATE")
    if discovered < V2_AUTHORIZED_START or discovered > V2_AUTHORIZED_END:
        _fail("RESPONSE_DATE_OUTSIDE_2010_2022")
    response_dates.append(discovered)


def _summarize_container(
    path: str, rows: list[Mapping[str, object]]
) -> RowContainerShape:
    key_sets = [set(row) for row in rows]
    all_keys = set().union(*key_sets) if key_sets else set()
    stable = set.intersection(*key_sets) if key_sets else set()
    field_types = tuple(
        (
            key,
            tuple(sorted({_json_type(row[key]) for row in rows if key in row})),
        )
        for key in sorted(all_keys)
    )
    return RowContainerShape(
        path=path,
        row_count=len(rows),
        row_object_key_names=tuple(sorted(all_keys)),
        field_json_types=field_types,
        nullable_fields=tuple(
            key
            for key in sorted(all_keys)
            if any(key in row and row[key] is None for row in rows)
        ),
        stable_fields=tuple(sorted(stable)),
        optional_fields=tuple(sorted(all_keys - stable)),
    )


def _schema_fingerprint(
    *,
    content_type: str,
    payload_encoding: str,
    top_level_json_type: str,
    top_level_key_names: tuple[str, ...],
    row_containers: tuple[RowContainerShape, ...],
) -> str:
    structure = {
        "content_type": content_type,
        "payload_encoding": payload_encoding,
        "top_level_json_type": top_level_json_type,
        "top_level_key_names": top_level_key_names,
        "row_containers": [container.fingerprint_record() for container in row_containers],
    }
    encoded = json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    _fail("UNSUPPORTED_JSON_TYPE")


def _media_type(content_type: str) -> str:
    media_type = content_type.partition(";")[0].strip().lower()
    if not media_type:
        _fail("HTTP_CONTENT_TYPE_REQUIRED")
    return media_type


def _is_date_field(field_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", field_name.lower())
    return normalized.endswith(_DATE_FIELD_SUFFIXES)


def _child_path(path: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{path}.{key}"
    encoded = json.dumps(key, ensure_ascii=True)
    return f"{path}[{encoded}]"


def _fail(code: str) -> NoReturn:
    raise OfficialResponseShapeError(code)
