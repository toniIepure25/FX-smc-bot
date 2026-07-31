from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fx_smc_bot.research.rate_sources import OFFICIAL_RATE_ADAPTERS
from fx_smc_bot.research.rate_sources.bank_of_canada import BankOfCanadaAdapter
from fx_smc_bot.research.rate_sources.bank_of_england import (
    SONIA_REFORM_START,
    BankOfEnglandSoniaAdapter,
)
from fx_smc_bot.research.rate_sources.bank_of_japan import BankOfJapanCallRateAdapter
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateAdapter,
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
    RateVersion,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.ecb import (
    EONIA_END,
    ESTR_START,
    EcbEoniaEstrAdapter,
)
from fx_smc_bot.research.rate_sources.new_york_fed import NewYorkFedEffrAdapter
from fx_smc_bot.research.rate_sources.rba import RbaCashRateAdapter
from fx_smc_bot.research.rate_sources.saron import Saron18Adapter

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rates"


def _authorization(
    adapter: OfficialRateAdapter, start: date, end: date
) -> RateAccessAuthorization:
    series_ids = {adapter.series_id}
    if isinstance(adapter, EcbEoniaEstrAdapter):
        series_ids.update({"EONIA", "ESTR"})
    requests_host = {
        NewYorkFedEffrAdapter: "markets.newyorkfed.org",
        EcbEoniaEstrAdapter: "data-api.ecb.europa.eu",
        BankOfEnglandSoniaAdapter: "www.bankofengland.co.uk",
        RbaCashRateAdapter: "www.rba.gov.au",
        BankOfJapanCallRateAdapter: "www.stat-search.boj.or.jp",
        BankOfCanadaAdapter: "www.bankofcanada.ca",
        Saron18Adapter: "data.snb.ch",
    }
    return RateAccessAuthorization(
        authorization_id="SYNTHETIC_ADAPTER_TEST",
        adapter_ids=frozenset({adapter.adapter_id}),
        currencies=frozenset({adapter.currency}),
        series_ids=frozenset(series_ids),
        start=start,
        end=end,
        official_hosts=frozenset({requests_host[type(adapter)]}),
    )


def _request(
    adapter: OfficialRateAdapter, start: date, end: date
) -> OfficialRateRequest:
    requests = adapter.build_requests(start, end, _authorization(adapter, start, end))
    assert len(requests) == 1
    return requests[0]


def _snapshot(request: OfficialRateRequest, payload: bytes) -> SourceSnapshot:
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type="application/json; charset=utf-8",
        response_headers=(("content-type", "application/json"), ("etag", '"synthetic"')),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _payload(adapter: OfficialRateAdapter, rows: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"schema": str(adapter.schema_id), "observations": rows},  # type: ignore[attr-defined]
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _case(adapter: OfficialRateAdapter) -> tuple[date, dict[str, object]]:
    common: dict[str, object] = {
        "currency": adapter.currency,
        "seriesId": adapter.series_id,
        "value": "1.25",
        "sourceDocumentId": "synthetic-official-document",
        "revisionIdentifier": "original",
        "revisionStatus": "ORIGINAL",
    }
    if isinstance(adapter, NewYorkFedEffrAdapter):
        observation = date(2016, 1, 4)
        common.update(
            observationDate="2016-01-04",
            publicationTimestamp="2016-01-05T14:30:00-05:00",
            effectiveTimestamp="2016-01-05T14:30:00-05:00",
            footnotes="synthetic schema field",
        )
    elif isinstance(adapter, EcbEoniaEstrAdapter):
        observation = ESTR_START
        common.update(
            seriesId="ESTR",
            observationDate=observation.isoformat(),
            publicationTimestamp="2019-10-02T09:00:00+02:00",
            effectiveTimestamp="2019-10-02T09:00:00+02:00",
            publicationType="STANDARD",
            calculationMethod="ESTR",
        )
    elif isinstance(adapter, BankOfEnglandSoniaAdapter):
        observation = SONIA_REFORM_START
        common.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2018-04-24T12:00:00+01:00",
            effectiveTimestamp="2018-04-24T12:00:00+01:00",
            methodologyRegime="REFORMED",
        )
    elif isinstance(adapter, RbaCashRateAdapter):
        observation = date(2016, 5, 2)
        common.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-05-03T16:00:00+10:00",
            effectiveTimestamp="2016-05-03T16:00:00+10:00",
            methodologyRegime="RITS_IDENTIFIED_TRANSACTIONS",
        )
    elif isinstance(adapter, BankOfJapanCallRateAdapter):
        observation = date(2016, 1, 4)
        common.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-05T10:00:00+09:00",
            effectiveTimestamp="2016-01-05T10:00:00+09:00",
            revisionStatus="FINAL",
            resultType="FINAL",
        )
    elif isinstance(adapter, BankOfCanadaAdapter):
        observation = date(2016, 1, 20)
        common.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-20T10:00:00-05:00",
            effectiveTimestamp="2016-01-20T10:00:00-05:00",
            announcementType="POLICY_RATE_DECISION",
        )
    else:
        assert isinstance(adapter, Saron18Adapter)
        observation = date(2016, 1, 4)
        common.update(
            observationDate=observation.isoformat(),
            publicationTimestamp="2016-01-05T18:00:00+01:00",
            effectiveTimestamp="2016-01-05T18:00:00+01:00",
            fixingLabel="18:00",
        )
    return observation, common


