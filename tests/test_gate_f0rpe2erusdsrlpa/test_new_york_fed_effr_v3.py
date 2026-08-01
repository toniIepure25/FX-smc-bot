from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
from fx_smc_bot.research.rate_sources.new_york_fed import (
    LEGACY_SCHEMA_FINGERPRINT,
    MODERN_SCHEMA_FINGERPRINT,
    NewYorkFedEffrAdapterV3,
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
        authorization_id=f"SYNTHETIC_EFFR_V3_{start}_{end}",
        adapter_ids=frozenset({"NY_FED_EFFR_V3"}),
        currencies=frozenset({"USD"}),
        series_ids=frozenset({"EFFR"}),
        start=start,
        end=end,
        official_hosts=frozenset({"markets.newyorkfed.org"}),
        source_allowlist_identities=frozenset(
            {"F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"}
        ),
    )


def _request(start: date, end: date) -> OfficialRateRequest:
    adapter = NewYorkFedEffrAdapterV3()
    return adapter.build_requests(start, end, _authorization(start, end))[0]


def _legacy_row(*, percent_rate: float = 0.37) -> dict[str, object]:
    return {
        "effectiveDate": "2016-01-04",
        "intraDayHigh": 0.4,
        "intraDayLow": 0.3,
        "percentRate": percent_rate,
        "revisionIndicator": "",
        "stdDeviation": 0.01,
        "targetRateFrom": 0.25,
        "targetRateTo": 0.5,
        "type": "EFFR",
    }


def _modern_rows() -> list[dict[str, object]]:
    common = {
        "effectiveDate": "2016-03-01",
        "percentPercentile1": 0.2,
        "percentPercentile25": 0.3,
        "percentPercentile75": 0.4,
        "percentPercentile99": 0.5,
        "percentRate": 0.36,
        "revisionIndicator": "",
    }
    return [
        {
            **common,
            "targetRateFrom": 0.25,
            "targetRateTo": 0.5,
            "type": "EFFR",
        },
        {**common, "percentRate": 0.35, "type": "OBFR"},
    ]


def _snapshot(
    request: OfficialRateRequest,
    rows: list[dict[str, object]],
) -> SourceSnapshot:
    payload = json.dumps(
        {"refRates": rows},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type="application/json",
        response_headers=(("content-type", "application/json"),),
        retrieved_at=datetime(2026, 7, 31, 12, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_v3_splits_requests_at_frozen_schema_boundary() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    start = date(2016, 2, 29)
    end = date(2016, 3, 1)

    requests = adapter.build_requests(start, end, _authorization(start, end))

    assert [(request.start, request.end) for request in requests] == [
        (date(2016, 2, 29), date(2016, 2, 29)),
        (date(2016, 3, 1), date(2016, 3, 1)),
    ]


def test_legacy_schema_normalizes_with_no_actual_publication_timestamp() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, [_legacy_row()])

    shape = adapter.certify_snapshot_shape(snapshot)
    versions = adapter.parse_snapshot(snapshot)

    assert shape.schema_fingerprint == LEGACY_SCHEMA_FINGERPRINT
    assert len(versions) == 1
    version = versions[0]
    assert version.value == pytest.approx(0.0037)
    assert version.publication_timestamp is None
    assert version.publication_evidence_kind == (
        PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value
    )
    assert version.publication_lower_bound == datetime(
        2016, 1, 5, tzinfo=NEW_YORK_ZONE
    )
    assert version.publication_upper_bound == datetime(
        2016, 1, 6, tzinfo=NEW_YORK_ZONE
    )
    assert version.strategy_availability_timestamp == datetime(
        2016, 1, 6, 17, 5, tzinfo=NEW_YORK_ZONE
    )
    assert version.revision_identifier is None
    assert version.revision_status == (
        RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
    )
    assert adapter.certify_version(version).status == "PASS"


def test_modern_schema_excludes_obfr_and_uses_revision_complete_boundary() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 3, 1), date(2016, 3, 1))
    snapshot = _snapshot(request, _modern_rows())

    shape = adapter.certify_snapshot_shape(snapshot)
    versions = adapter.parse_snapshot(snapshot)

    assert shape.schema_fingerprint == MODERN_SCHEMA_FINGERPRINT
    assert len(versions) == 1
    version = versions[0]
    assert version.value == pytest.approx(0.0036)
    assert version.publication_timestamp is None
    assert version.publication_upper_bound == datetime(
        2016, 3, 2, 14, 30, tzinfo=NEW_YORK_ZONE
    )
    assert version.strategy_availability_timestamp == datetime(
        2016, 3, 2, 17, 5, tzinfo=NEW_YORK_ZONE
    )
    assert adapter.certify_version(version).status == "PASS"


def test_unknown_fingerprint_and_third_series_fail_closed() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    legacy_request = _request(date(2016, 1, 4), date(2016, 1, 4))
    changed = _legacy_row()
    changed["unexpectedField"] = 1.0
    with pytest.raises(RateSourceError, match="UNKNOWN_EFFR_SCHEMA_FINGERPRINT"):
        adapter.parse_snapshot(_snapshot(legacy_request, [changed]))

    modern_request = _request(date(2016, 3, 1), date(2016, 3, 1))
    rows = _modern_rows()
    rows[1]["type"] = "THIRD_SERIES"
    with pytest.raises(RateSourceError, match="UNEXPECTED_NY_FED_SERIES_TYPE"):
        adapter.parse_snapshot(_snapshot(modern_request, rows))


