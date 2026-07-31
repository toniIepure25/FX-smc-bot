from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient
from fx_smc_bot.research.rate_sources.new_york_fed import NewYorkFedEffrAdapter


def _request_and_authorization() -> tuple[OfficialRateRequest, RateAccessAuthorization]:
    adapter = NewYorkFedEffrAdapter()
    authorization = RateAccessAuthorization(
        authorization_id="SNAPSHOT_CLIENT_TEST",
        adapter_ids=frozenset({adapter.adapter_id}),
        currencies=frozenset({adapter.currency}),
        series_ids=frozenset({adapter.series_id}),
        start=date(2016, 3, 1),
        end=date(2016, 3, 2),
        official_hosts=frozenset({"markets.newyorkfed.org"}),
    )
    request = adapter.build_requests(date(2016, 3, 1), date(2016, 3, 2), authorization)[0]
    return request, authorization


def test_snapshot_client_hashes_and_persists_idempotently(tmp_path: Path) -> None:
    request, authorization = _request_and_authorization()
    payload = b'{"schema":"test","observations":[]}'

    def handler(incoming: httpx.Request) -> httpx.Response:
        assert incoming.url.params["startDate"] == "2016-03-01"
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/json", "etag": '"frozen"'},
            request=incoming,
        )

    client = OfficialRateSnapshotClient(tmp_path, transport=httpx.MockTransport(handler))
    first = client.fetch(request, authorization)
    second = client.fetch(request, authorization)

    assert first.source_snapshot_sha256 == second.source_snapshot_sha256
    directory = tmp_path / request.adapter_id / request.request_identity
    assert (directory / f"{first.source_snapshot_sha256}.payload").read_bytes() == payload
    metadata = json.loads(
        (directory / f"{first.source_snapshot_sha256}.json").read_text(encoding="utf-8")
    )
    assert metadata["request_identity"] == request.request_identity
    assert metadata["retrieved_at"].endswith("+00:00")


@pytest.mark.parametrize("status", [302, 404, 500])
def test_snapshot_client_rejects_redirects_and_errors(tmp_path: Path, status: int) -> None:
    request, authorization = _request_and_authorization()

    def handler(incoming: httpx.Request) -> httpx.Response:
        headers = {"location": "https://example.com/rates"} if status == 302 else {}
        return httpx.Response(status, headers=headers, request=incoming)

    client = OfficialRateSnapshotClient(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(RateSourceError):
        client.fetch(request, authorization)


def test_snapshot_client_rejects_unauthorized_request_before_transport(tmp_path: Path) -> None:
    request, authorization = _request_and_authorization()
    blocked = RateAccessAuthorization(
        authorization_id="BLOCKED",
        adapter_ids=authorization.adapter_ids,
        currencies=authorization.currencies,
        series_ids=authorization.series_ids,
        start=authorization.start,
        end=authorization.end,
        official_hosts=frozenset({"www.newyorkfed.org"}),
    )
    client = OfficialRateSnapshotClient(
        tmp_path,
        transport=httpx.MockTransport(lambda incoming: httpx.Response(200, request=incoming)),
    )

    with pytest.raises(RateSourceError, match="NON_OFFICIAL_HOST"):
        client.fetch(request, blocked)
