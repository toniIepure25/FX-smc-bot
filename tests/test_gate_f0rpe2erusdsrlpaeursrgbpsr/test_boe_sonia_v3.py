from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidenceKind,
    RevisionStatus,
)
from fx_smc_bot.research.rate_sources.bank_of_england import (
    BOE_IADB_CSV_INSPECTOR_ID,
    BOE_IADB_RESEARCH_USER_AGENT,
    BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT,
    SONIA_FINAL_LEGACY_OBSERVATION,
    SONIA_REFORM_START,
    BankOfEnglandSoniaAdapterV3,
    legacy_sonia_publication_evidence,
    reformed_sonia_publication_evidence,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_vintage_store import (
    V4_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageIntegrityError,
    RateVintageStore,
)


def _authorization(start: date, end: date) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"SYNTHETIC_BOE_V3_{start}_{end}",
        adapter_ids=frozenset({"BOE_SONIA_V3"}),
        currencies=frozenset({"GBP"}),
        series_ids=frozenset({"IUDSOIA"}),
        start=start,
        end=end,
        official_hosts=frozenset({"www.bankofengland.co.uk"}),
        source_allowlist_identities=frozenset(
            {"F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"}
        ),
    )


def _request(start: date, end: date) -> OfficialRateRequest:
    adapter = BankOfEnglandSoniaAdapterV3()
    return adapter.build_requests(start, end, _authorization(start, end))[0]


def _csv(*rows: tuple[str, str]) -> str:
    body = "".join(f"{day},{value}\n" for day, value in rows)
    return "DATE,IUDSOIA\n" + body


def _snapshot(request: OfficialRateRequest, text: str) -> SourceSnapshot:
    payload = text.encode("utf-8")
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type="text/csv",
        response_headers=(("content-type", "text/csv"),),
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_v3_builds_documented_bounded_csv_request() -> None:
    request = _request(date(2018, 4, 23), date(2018, 4, 27))
    parameters = dict(request.query_parameters)
    headers = dict(request.request_headers)

    assert request.adapter_id == "BOE_SONIA_V3"
    assert request.series_id == "IUDSOIA"
    assert parameters["csv.x"] == "yes"
    assert parameters["CSVF"] == "TN"
    assert parameters["UsingCodes"] == "Y"
    assert parameters["VPD"] == "N"
    assert parameters["VFD"] == "Y"
    assert headers == {
        "Accept": "text/csv",
        "User-Agent": BOE_IADB_RESEARCH_USER_AGENT,
    }
    assert "Mozilla/" not in headers["User-Agent"]


def test_csvf_tn_is_tabular_and_xml_fallback_requires_csv_failure() -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    start = date(2018, 4, 23)
    end = date(2018, 4, 27)

    assert adapter.endpoint_declarations[0].response_format == "CSV_TABULAR_NO_TITLES"
    assert adapter.build_fallback_requests_after_csv_failure(
        start, end, _authorization(start, end), "SCHEMA_NOT_ATTEMPTED"
    ) == ()

    fallback = adapter.build_fallback_requests_after_csv_failure(
        start, end, _authorization(start, end), "OFFICIAL_ENDPOINT_HTTP_STATUS_403"
    )[0]
    assert fallback.endpoint_declaration is not None
    assert fallback.endpoint_declaration.response_format == "XML_IADB"
    assert dict(fallback.query_parameters)["xml.x"] == "yes"
    assert dict(fallback.query_parameters)["CodeVer"] == "new"
    assert dict(fallback.request_headers)["Accept"] == "application/xml"


def test_legacy_publication_envelope_and_first_eligible_execution() -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 20), date(2018, 4, 20))
    version = adapter.parse_snapshot(_snapshot(request, _csv(("20 Apr 2018", "0.46"))))[0]

    assert version.observation_date == SONIA_FINAL_LEGACY_OBSERVATION
    assert version.value == pytest.approx(0.0046)
    assert version.publication_timestamp is None
    assert version.publication_evidence_kind == (
        PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value
    )
    assert version.publication_lower_bound == datetime(
        2018, 4, 20, 18, 0, tzinfo=version.resolved_publication_lower_bound.tzinfo
    )
    assert version.publication_upper_bound_exclusive is True
    assert version.strategy_availability_timestamp == datetime(
        2018, 4, 23, 17, 5, tzinfo=NEW_YORK_ZONE
    )
    assert version.revision_identifier is None
    assert version.revision_status == (
        RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
    )
    assert adapter.certify_version(version).status == "PASS"


