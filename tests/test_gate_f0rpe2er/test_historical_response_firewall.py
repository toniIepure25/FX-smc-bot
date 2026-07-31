from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from fx_smc_bot.research.historical_response_firewall import (
    AUTHORIZED_CURRENCIES,
    AUTHORIZED_INSTRUMENTS,
    FIREWALL_ID,
    SOURCE_RESPONSE_SCOPE_VIOLATION,
    HistoricalResponseContract,
    HistoricalResponseFirewall,
    HistoricalResponseFirewallError,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient

FIELDS = frozenset({"currency", "seriesId", "observationDate", "revisionLabel"})


def _contract() -> HistoricalResponseContract:
    return HistoricalResponseContract(
        adapter_id="OFFICIAL_TEST_V2",
        currency="USD",
        series_ids=frozenset({"AUTHORIZED_SERIES"}),
        schema_id="official-test-schema-v2",
        required_row_fields=FIELDS,
        allowlist_identity="F0RPE2ER_TEST_OFFICIAL_V2",
        endpoint_url="https://official.example.test/rates",
        minimum_authorized_date=date(2010, 1, 1),
        maximum_authorized_date=date(2022, 12, 31),
    )


def _request(
    *,
    start: date = date(2022, 12, 31),
    end: date = date(2022, 12, 31),
) -> OfficialRateRequest:
    return OfficialRateRequest(
        adapter_id="OFFICIAL_TEST_V2",
        currency="USD",
        series_id="AUTHORIZED_SERIES",
        source_publisher="Official Publisher",
        source_endpoint_role="BOUNDED_HISTORICAL_DATA",
        start=start,
        end=end,
        url="https://official.example.test/rates",
        query_parameters=tuple(
            sorted(
                {
                    "currency": "USD",
                    "endDate": end.isoformat(),
                    "format": "json",
                    "series": "AUTHORIZED_SERIES",
                    "startDate": start.isoformat(),
                }.items()
            )
        ),
    )


def _scope_row(label: str, *, revision: str = "ORIGINAL") -> dict[str, str]:
    return {
        "currency": "USD",
        "seriesId": "AUTHORIZED_SERIES",
        "observationDate": label,
        "revisionLabel": revision,
    }


def _document(*rows: dict[str, str]) -> dict[str, object]:
    return {"schema": "official-test-schema-v2", "observations": list(rows)}


@dataclass(frozen=True)
class _SyntheticEndpointDeclaration:
    allowlist_identity: str = "F0RPE2ER_TEST_OFFICIAL_V2"
    firewall_id: str = FIREWALL_ID
    declaration_sha256: str = "a" * 64
    schema_fingerprint: str = "b" * 64
    retry_policy: None = None

    def validate_request(self, _: OfficialRateRequest) -> None:
        return None


def _transport_request() -> OfficialRateRequest:
    return replace(
        _request(),
        endpoint_declaration=cast(Any, _SyntheticEndpointDeclaration()),
    )


def _transport_authorization(request: OfficialRateRequest) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id="F0RPE2ER_FIREWALL_INTEGRATION_TEST",
        adapter_ids=frozenset({request.adapter_id}),
        currencies=frozenset({request.currency}),
        series_ids=frozenset({request.series_id}),
        start=request.start,
        end=request.end,
        official_hosts=frozenset({"official.example.test"}),
        source_allowlist_identities=frozenset({"F0RPE2ER_TEST_OFFICIAL_V2"}),
    )


def test_authorized_universes_are_exact_and_exclude_nzd() -> None:
    assert AUTHORIZED_CURRENCIES == {"USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"}
    assert AUTHORIZED_INSTRUMENTS == {
        "EURUSD",
        "GBPUSD",
        "AUDUSD",
        "USDJPY",
        "USDCAD",
        "USDCHF",
        "EURJPY",
        "GBPJPY",
        "AUDJPY",
    }
    assert "NZD" not in AUTHORIZED_CURRENCIES
    assert "NZDUSD" not in AUTHORIZED_INSTRUMENTS


