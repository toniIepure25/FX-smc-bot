from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidenceKind,
    RevisionStatus,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.ecb import (
    BRUSSELS_ZONE,
    ECB_SDMX_CSV_INSPECTOR_ID,
    EONIA_V3_KEY,
    EONIA_V3_SCHEMA_FINGERPRINT,
    ESTR_V3_KEY,
    ESTR_V3_SCHEMA_FINGERPRINT,
    EcbEoniaEstrAdapterV3,
)
from fx_smc_bot.research.rate_vintage_store import (
    V4_SCHEMA_VERSION,
    RateVintageIntegrityError,
    RateVintageStore,
)


def _authorization(start: date, end: date) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"SYNTHETIC_ECB_V3_{start}_{end}",
        adapter_ids=frozenset({"ECB_EONIA_ESTR_V3"}),
        currencies=frozenset({"EUR"}),
        series_ids=frozenset({"EONIA", "ESTR"}),
        start=start,
        end=end,
        official_hosts=frozenset({"data-api.ecb.europa.eu"}),
        source_allowlist_identities=frozenset({"F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"}),
    )


def _request(start: date, end: date) -> OfficialRateRequest:
    adapter = EcbEoniaEstrAdapterV3()
    requests = adapter.build_requests(start, end, _authorization(start, end))
    assert len(requests) == 1
    return requests[0]


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


def _eonia_csv(*, key: str = EONIA_V3_KEY, day: str = "2016-01-04") -> str:
    return (
        "KEY,FREQ,EONIA_BANK,EONIA_ITEM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,"
        "OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,BREAKS,COLLECTION,COMPILING_ORG,DISS_ORG,"
        "PUBL_ECB,PUBL_MU,PUBL_PUBLIC,COMPILATION,DECIMALS,SOURCE_AGENCY,TITLE,"
        "TITLE_COMPL,UNIT,UNIT_MULT\n"
        f"{key},D,EONIA_TO,RATE,{day},1.25,A,,,,P1D,,A,,,,,,3,,title,,PC,0\n"
    )


def _estr_csv(*, key: str = ESTR_V3_KEY, day: str = "2019-10-01") -> str:
    return (
        "KEY,FREQ,BENCHMARK_ITEM,DATA_TYPE_EST,TIME_PERIOD,OBS_VALUE,OBS_STATUS,"
        "CONF_STATUS,PRE_BREAK_VALUE,COMMENT_OBS,CALCUL_START_DATE,CALCUL_END_DATE,"
        "TIME_FORMAT,BREAKS,COMMENT_TS,COMPILING_ORG,COVERAGE,DATA_COMP,DECIMALS,"
        "DISS_ORG,PUBL_ECB,PUBL_MU,PUBL_PUBLIC,TIME_PER_COLLECT,TITLE,TITLE_COMPL,"
        "UNIT_INDEX_BASE,UNIT_MEASURE,UNIT_MULT\n"
        f"{key},B,EU000A2X2A25,WT,{day},1.50,A,F,,,,,P1D,,,,,,3,,,,,A,title,,,"
        "PC,0\n"
    )


def test_v3_builds_corrected_bounded_eonia_and_estr_requests() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    requests = adapter.build_requests(
        date(2019, 9, 30),
        date(2019, 10, 1),
        _authorization(date(2019, 9, 30), date(2019, 10, 1)),
    )

    assert [request.series_id for request in requests] == ["EONIA", "ESTR"]
    assert requests[0].url.endswith("/EON/D.EONIA_TO.RATE")
    assert requests[1].url.endswith("/EST/B.EU000A2X2A25.WT")
    assert all(dict(request.query_parameters)["format"] == "csvdata" for request in requests)
    assert "B.EU000A2X2A25.WT" not in requests[0].url


def test_eonia_exact_publication_rule_and_decimal_normalization() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    version = adapter.parse_snapshot(_snapshot(request, _eonia_csv()))[0]

    assert version.series_id == "EONIA"
    assert version.value == pytest.approx(0.0125)
    assert version.schema_fingerprint == EONIA_V3_SCHEMA_FINGERPRINT
    assert version.publication_timestamp == datetime(
        2016, 1, 4, 19, 0, tzinfo=BRUSSELS_ZONE
    )
    assert version.publication_evidence_kind == PublicationEvidenceKind.EXACT_TIMESTAMP.value
    assert version.strategy_availability_timestamp == version.publication_timestamp
    assert version.revision_identifier is None
    assert version.revision_status == (
        RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
    )
    assert adapter.certify_version(version).status == "PASS"


def test_estr_bounded_publication_rule_and_revision_semantics() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    request = _request(date(2019, 10, 1), date(2019, 10, 1))
    version = adapter.parse_snapshot(_snapshot(request, _estr_csv()))[0]

    assert version.series_id == "ESTR"
    assert version.value == pytest.approx(0.015)
    assert version.schema_fingerprint == ESTR_V3_SCHEMA_FINGERPRINT
    assert version.publication_timestamp is None
    assert version.publication_lower_bound == datetime(
        2019, 10, 2, 8, 0, tzinfo=BRUSSELS_ZONE
    )
    assert version.publication_upper_bound == datetime(
        2019, 10, 2, 9, 0, tzinfo=BRUSSELS_ZONE
    )
    assert version.publication_evidence_kind == (
        PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value
    )
    assert version.strategy_availability_timestamp == version.publication_upper_bound
    assert version.revision_identifier is None
    assert adapter.certify_version(version).status == "PASS"


