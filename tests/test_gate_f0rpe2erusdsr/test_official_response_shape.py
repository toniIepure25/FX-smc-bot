from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import pytest

from fx_smc_bot.research.official_response_shape import (
    INSPECTOR_ID,
    OfficialResponseShapeError,
    OfficialResponseShapeInspector,
    inspect_official_json_response,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateAccessAuthorization,
    SourceSnapshot,
    schema_fingerprint,
)

ALLOWLIST_ID = "F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"
URL = "https://official.example.test/rates.json"


def _declaration() -> OfficialNumericalEndpoint:
    fields = ("effectiveDate", "footnote", "rate", "seriesCode")
    return OfficialNumericalEndpoint(
        allowlist_identity=ALLOWLIST_ID,
        adapter_id="SYNTHETIC_OFFICIAL_JSON_V3",
        currency="USD",
        series_id="EFFR",
        publisher="Synthetic Official Publisher",
        url=URL,
        start_parameter="startDate",
        end_parameter="endDate",
        series_parameter="eventCodes",
        series_parameter_value="500",
        response_format="json",
        accept_media_type="application/json",
        format_parameter="format",
        format_parameter_value="json",
        series_path_token=None,
        format_path_token=None,
        schema_id="SYNTHETIC_OFFICIAL_JSON_SHAPE_V1",
        required_fields=fields,
        schema_fingerprint=schema_fingerprint(
            "SYNTHETIC_OFFICIAL_JSON_SHAPE_V1", frozenset(fields)
        ),
        publication_timestamp_field="publicationTimestamp",
        effective_timestamp_field="effectiveTimestamp",
    )


def _request(
    *,
    start: date = date(2010, 1, 4),
    end: date = date(2010, 1, 5),
    declaration: OfficialNumericalEndpoint | None = None,
) -> OfficialRateRequest:
    endpoint = declaration or _declaration()
    return OfficialRateRequest(
        adapter_id=endpoint.adapter_id,
        currency=endpoint.currency,
        series_id=endpoint.series_id,
        source_publisher=endpoint.publisher,
        source_endpoint_role="OFFICIAL_NUMERICAL_ENDPOINT",
        start=start,
        end=end,
        url=endpoint.url,
        query_parameters=(
            ("endDate", end.isoformat()),
            ("eventCodes", "500"),
            ("format", "json"),
            ("startDate", start.isoformat()),
        ),
        endpoint_declaration=endpoint,
    )


def _authorization(request: OfficialRateRequest) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id="F0RPE2ERUSDSR_SHAPE_TEST_V1",
        adapter_ids=frozenset({request.adapter_id}),
        currencies=frozenset({request.currency}),
        series_ids=frozenset({request.series_id}),
        start=date(2010, 1, 1),
        end=date(2022, 12, 31),
        official_hosts=frozenset({urlparse(request.url).hostname or ""}),
        source_allowlist_identities=frozenset({ALLOWLIST_ID}),
    )


def _payload() -> dict[str, object]:
    return {
        "meta": {"generatedDate": "2010-01-06"},
        "response": {
            "rates": [
                {
                    "effectiveDate": "2010-01-04",
                    "seriesCode": "EFFR",
                    "rate": 4.25,
                    "footnote": None,
                },
                {
                    "effectiveDate": "2010-01-05",
                    "seriesCode": "EFFR",
                    "rate": 4,
                    "revision": "final",
                },
            ]
        },
    }