def test_2022_12_31_scope_label_is_accepted() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request(), instruments=AUTHORIZED_INSTRUMENTS)

    result = firewall.validate_response(approved, _document(_scope_row("2022-12-31")))

    assert len(result.rows) == 1
    assert result.schema_id == _contract().schema_id
    assert firewall.certified_response_count == 1
    assert firewall.violations == ()


@pytest.mark.parametrize("scope_label", ["2023-01-01", "2024-01-01", "2025-01-01"])
def test_quarantined_year_scope_labels_are_rejected(scope_label: str) -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())

    with pytest.raises(HistoricalResponseFirewallError, match=SOURCE_RESPONSE_SCOPE_VIOLATION):
        firewall.validate_scope_label(approved, scope_label)

    assert firewall.violations[-1].offending_date_label == scope_label
    assert firewall.certified_response_count == 0


def test_mixed_2022_and_2025_scope_response_is_rejected_atomically() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())

    with pytest.raises(HistoricalResponseFirewallError, match=SOURCE_RESPONSE_SCOPE_VIOLATION):
        firewall.validate_response(
            approved,
            _document(_scope_row("2022-12-31"), _scope_row("2025-01-01")),
        )

    assert firewall.certified_response_count == 0
    assert firewall.quarantined_response_count == 1
    assert len(firewall.violations) == 1


def test_nzd_contract_and_nzdusd_instrument_are_rejected() -> None:
    with pytest.raises(RateSourceError, match="NZD"):
        replace(_contract(), currency="NZD")

    firewall = HistoricalResponseFirewall(_contract())
    with pytest.raises(RateSourceError, match="NZDUSD"):
        firewall.validate_instrument_scope(("NZDUSD",))


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("seriesId", "WRONG_SERIES", "SOURCE_RESPONSE_SERIES_MISMATCH"),
        ("currency", "CAD", "SOURCE_RESPONSE_CURRENCY_MISMATCH"),
    ],
)
def test_wrong_declared_identity_is_rejected(
    field: str, replacement: str, reason: str
) -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())
    row = _scope_row("2022-12-31")
    row[field] = replacement

    with pytest.raises(HistoricalResponseFirewallError, match=reason):
        firewall.validate_response(approved, _document(row))


def test_wrong_schema_and_malformed_date_are_rejected() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())

    with pytest.raises(HistoricalResponseFirewallError, match="SCHEMA"):
        firewall.validate_response(
            approved, {"schema": "wrong-schema", "observations": []}
        )
    with pytest.raises(HistoricalResponseFirewallError, match="DATE_MALFORMED"):
        firewall.validate_response(approved, _document(_scope_row("invalid-date-label")))


def test_conflicting_duplicate_is_rejected_without_recording_row_values() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())

    with pytest.raises(HistoricalResponseFirewallError, match="DUPLICATE_CONFLICT"):
        firewall.validate_response(
            approved,
            _document(
                _scope_row("2022-12-31", revision="ORIGINAL"),
                _scope_row("2022-12-31", revision="CORRECTED"),
            ),
        )

    record = firewall.violations[-1]
    serialized = repr(record)
    assert "ORIGINAL" not in serialized
    assert "CORRECTED" not in serialized
    assert record.field_names == ()


def test_identical_duplicate_scope_label_is_idempotent() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())
    row = _scope_row("2022-12-31")

    result = firewall.validate_response(approved, _document(row, dict(row)))

    assert len(result.rows) == 1


def test_unbounded_request_is_rejected_before_operation() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    request = _request()
    unbounded = replace(
        request,
        query_parameters=tuple(
            item for item in request.query_parameters if item[0] not in {"startDate", "endDate"}
        ),
    )
    operation_calls = 0

    def operation(_: OfficialRateRequest) -> object:
        nonlocal operation_calls
        operation_calls += 1
        return object()

    with pytest.raises(HistoricalResponseFirewallError, match="SERVER_DATE_BOUNDS_REQUIRED"):
        firewall.execute_after_preflight(unbounded, operation)

    assert operation_calls == 0
    assert firewall.violations[-1].stage == "REQUEST_PREFLIGHT"