def test_target2_holiday_and_dst_boundaries_are_timezone_aware() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    holiday_request = _request(date(2019, 12, 24), date(2019, 12, 24))
    holiday_version = adapter.parse_snapshot(
        _snapshot(holiday_request, _estr_csv(day="2019-12-24"))
    )[0]

    assert holiday_version.publication_upper_bound == datetime(
        2019, 12, 27, 9, 0, tzinfo=BRUSSELS_ZONE
    )

    divergence_request = _request(date(2016, 3, 14), date(2016, 3, 14))
    divergence_version = adapter.parse_snapshot(
        _snapshot(divergence_request, _eonia_csv(day="2016-03-14"))
    )[0]

    assert divergence_version.publication_timestamp is not None
    assert divergence_version.publication_timestamp.astimezone(NEW_YORK_ZONE).hour == 14


def test_new_york_1705_execution_is_after_eur_availability_boundaries() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    versions = (
        adapter.parse_snapshot(
            _snapshot(
                _request(date(2016, 1, 4), date(2016, 1, 4)),
                _eonia_csv(),
            )
        )[0],
        adapter.parse_snapshot(
            _snapshot(
                _request(date(2019, 10, 1), date(2019, 10, 1)),
                _estr_csv(),
            )
        )[0],
    )

    for version in versions:
        availability_ny = version.strategy_availability_timestamp.astimezone(
            NEW_YORK_ZONE
        )
        execution_ny = datetime.combine(
            availability_ny.date(), datetime.min.time().replace(hour=17, minute=5)
        ).replace(tzinfo=ZoneInfo("America/New_York"))

        assert execution_ny > availability_ny


def test_transition_boundaries_reject_overlap_gap_and_wrong_identity() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    eonia_request = _request(date(2019, 9, 30), date(2019, 9, 30))
    estr_request = _request(date(2019, 10, 1), date(2019, 10, 1))

    assert adapter.parse_snapshot(_snapshot(eonia_request, _eonia_csv(day="2019-09-30")))
    assert adapter.parse_snapshot(_snapshot(estr_request, _estr_csv(day="2019-10-01")))

    with pytest.raises(RateSourceError, match="OUTSIDE_REQUEST_BOUNDS"):
        adapter.parse_snapshot(_snapshot(eonia_request, _eonia_csv(day="2019-10-01")))
    with pytest.raises(RateSourceError, match="OUTSIDE_REQUEST_BOUNDS"):
        adapter.parse_snapshot(_snapshot(estr_request, _estr_csv(day="2019-09-30")))
    with pytest.raises(RateSourceError, match="KEY_MISMATCH"):
        adapter.parse_snapshot(_snapshot(eonia_request, _eonia_csv(key=ESTR_V3_KEY)))


def test_wrong_dataflow_header_and_mixed_out_of_range_response_rejected() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 5))
    wrong_header = _eonia_csv().replace("OBS_CONF", "OBS_CONF_WRONG", 1)
    mixed_scope = (
        _eonia_csv(day="2016-01-04").strip()
        + "\n"
        + _eonia_csv(day="2016-01-08").splitlines()[1]
        + "\n"
    )
    with pytest.raises(RateSourceError, match="ECB_SDMX_CSV_SCHEMA_CHANGED"):
        adapter.parse_snapshot(_snapshot(request, wrong_header))
    with pytest.raises(RateSourceError, match="OUTSIDE_REQUEST_BOUNDS"):
        adapter.parse_snapshot(_snapshot(request, mixed_scope))
    with pytest.raises(RateSourceError, match="REQUEST_ENDPOINT_DECLARATION_MISMATCH"):
        replace(
            request,
            url="https://data-api.ecb.europa.eu/service/data/EST/D.EONIA_TO.RATE",
        )


def test_sdmx_shape_certification_is_bound_to_v4_store(tmp_path: Path) -> None:
    adapter = EcbEoniaEstrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, _eonia_csv())
    certification = adapter.certify_snapshot_shape(snapshot)

    assert certification.inspector_id == ECB_SDMX_CSV_INSPECTOR_ID
    assert certification.row_container_path == "$.sdmx_csv_rows"
    with RateVintageStore(
        tmp_path / "eur-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store:
        store.append_source_snapshot(snapshot, firewall_certification=certification)

    tampered = replace(certification, row_count=certification.row_count + 1)
    with RateVintageStore(
        tmp_path / "eur-v4-tampered.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store, pytest.raises(RateVintageIntegrityError, match="complete snapshot payload"):
        store.append_source_snapshot(snapshot, firewall_certification=tampered)


def test_conflicting_duplicate_rows_fail_closed() -> None:
    adapter = EcbEoniaEstrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    text = _eonia_csv().strip() + "\n" + _eonia_csv().splitlines()[1].replace("1.25", "1.26") + "\n"

    with pytest.raises(RateSourceError, match="CONFLICTING_FINAL_HISTORY_ECB_ROWS"):
        adapter.parse_snapshot(_snapshot(request, text))