def test_conflicting_final_history_duplicates_are_rejected() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    rows = [_legacy_row(), _legacy_row(percent_rate=0.38)]

    with pytest.raises(RateSourceError, match="CONFLICTING_FINAL_HISTORY_EFFR_ROWS"):
        adapter.parse_snapshot(_snapshot(request, rows))


def test_metadata_conflicting_final_history_duplicates_are_rejected() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    revised = _legacy_row()
    revised["revisionIndicator"] = "Y"

    with pytest.raises(RateSourceError, match="CONFLICTING_FINAL_HISTORY_EFFR_ROWS"):
        adapter.parse_snapshot(_snapshot(request, [_legacy_row(), revised]))


def test_three_run_parse_is_deterministic() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 3, 1), date(2016, 3, 1))
    snapshot = _snapshot(request, _modern_rows())

    first = adapter.parse_snapshot(snapshot)
    second = adapter.parse_snapshot(snapshot)
    third = adapter.parse_snapshot(snapshot)

    assert first == second == third


def test_snapshot_request_and_payload_identity_are_bound() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, [_legacy_row()])

    with pytest.raises(RateSourceError, match="SOURCE_SNAPSHOT_SHA256_MISMATCH"):
        replace(snapshot, source_snapshot_sha256="0" * 64)
    certification = adapter.certify_snapshot_shape(snapshot)
    assert certification.snapshot_sha256 == snapshot.source_snapshot_sha256
    assert certification.request_identity == request.request_identity


def test_v4_shape_certification_requires_explicit_schema_role(tmp_path: Path) -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, [_legacy_row()])
    certification = replace(adapter.certify_snapshot_shape(snapshot), schema_role="")

    with RateVintageStore(
        tmp_path / "effr-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store, pytest.raises(RateVintageIntegrityError, match="schema_role"):
        store.append_source_snapshot(snapshot, firewall_certification=certification)


def test_v4_shape_certification_is_recomputed_from_payload(tmp_path: Path) -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, [_legacy_row()])
    certification = replace(
        adapter.certify_snapshot_shape(snapshot), schema_fingerprint="0" * 64
    )

    with RateVintageStore(
        tmp_path / "effr-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store, pytest.raises(RateVintageIntegrityError, match="complete snapshot payload"):
        store.append_source_snapshot(snapshot, firewall_certification=certification)


def test_v3_certification_recomputes_frozen_availability() -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 3, 1), date(2016, 3, 1))
    version = adapter.parse_snapshot(_snapshot(request, _modern_rows()))[0]
    tampered = replace(
        version,
        strategy_availability_timestamp=version.resolved_publication_upper_bound
        + timedelta(minutes=30),
    )

    certification = adapter.certify_version(tampered)
    assert certification.passed is False
    assert "STRATEGY_AVAILABILITY_MISMATCH" in certification.reasons


def test_v3_shape_certification_versions_and_v4_asof_are_bound(tmp_path: Path) -> None:
    adapter = NewYorkFedEffrAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4))
    snapshot = _snapshot(request, [_legacy_row()])
    shape = adapter.certify_snapshot_shape(snapshot)
    version = adapter.parse_snapshot(snapshot)[0]

    with RateVintageStore(
        tmp_path / "effr-v4.sqlite3", schema_version=V4_SCHEMA_VERSION
    ) as store:
        store.append_source_snapshot(snapshot, firewall_certification=shape)
        with pytest.raises(RateVintageIntegrityError, match="schema fingerprint"):
            store.append_rate_version(replace(version, schema_fingerprint="0" * 64))
        with pytest.raises(RateVintageIntegrityError, match="source ordinal"):
            store.append_rate_version(replace(version, source_row_ordinal=shape.row_count))
        version_id = store.append_rate_version(version)
        store.append_certification(
            version_id,
            status="PASS",
            certified_at=datetime(2026, 7, 31, 13, tzinfo=UTC),
        )
        freeze = store.create_dataset_freeze(
            "SYNTHETIC_EFFR_V3_V4_FREEZE",
            [version_id],
            created_at=datetime(2026, 7, 31, 14, tzinfo=UTC),
        )
        before = store.get_rate_as_of(
            "USD",
            version.strategy_availability_timestamp - timedelta(seconds=1),
            freeze.dataset_freeze_id,
        )
        at = store.get_rate_as_of(
            "USD",
            version.strategy_availability_timestamp,
            freeze.dataset_freeze_id,
        )

    assert isinstance(before, MissingRate)
    assert isinstance(at, AvailableRate)
    assert at.version_id == version_id
    assert at.publication_timestamp is None
    assert at.schema_fingerprint == LEGACY_SCHEMA_FINGERPRINT
    assert at.source_metadata is not None
    assert ("revisionIndicator", "") in at.source_metadata