def _snapshot(
    payload: object = None,
    *,
    request: OfficialRateRequest | None = None,
    content_type: str = "application/json; charset=utf-8",
    raw_payload: bytes | None = None,
) -> SourceSnapshot:
    bounded_request = request or _request()
    body = (
        raw_payload
        if raw_payload is not None
        else json.dumps(_payload() if payload is None else payload).encode("utf-8")
    )
    return SourceSnapshot(
        request=bounded_request,
        payload=body,
        content_type=content_type,
        response_headers=(("content-type", content_type),),
        retrieved_at=datetime(2026, 7, 31, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(body).hexdigest(),
    )


def test_descriptor_is_recursive_sanitized_and_complete() -> None:
    snapshot = _snapshot()
    inspector = OfficialResponseShapeInspector(_authorization(snapshot.request))

    shape = inspector.inspect(snapshot)
    record = shape.to_record()

    assert inspector.inspector_id == INSPECTOR_ID
    assert shape.content_type == "application/json"
    assert shape.payload_encoding == "utf-8"
    assert shape.top_level_json_type == "object"
    assert shape.top_level_key_names == ("meta", "response")
    assert shape.candidate_row_container_paths == ("$.response.rates",)
    assert shape.row_count == 2
    assert shape.minimum_response_date == "2010-01-04"
    assert shape.maximum_response_date == "2010-01-06"
    assert shape.payload_byte_count == len(snapshot.payload)
    assert len(shape.schema_fingerprint) == 64

    rows = shape.row_containers[0]
    assert rows.row_object_key_names == (
        "effectiveDate",
        "footnote",
        "rate",
        "revision",
        "seriesCode",
    )
    assert dict(rows.field_json_types) == {
        "effectiveDate": ("string",),
        "footnote": ("null",),
        "rate": ("integer", "number"),
        "revision": ("string",),
        "seriesCode": ("string",),
    }
    assert rows.nullable_fields == ("footnote",)
    assert rows.stable_fields == ("effectiveDate", "rate", "seriesCode")
    assert rows.optional_fields == ("footnote", "revision")

    serialized = json.dumps(record, sort_keys=True)
    assert "4.25" not in serialized
    assert '"final"' not in serialized
    assert "individual" not in serialized


def test_fingerprint_is_stable_across_values_dates_and_row_cardinality() -> None:
    request = _request()
    authorization = _authorization(request)
    first = inspect_official_json_response(_snapshot(request=request), authorization)
    changed = _payload()
    rates = changed["response"]
    assert isinstance(rates, dict)
    rates["rates"] = [
        {
            "effectiveDate": "2011-02-03",
            "seriesCode": "DIFFERENT",
            "rate": 99.5,
            "footnote": None,
        },
        {
            "effectiveDate": "2011-02-04",
            "seriesCode": "DIFFERENT",
            "rate": 98,
            "revision": "corrected",
        },
        {
            "effectiveDate": "2011-02-05",
            "seriesCode": "DIFFERENT",
            "rate": 97.5,
            "footnote": None,
        },
    ]
    changed["meta"] = {"generatedDate": "2011-02-06"}

    second = inspect_official_json_response(
        _snapshot(changed, request=request), authorization
    )

    assert first.schema_fingerprint == second.schema_fingerprint
    assert first.row_count != second.row_count


def test_nested_repeated_containers_are_aggregated_by_wildcard_path() -> None:
    payload = {
        "groups": [
            {"rows": [{"effectiveDate": "2012-01-03", "rate": 1.0}]},
            {"rows": [{"effectiveDate": "2012-01-04", "rate": 2.0}]},
        ]
    }
    snapshot = _snapshot(payload)
    shape = inspect_official_json_response(snapshot, _authorization(snapshot.request))

    assert shape.candidate_row_container_paths == ("$.groups", "$.groups[*].rows")
    assert shape.row_containers[1].row_count == 2


@pytest.mark.parametrize(
    "outside_date",
    ["2009-12-31", "2023-01-01", "2025-12-31", "2026-01-01T00:00:00Z"],
)
def test_any_discovered_out_of_range_date_rejects_whole_response(
    outside_date: str,
) -> None:
    payload = _payload()
    payload["metadata"] = {"lastUpdate": outside_date}
    snapshot = _snapshot(payload)

    with pytest.raises(OfficialResponseShapeError) as exc_info:
        inspect_official_json_response(snapshot, _authorization(snapshot.request))

    assert exc_info.value.code == "RESPONSE_DATE_OUTSIDE_2010_2022"
    assert outside_date not in str(exc_info.value)


def test_rejection_is_atomic_and_exposes_no_partial_descriptor() -> None:
    payload = {
        "rows": [
            {"effectiveDate": "2010-01-04", "rate": 1.0},
            {"effectiveDate": "2023-01-01", "rate": 999.0},
        ]
    }
    snapshot = _snapshot(payload)

    with pytest.raises(OfficialResponseShapeError) as exc_info:
        inspect_official_json_response(snapshot, _authorization(snapshot.request))

    assert vars(exc_info.value) == {"code": "RESPONSE_DATE_OUTSIDE_2010_2022"}
    assert "999" not in str(exc_info.value)


def test_request_requires_allowlisted_declaration_and_authorization() -> None:
    declared = _request()
    undeclared = replace(declared, endpoint_declaration=None)
    snapshot = _snapshot(request=undeclared)
    with pytest.raises(
        OfficialResponseShapeError,
        match="ALLOWLISTED_ENDPOINT_DECLARATION_REQUIRED",
    ):
        inspect_official_json_response(snapshot, _authorization(declared))

    wrong_authorization = replace(
        _authorization(declared),
        source_allowlist_identities=frozenset({"DIFFERENT_ALLOWLIST"}),
    )
    with pytest.raises(
        OfficialResponseShapeError,
        match="DECLARATION_OR_REQUEST_AUTHORIZATION_FAILED",
    ):
        inspect_official_json_response(_snapshot(request=declared), wrong_authorization)


def test_request_accept_header_and_actual_media_type_must_match_declaration() -> None:
    request = replace(_request(), request_headers=(("Accept", "text/json"),))
    snapshot = _snapshot(request=request)
    with pytest.raises(OfficialResponseShapeError, match="REQUEST_ACCEPT_HEADER_MISMATCH"):
        inspect_official_json_response(snapshot, _authorization(request))

    request = _request()
    snapshot = _snapshot(request=request, content_type="text/html")
    with pytest.raises(
        OfficialResponseShapeError,
        match="HTTP_CONTENT_TYPE_NOT_DECLARED_JSON",
    ):
        inspect_official_json_response(snapshot, _authorization(request))


@pytest.mark.parametrize(
    ("raw_payload", "expected_code"),
    [
        (b'\xff\xfe{\x00}\x00', "JSON_ENCODING_NOT_UTF8"),
        (b'{"rows": [{"date": NaN}]}', "NONSTANDARD_JSON_NUMBER"),
        (
            b'{"rows": [{"effectiveDate": "2010-01-04", "rate": 1, "rate": 2}]}',
            "DUPLICATE_JSON_OBJECT_KEY",
        ),
    ],
)
def test_non_utf8_nonstandard_numbers_and_duplicate_keys_fail_closed(
    raw_payload: bytes, expected_code: str
) -> None:
    snapshot = _snapshot(raw_payload=raw_payload)
    with pytest.raises(OfficialResponseShapeError) as exc_info:
        inspect_official_json_response(snapshot, _authorization(snapshot.request))
    assert exc_info.value.code == expected_code


def test_utf8_bom_is_reported_without_exposing_payload() -> None:
    body = b"\xef\xbb\xbf" + json.dumps(_payload()).encode("utf-8")
    snapshot = _snapshot(raw_payload=body)
    shape = inspect_official_json_response(snapshot, _authorization(snapshot.request))
    assert shape.payload_encoding == "utf-8-sig"


@pytest.mark.parametrize(
    "payload",
    [
        {"rows": [{"effectiveDate": "not-a-date", "rate": 1.0}]},
        {"rows": [{"effectiveDate": 20100104, "rate": 1.0}]},
        {"rows": [{"effectiveDate": "2010-13-40", "rate": 1.0}]},
        {"metadata": {"generatedDate": "2010-01-04"}},
        {"rows": [{"effectiveDate": "2010-01-04"}, 1]},
    ],
)
def test_ambiguous_or_non_structural_json_is_not_accepted(payload: object) -> None:
    snapshot = _snapshot(payload)
    with pytest.raises(OfficialResponseShapeError):
        inspect_official_json_response(snapshot, _authorization(snapshot.request))
