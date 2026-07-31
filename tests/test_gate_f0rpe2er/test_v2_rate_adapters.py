from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from fx_smc_bot.research.rate_sources import (
    OFFICIAL_RATE_ADAPTERS,
    OFFICIAL_RATE_ADAPTERS_V2,
)
from fx_smc_bot.research.rate_sources.bank_of_canada import BankOfCanadaAdapterV2
from fx_smc_bot.research.rate_sources.bank_of_england import BankOfEnglandSoniaAdapterV2
from fx_smc_bot.research.rate_sources.bank_of_japan import BankOfJapanCallRateAdapterV2
from fx_smc_bot.research.rate_sources.base import (
    BoundedRetryPolicy,
    OfficialNumericalEndpoint,
    OfficialRateAdapter,
    RateAccessAuthorization,
    RateSourceError,
    SourceSnapshot,
    schema_fingerprint,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient
from fx_smc_bot.research.rate_sources.ecb import EcbEoniaEstrAdapterV2
from fx_smc_bot.research.rate_sources.new_york_fed import NewYorkFedEffrAdapterV2
from fx_smc_bot.research.rate_sources.rba import RbaCashRateAdapterV2
from fx_smc_bot.research.rate_sources.saron import Saron18AdapterV2

ALLOWLIST_ID = "F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"
ALLOWLIST_PATH = Path("results/gate_f0rpe2er/official_source_allowlist.json")


def _declarations() -> tuple[OfficialNumericalEndpoint, ...]:
    return tuple(
        declaration
        for adapter_type in OFFICIAL_RATE_ADAPTERS_V2
        for declaration in adapter_type.endpoint_declarations
    )


def _authorization(
    adapter: OfficialRateAdapter,
    start: date,
    end: date,
) -> RateAccessAuthorization:
    declarations = adapter.endpoint_declarations  # type: ignore[attr-defined]
    return RateAccessAuthorization(
        authorization_id="F0RPE2ER_SYNTHETIC_V2_ADAPTER_TEST",
        adapter_ids=frozenset({adapter.adapter_id}),
        currencies=frozenset({adapter.currency}),
        series_ids=frozenset(item.series_id for item in declarations),
        start=start,
        end=end,
        official_hosts=frozenset(urlparse(item.url).hostname or "" for item in declarations),
        source_allowlist_identities=frozenset({ALLOWLIST_ID}),
    )


def _request(adapter: OfficialRateAdapter, observation: date):
    requests = adapter.build_requests(
        observation,
        observation,
        _authorization(adapter, observation, observation),
    )
    assert len(requests) == 1
    return requests[0]


def _case(adapter: OfficialRateAdapter) -> tuple[date, dict[str, object]]:
    row: dict[str, object] = {
        "currency": adapter.currency,
        "seriesId": adapter.series_id,
        "value": "1.25",
        "sourceDocumentId": "synthetic-pre-2023-official-document",
        "revisionIdentifier": "synthetic-original",
        "revisionStatus": "ORIGINAL",
    }
    if isinstance(adapter, NewYorkFedEffrAdapterV2):
        observation = date(2016, 1, 4)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-05T14:30:00-05:00",
            effectiveTimestamp="2016-01-05T14:30:00-05:00",
            footnotes="synthetic",
        )
    elif isinstance(adapter, EcbEoniaEstrAdapterV2):
        observation = date(2019, 10, 1)
        row.update(
            seriesId="ESTR",
            observationDate=observation.isoformat(),
            publicationTimestamp="2019-10-02T09:00:00+02:00",
            effectiveTimestamp="2019-10-02T09:00:00+02:00",
            publicationType="STANDARD",
            calculationMethod="ESTR",
        )
    elif isinstance(adapter, BankOfEnglandSoniaAdapterV2):
        observation = date(2018, 4, 23)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2018-04-24T12:00:00+01:00",
            effectiveTimestamp="2018-04-24T12:00:00+01:00",
            methodologyRegime="REFORMED",
        )
    elif isinstance(adapter, RbaCashRateAdapterV2):
        observation = date(2016, 5, 2)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-05-03T16:00:00+10:00",
            effectiveTimestamp="2016-05-03T16:00:00+10:00",
            methodologyRegime="RITS_IDENTIFIED_TRANSACTIONS",
        )
    elif isinstance(adapter, BankOfJapanCallRateAdapterV2):
        observation = date(2016, 1, 4)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-05T10:00:00+09:00",
            effectiveTimestamp="2016-01-05T10:00:00+09:00",
            revisionStatus="FINAL",
            resultType="FINAL",
        )
    elif isinstance(adapter, BankOfCanadaAdapterV2):
        observation = date(2016, 1, 20)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-20T10:00:00-05:00",
            effectiveTimestamp="2016-01-20T10:00:00-05:00",
            announcementType="POLICY_RATE_DECISION",
        )
    else:
        assert isinstance(adapter, Saron18AdapterV2)
        observation = date(2016, 1, 4)
        row.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-05T18:00:00+01:00",
            effectiveTimestamp="2016-01-05T18:00:00+01:00",
            fixingLabel="18:00",
        )
    return observation, row