def test_explicit_request_series_currency_and_format_are_required() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    request = _request()

    for parameter in ("series", "currency", "format"):
        changed = replace(
            request,
            query_parameters=tuple(
                item for item in request.query_parameters if item[0] != parameter
            ),
        )
        with pytest.raises(
            HistoricalResponseFirewallError, match="EXPLICIT_DECLARATION_MISMATCH"
        ):
            firewall.preflight(changed)


def test_preflight_accepts_earliest_historical_boundary() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    request = _request(start=date(2010, 1, 1), end=date(2010, 1, 1))

    approved = firewall.preflight(request)

    assert approved.request.start == date(2010, 1, 1)
    assert approved.request.end == date(2010, 1, 1)


def test_request_before_historical_boundary_is_rejected() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    request = _request(start=date(2009, 12, 31), end=date(2010, 1, 1))

    with pytest.raises(HistoricalResponseFirewallError, match="HISTORICAL_SCOPE_VIOLATION"):
        firewall.preflight(request)


def test_allowlist_specific_date_bound_is_enforced() -> None:
    contract = replace(_contract(), maximum_authorized_date=date(2019, 9, 30))
    firewall = HistoricalResponseFirewall(contract)

    with pytest.raises(HistoricalResponseFirewallError, match="HISTORICAL_SCOPE_VIOLATION"):
        firewall.preflight(_request())


def test_allowlist_cannot_authorize_dates_after_global_boundary() -> None:
    with pytest.raises(RateSourceError, match="ALLOWLIST_DATE_BOUNDS_NOT_AUTHORIZED"):
        replace(_contract(), maximum_authorized_date=date(2023, 1, 1))


def test_response_fields_must_match_contract_exactly() -> None:
    firewall = HistoricalResponseFirewall(_contract())
    approved = firewall.preflight(_request())
    row = _scope_row("2022-12-31")
    row["unexpected"] = "metadata"

    with pytest.raises(HistoricalResponseFirewallError, match="SCHEMA"):
        firewall.validate_response(approved, _document(row))

    assert firewall.violations[-1].field_names == tuple(sorted(row))


def test_client_never_calls_transport_when_firewall_rejects_request(tmp_path: Path) -> None:
    request = _transport_request()
    authorization = _transport_authorization(request)
    firewall = HistoricalResponseFirewall(
        replace(_contract(), maximum_authorized_date=date(2019, 9, 30))
    )
    transport_calls = 0

    def handler(incoming: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(200, request=incoming)

    client = OfficialRateSnapshotClient(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(HistoricalResponseFirewallError, match="HISTORICAL_SCOPE_VIOLATION"):
        client.fetch(request, authorization, response_firewall=firewall)

    assert transport_calls == 0
    assert list(tmp_path.rglob("*.payload")) == []


def test_client_never_returns_or_persists_snapshot_with_bad_scope(tmp_path: Path) -> None:
    request = _transport_request()
    authorization = _transport_authorization(request)
    firewall = HistoricalResponseFirewall(_contract())
    payload = json.dumps(
        _document(_scope_row("2022-12-31"), _scope_row("2025-01-01")),
        sort_keys=True,
    ).encode("ascii")
    transport_calls = 0

    def handler(incoming: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/json"},
            request=incoming,
        )

    client = OfficialRateSnapshotClient(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(HistoricalResponseFirewallError, match=SOURCE_RESPONSE_SCOPE_VIOLATION):
        client.fetch(request, authorization, response_firewall=firewall)

    assert transport_calls == 1
    assert firewall.certified_snapshot_sha256s == frozenset()
    assert firewall.certified_response_count == 0
    assert firewall.quarantined_response_count == 1
    assert list(tmp_path.rglob("*.payload")) == []
    assert list(tmp_path.rglob("*.json")) == []