def _parsed(adapter: OfficialRateAdapter) -> RateVersion:
    observation, row = _case(adapter)
    request = _request(adapter, observation, observation)
    versions = adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row])))
    assert len(versions) == 1
    return versions[0]


def test_exactly_seven_adapters_and_schema_metadata_fixture() -> None:
    assert len(OFFICIAL_RATE_ADAPTERS) == 7
    instances = tuple(adapter_type() for adapter_type in OFFICIAL_RATE_ADAPTERS)
    assert {adapter.currency for adapter in instances} == {
        "USD",
        "EUR",
        "GBP",
        "AUD",
        "JPY",
        "CAD",
        "CHF",
    }
    catalog = json.loads((FIXTURE_ROOT / "schema_catalog.json").read_text(encoding="utf-8"))
    assert catalog["contains_observation_rows"] is False
    assert catalog["schemas"] == {
        adapter.currency: adapter.schema_id for adapter in instances
    }


@pytest.mark.parametrize("adapter_type", OFFICIAL_RATE_ADAPTERS)
def test_requests_are_bounded_authorized_and_deterministic(
    adapter_type: type[OfficialRateAdapter],
) -> None:
    adapter = adapter_type()
    start = date(2016, 1, 1)
    end = date(2016, 12, 31)
    authorization = _authorization(adapter, start, end)
    first = adapter.build_requests(start, end, authorization)
    second = adapter.build_requests(start, end, authorization)
    assert first == second
    assert all(request.url.startswith("https://") for request in first)
    assert all(request.request_identity for request in first)
    assert all(request.start >= start and request.end <= end for request in first)


@pytest.mark.parametrize("adapter_type", OFFICIAL_RATE_ADAPTERS)
def test_strict_parser_and_certification_pass_synthetic_contract(
    adapter_type: type[OfficialRateAdapter],
) -> None:
    adapter = adapter_type()
    version = _parsed(adapter)
    certification = adapter.certify_version(version)
    assert certification.passed is True
    assert certification.status == "PASS"
    assert version.strategy_availability_timestamp == max(
        version.publication_timestamp, version.effective_timestamp
    )
    assert version.retrieved_at > version.strategy_availability_timestamp
    assert version.source_snapshot_sha256


def test_eonia_estr_request_split_has_no_overlap_or_gap() -> None:
    adapter = EcbEoniaEstrAdapter()
    start = date(2019, 9, 29)
    end = date(2019, 10, 2)
    requests = adapter.build_requests(start, end, _authorization(adapter, start, end))
    assert [(item.series_id, item.start, item.end) for item in requests] == [
        ("EONIA", start, EONIA_END),
        ("ESTR", ESTR_START, end),
    ]
    assert requests[0].end.toordinal() + 1 == requests[1].start.toordinal()


def test_eonia_estr_wrong_side_of_transition_is_rejected() -> None:
    adapter = EcbEoniaEstrAdapter()
    observation = ESTR_START
    _, row = _case(adapter)
    row["seriesId"] = "EONIA"
    request = adapter.build_requests(
        observation,
        observation,
        _authorization(adapter, observation, observation),
    )[0]
    request = replace(request, series_id="EONIA")
    with pytest.raises(RateSourceError, match="TRANSITION"):
        adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row])))


def test_effective_after_publication_controls_strategy_availability() -> None:
    adapter = BankOfCanadaAdapter()
    observation, row = _case(adapter)
    row["effectiveTimestamp"] = "2016-01-21T00:00:00-05:00"
    request = _request(adapter, observation, observation)
    version = adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row])))[0]
    assert version.strategy_availability_timestamp == version.effective_timestamp
    assert version.strategy_availability_timestamp != version.retrieved_at