def _payload(adapter: OfficialRateAdapter, row: dict[str, object]) -> tuple[bytes, str]:
    if isinstance(adapter, BankOfEnglandSoniaAdapterV2):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=adapter.csv_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
        return stream.getvalue().encode("ascii"), "text/csv"
    payload = json.dumps(
        {"schema": adapter.schema_id, "observations": [row]},  # type: ignore[attr-defined]
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return payload, "application/json"


def _snapshot(adapter: OfficialRateAdapter) -> SourceSnapshot:
    observation, row = _case(adapter)
    payload, content_type = _payload(adapter, row)
    return SourceSnapshot(
        request=_request(adapter, observation),
        payload=payload,
        content_type=content_type,
        response_headers=(("content-type", content_type),),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_exactly_seven_v2_adapters_and_eight_endpoint_declarations() -> None:
    assert len(OFFICIAL_RATE_ADAPTERS) == 7
    assert all(adapter.adapter_id.endswith("_V1") for adapter in OFFICIAL_RATE_ADAPTERS)
    assert len(OFFICIAL_RATE_ADAPTERS_V2) == 7
    assert len(_declarations()) == 8
    assert len({item.declaration_sha256 for item in _declarations()}) == 8
    assert {adapter.currency for adapter in OFFICIAL_RATE_ADAPTERS_V2} == {
        "USD",
        "EUR",
        "GBP",
        "AUD",
        "JPY",
        "CAD",
        "CHF",
    }


def test_declarations_match_frozen_official_source_allowlist_exactly() -> None:
    allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert allowlist["allowlist_id"] == ALLOWLIST_ID
    expected = {(record["adapter"], record["series"]): record for record in allowlist["records"]}
    actual = {(item.adapter_id, item.series_id): item for item in _declarations()}
    assert actual.keys() == expected.keys()
    for key, declaration in actual.items():
        record = expected[key]
        assert declaration.allowlist_identity == ALLOWLIST_ID
        assert declaration.currency == record["currency"]
        assert declaration.publisher == record["publisher"]
        assert declaration.url == record["numerical_endpoint"]
        assert [declaration.start_parameter, declaration.end_parameter] == record[
            "server_side_date_parameters"
        ]
        assert declaration.series_parameter == record["series_parameter"]
        assert declaration.response_format == record["format"]
        assert declaration.schema_id == record["expected_schema"]


@pytest.mark.parametrize("adapter_type", OFFICIAL_RATE_ADAPTERS_V2)
def test_requests_carry_bounds_series_format_and_allowlist_identity(
    adapter_type: type[OfficialRateAdapter],
) -> None:
    adapter = adapter_type()
    start = date(2016, 1, 4)
    end = date(2016, 1, 8)
    requests = adapter.build_requests(start, end, _authorization(adapter, start, end))
    assert requests == adapter.build_requests(start, end, _authorization(adapter, start, end))
    for request in requests:
        declaration = request.endpoint_declaration
        assert declaration is not None
        parameters = dict(request.query_parameters)
        assert declaration.start_parameter in parameters
        assert declaration.end_parameter in parameters
        assert request.start == start and request.end == end
        assert request.request_headers == (("Accept", declaration.accept_media_type),)
        declaration.validate_request(request)
        assert request.request_identity


def test_boe_is_columnar_csv_end_to_end_contract() -> None:
    adapter = BankOfEnglandSoniaAdapterV2()
    declaration = adapter.endpoint_declarations[0]
    request = _request(adapter, date(2018, 4, 23))
    assert declaration.response_format == "CSV_COLUMNAR"
    assert declaration.schema_id == "BOE_IADB_COLUMNAR_CSV_V2"
    assert adapter.parser_version == "BOE_IUDSOIA_COLUMNAR_CSV_V2"
    assert request.request_headers == (("Accept", "text/csv"),)


def test_schema_fingerprints_and_retry_policies_are_frozen_and_bounded() -> None:
    for declaration in _declarations():
        assert declaration.schema_fingerprint == schema_fingerprint(
            declaration.schema_id, frozenset(declaration.required_fields)
        )
        assert len(declaration.schema_fingerprint) == 64
        policy = declaration.retry_policy
        assert 1 <= policy.maximum_attempts <= 4
        assert policy.backoff_seconds(1) <= policy.maximum_backoff_seconds
        assert tuple(sorted(set(policy.retryable_status_codes))) == policy.retryable_status_codes
    with pytest.raises(RateSourceError, match="RETRY_ATTEMPTS_NOT_BOUNDED"):
        BoundedRetryPolicy(maximum_attempts=5)


@pytest.mark.parametrize("adapter_type", OFFICIAL_RATE_ADAPTERS_V2)
def test_v2_adapters_parse_and_certify_synthetic_pre_2023_fixture(
    adapter_type: type[OfficialRateAdapter],
) -> None:
    adapter = adapter_type()
    versions = adapter.parse_snapshot(_snapshot(adapter))
    assert len(versions) == 1
    certification = adapter.certify_version(versions[0])
    assert certification.passed is True
    assert certification.status == "PASS"
    assert versions[0].observation_date <= date(2022, 12, 31)
    assert versions[0].strategy_availability_timestamp == max(
        versions[0].publication_timestamp, versions[0].effective_timestamp
    )


def test_snapshot_hashing_is_mandatory_and_request_identity_pins_declaration() -> None:
    adapter = NewYorkFedEffrAdapterV2()
    snapshot = _snapshot(adapter)
    assert snapshot.source_snapshot_sha256 == hashlib.sha256(snapshot.payload).hexdigest()
    assert snapshot.request.endpoint_declaration is not None
    changed_declaration = replace(
        snapshot.request.endpoint_declaration,
        retry_policy=BoundedRetryPolicy(maximum_attempts=2),
    )
    changed_request = replace(snapshot.request, endpoint_declaration=changed_declaration)
    assert changed_request.request_identity != snapshot.request.request_identity
    with pytest.raises(RateSourceError, match="SOURCE_SNAPSHOT_SHA256_MISMATCH"):
        replace(snapshot, source_snapshot_sha256="0" * 64)


def test_unbounded_quarantined_nzd_and_missing_allowlist_fail_before_network(
    tmp_path: Path,
) -> None:
    adapter = NewYorkFedEffrAdapterV2()
    with pytest.raises(RateSourceError, match="V2_REQUEST_OUTSIDE_2010_2022"):
        adapter.build_requests(
            date(2009, 12, 31),
            date(2010, 1, 1),
            _authorization(adapter, date(2009, 12, 31), date(2010, 1, 1)),
        )
    with pytest.raises(RateSourceError, match="QUARANTINED"):
        adapter.build_requests(
            date(2024, 1, 2),
            date(2024, 1, 2),
            _authorization(adapter, date(2024, 1, 2), date(2024, 1, 2)),
        )
    with pytest.raises(RateSourceError, match="NZD"):
        replace(adapter.endpoint_declarations[0], currency="NZD")

    observation = date(2016, 1, 4)
    request = _request(adapter, observation)
    authorization = replace(
        _authorization(adapter, observation, observation),
        source_allowlist_identities=frozenset(),
    )
    with pytest.raises(RateSourceError, match="SOURCE_ALLOWLIST"):
        authorization.authorize(request)
    with pytest.raises(RateSourceError, match="FIREWALL_REQUIRED_BEFORE_HTTP"):
        OfficialRateSnapshotClient(tmp_path).fetch(
            request,
            _authorization(adapter, observation, observation),
        )


def test_missing_server_bounds_or_series_or_format_is_rejected() -> None:
    adapter = NewYorkFedEffrAdapterV2()
    request = _request(adapter, date(2016, 1, 4))
    parameters = dict(request.query_parameters)
    for missing, reason in (
        ("startDate", "SERVER_SIDE_DATE_BOUNDS_REQUIRED"),
        ("eventCodes", "SERVER_SIDE_SERIES_PARAMETER_REQUIRED"),
        ("format", "EXPLICIT_RESPONSE_FORMAT_REQUIRED"),
    ):
        changed = tuple(sorted((key, value) for key, value in parameters.items() if key != missing))
        with pytest.raises(RateSourceError, match=reason):
            replace(request, query_parameters=changed)