def test_reformed_publication_bounds_are_unavailable_before_noon_and_available_after(
    tmp_path: Path,
) -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 23), date(2018, 4, 23))
    snapshot = _snapshot(request, _csv(("23 Apr 2018", "0.46")))
    shape = adapter.certify_snapshot_shape(snapshot)
    version = adapter.parse_snapshot(snapshot)[0]

    assert version.observation_date == SONIA_REFORM_START
    assert version.publication_timestamp is None
    assert version.publication_lower_bound == datetime(
        2018, 4, 24, 9, 0, tzinfo=version.resolved_publication_lower_bound.tzinfo
    )
    assert version.publication_upper_bound == datetime(
        2018, 4, 24, 12, 0, tzinfo=version.resolved_publication_upper_bound.tzinfo
    )
    assert version.publication_evidence_kind == (
        PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value
    )
    assert version.strategy_availability_timestamp == version.publication_upper_bound
    assert adapter.certify_version(version).status == "PASS"

    with RateVintageStore(
        tmp_path / "gbp-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store:
        store.append_source_snapshot(snapshot, firewall_certification=shape)
        version_id = store.append_rate_version(version)
        store.append_certification(
            version_id,
            status="PASS",
            certified_at=datetime(2026, 8, 1, 13, tzinfo=UTC),
        )
        freeze = store.create_dataset_freeze(
            "SYNTHETIC_BOE_SONIA_V3_FREEZE",
            [version_id],
            created_at=datetime(2026, 8, 1, 14, tzinfo=UTC),
        )
        before = store.get_rate_as_of(
            "GBP",
            version.strategy_availability_timestamp - timedelta(seconds=1),
            freeze.dataset_freeze_id,
        )
        at = store.get_rate_as_of(
            "GBP",
            version.strategy_availability_timestamp,
            freeze.dataset_freeze_id,
        )

    assert isinstance(before, MissingRate)
    assert isinstance(at, AvailableRate)
    assert at.schema_fingerprint == BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT


def test_london_holiday_and_uk_us_dst_divergence_are_timezone_aware() -> None:
    holiday = reformed_sonia_publication_evidence(date(2018, 5, 4))
    assert holiday.publication_upper_bound == datetime(
        2018, 5, 8, 12, 0, tzinfo=holiday.publication_upper_bound.tzinfo
    )

    uk_gmt_us_dst = legacy_sonia_publication_evidence(date(2018, 3, 19))
    uk_bst_us_dst = legacy_sonia_publication_evidence(date(2018, 3, 26))
    assert uk_gmt_us_dst.publication_lower_bound.astimezone(NEW_YORK_ZONE).hour == 14
    assert uk_bst_us_dst.publication_lower_bound.astimezone(NEW_YORK_ZONE).hour == 13


def test_transition_weekend_has_no_synthetic_observations() -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 20), date(2018, 4, 23))

    assert adapter.parse_snapshot(
        _snapshot(request, _csv(("20 Apr 2018", "0.46"), ("23 Apr 2018", "0.46")))
    )
    with pytest.raises(RateSourceError, match="NON_BUSINESS_DAY_OBSERVATION"):
        adapter.parse_snapshot(_snapshot(request, _csv(("21 Apr 2018", "0.46"))))


def test_wrong_series_out_of_range_mixed_scope_and_unknown_schema_rejected() -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 23), date(2018, 4, 24))

    with pytest.raises(RateSourceError, match="REQUEST_ENDPOINT_DECLARATION_MISMATCH"):
        replace(request, series_id="BADSONIA")

    with pytest.raises(RateSourceError, match="OUTSIDE_REQUEST_BOUNDS"):
        adapter.parse_snapshot(_snapshot(request, _csv(("25 Apr 2018", "0.46"))))
    with pytest.raises(RateSourceError, match="OUTSIDE_REQUEST_BOUNDS"):
        adapter.parse_snapshot(
            _snapshot(request, _csv(("23 Apr 2018", "0.46"), ("25 Apr 2018", "0.46")))
        )
    with pytest.raises(RateSourceError, match="CSV_SCHEMA_CHANGED"):
        adapter.parse_snapshot(
            _snapshot(request, "DATE,IUDSOIA,EXTRA_NUMERICAL_SERIES\n23 Apr 2018,0.46,1.00\n")
        )


def test_unknown_schema_fingerprint_and_conflicting_duplicates_fail_closed() -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 23), date(2018, 4, 23))
    snapshot = _snapshot(request, _csv(("23 Apr 2018", "0.46")))
    row = {"DATE": "23 Apr 2018", "IUDSOIA": "0.46"}

    with pytest.raises(RateSourceError, match="UNKNOWN_BOE_IADB_SCHEMA_FINGERPRINT"):
        adapter._version_from_csv_row(
            snapshot,
            row,
            source_row_ordinal=0,
            schema_fingerprint="0" * 64,
        )
    with pytest.raises(RateSourceError, match="CONFLICTING_FINAL_HISTORY_SONIA_ROWS"):
        adapter.parse_snapshot(
            _snapshot(request, _csv(("23 Apr 2018", "0.46"), ("23 Apr 2018", "0.47")))
        )


def test_v4_shape_certification_recomputes_complete_boe_payload(tmp_path: Path) -> None:
    adapter = BankOfEnglandSoniaAdapterV3()
    request = _request(date(2018, 4, 23), date(2018, 4, 23))
    snapshot = _snapshot(request, _csv(("23 Apr 2018", "0.46")))
    shape = adapter.certify_snapshot_shape(snapshot)

    assert shape.inspector_id == BOE_IADB_CSV_INSPECTOR_ID
    assert shape.row_container_path == "$.iadb_tabular_csv_rows"
    with RateVintageStore(
        tmp_path / "gbp-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store:
        store.append_source_snapshot(snapshot, firewall_certification=shape)

    tampered = replace(shape, row_count=shape.row_count + 1)
    with RateVintageStore(
        tmp_path / "gbp-v4-tampered.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store, pytest.raises(RateVintageIntegrityError, match="complete snapshot payload"):
        store.append_source_snapshot(snapshot, firewall_certification=tampered)