@pytest.mark.parametrize("prefix", [b"<html>error</html>", b"<!DOCTYPE html><p>error</p>"])
def test_http_200_html_payload_is_rejected(prefix: bytes) -> None:
    adapter = NewYorkFedEffrAdapter()
    observation, _ = _case(adapter)
    request = _request(adapter, observation, observation)
    with pytest.raises(RateSourceError, match="HTML_ERROR_PAGE_REJECTED"):
        adapter.parse_snapshot(_snapshot(request, prefix))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("publicationTimestamp", None, "PUBLICATION_TIMESTAMP_REQUIRED"),
        ("publicationTimestamp", "2016-01-05T14:30:00", "TIMEZONE_AWARE"),
        ("value", "NaN", "NON_FINITE"),
        ("value", "1000", "OUT_OF_RANGE"),
        ("currency", "CAD", "UNEXPECTED_CURRENCY"),
        ("seriesId", "NOT_EFFR", "UNEXPECTED_SERIES"),
    ],
)
def test_required_provenance_and_value_guards(field: str, value: object, reason: str) -> None:
    adapter = NewYorkFedEffrAdapter()
    observation, row = _case(adapter)
    row[field] = value
    request = _request(adapter, observation, observation)
    with pytest.raises(RateSourceError, match=reason):
        adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row])))


def test_schema_change_and_out_of_interval_are_rejected() -> None:
    adapter = RbaCashRateAdapter()
    observation, row = _case(adapter)
    request = _request(adapter, observation, observation)
    changed = dict(row, unexpectedField="schema drift")
    with pytest.raises(RateSourceError, match="SOURCE_ROW_SCHEMA_CHANGED"):
        adapter.parse_snapshot(_snapshot(request, _payload(adapter, [changed])))
    row["observationDate"] = "2016-05-03"
    with pytest.raises(RateSourceError, match="OUTSIDE_AUTHORIZED"):
        adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row])))


def test_identical_duplicate_is_idempotent_but_conflict_is_rejected() -> None:
    adapter = BankOfEnglandSoniaAdapter()
    observation, row = _case(adapter)
    request = _request(adapter, observation, observation)
    identical = adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row, row])))
    assert len(identical) == 1
    conflict = dict(row, value="9.99")
    with pytest.raises(RateSourceError, match="DUPLICATE_CONFLICTING"):
        adapter.parse_snapshot(_snapshot(request, _payload(adapter, [row, conflict])))


def test_boj_provisional_and_non_1800_saron_are_prohibited() -> None:
    boj = BankOfJapanCallRateAdapter()
    observation, row = _case(boj)
    row["resultType"] = "PROVISIONAL"
    request = _request(boj, observation, observation)
    with pytest.raises(RateSourceError, match="PROVISIONAL"):
        boj.parse_snapshot(_snapshot(request, _payload(boj, [row])))

    saron = Saron18Adapter()
    observation, row = _case(saron)
    row["fixingLabel"] = "16:00"
    request = _request(saron, observation, observation)
    with pytest.raises(RateSourceError, match="INTRADAY_SARON"):
        saron.parse_snapshot(_snapshot(request, _payload(saron, [row])))


def test_nzd_quarantined_years_and_unofficial_hosts_fail_closed() -> None:
    with pytest.raises(RateSourceError, match="NZD"):
        RateAccessAuthorization(
            "bad",
            frozenset({"x"}),
            frozenset({"NZD"}),
            frozenset({"x"}),
            date(2016, 1, 1),
            date(2016, 1, 2),
            frozenset({"example.test"}),
        )
    with pytest.raises(RateSourceError, match="QUARANTINED"):
        OfficialRateRequest(
            "x",
            "USD",
            "EFFR",
            "publisher",
            "role",
            date(2023, 1, 1),
            date(2023, 1, 2),
            "https://example.test/rates",
        )
    adapter = NewYorkFedEffrAdapter()
    authorization = _authorization(adapter, date(2016, 1, 1), date(2016, 1, 2))
    request = replace(
        _request(adapter, date(2016, 1, 1), date(2016, 1, 2)),
        url="https://example.test/rates",
    )
    with pytest.raises(RateSourceError, match="NON_OFFICIAL_HOST"):
        authorization.authorize(request)


def test_records_are_immutable_and_adapters_have_no_http_execution() -> None:
    adapter = NewYorkFedEffrAdapter()
    version = _parsed(adapter)
    with pytest.raises(FrozenInstanceError):
        version.value = 2.0  # type: ignore[misc]
    source = "\n".join(inspect.getsource(adapter_type) for adapter_type in OFFICIAL_RATE_ADAPTERS)
    assert ".get(" not in source
    assert ".post(" not in source
    assert "import httpx" not in source
    assert "import requests" not in source
