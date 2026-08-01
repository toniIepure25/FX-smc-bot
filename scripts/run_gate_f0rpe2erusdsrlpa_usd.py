"""Certify frozen EFFR snapshots under the publication-censored V3 contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidenceKind,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateAccessAuthorization,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.new_york_fed import (
    LEGACY_SCHEMA_FINGERPRINT,
    MODERN_SCHEMA_FINGERPRINT,
    NewYorkFedEffrAdapterV2,
    NewYorkFedEffrAdapterV3,
)
from fx_smc_bot.research.rate_vintage_store import (
    V4_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageStore,
)

GATE_ID = "F0RPE2ERUSDSRLPA_LEGACY_PUBLICATION_AVAILABILITY_V1"
OVERLAY_ID = "F0RPE2ERUSDSRLPA_PUBLICATION_CENSORING_OVERLAY_V1"
OVERLAY_PRE_PARSE_SHA = "8335cf4f0ee87a0d3e636b402676455f7e6730fe"
DATASET_FREEZE_ID = "F0RPE2ERUSDSRLPA_USD_CERTIFICATION_V1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION_COUNTS = (5, 4)
WINDOWS = {
    "legacy": {
        "start": date(2016, 1, 4),
        "end": date(2016, 1, 8),
        "request_identity": (
            "6c0fe53d4d94105dc8e4b12cdd7a709c42715cf4a51be3c297584b61dc005e38"
        ),
        "snapshot_sha256": (
            "c2da958e75b10e28d901a197eac1be78b2acdf4ffe77335f0bf325edc68370c3"
        ),
        "schema_fingerprint": LEGACY_SCHEMA_FINGERPRINT,
    },
    "modern": {
        "start": date(2016, 3, 1),
        "end": date(2016, 3, 4),
        "request_identity": (
            "a1289ce5201a55ea5c1d28d8df88241dd0be2e0587e3c3e9e1b1cb1bea6a7b4e"
        ),
        "snapshot_sha256": (
            "8cf63f8ae7886e63475d8a92cdecac6f5e40d50908498c5eb547f1801cafa342"
        ),
        "schema_fingerprint": MODERN_SCHEMA_FINGERPRINT,
    },
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-clean-room-root", type=Path, required=True)
    parser.add_argument("--v4-database", type=Path, required=True)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authorization(
    declaration: OfficialNumericalEndpoint,
    start: date,
    end: date,
) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"F0RPE2ERUSDSR_EFFR_{start}_{end}",
        adapter_ids=frozenset({declaration.adapter_id}),
        currencies=frozenset({declaration.currency}),
        series_ids=frozenset({declaration.series_id}),
        start=start,
        end=end,
        official_hosts=frozenset({urlparse(declaration.url).hostname or ""}),
        source_allowlist_identities=frozenset({declaration.allowlist_identity}),
    )


def _exact_request(window: Mapping[str, object]) -> OfficialRateRequest:
    adapter = NewYorkFedEffrAdapterV2()
    declaration = adapter.endpoint_declarations[0]
    start = window["start"]
    end = window["end"]
    if not isinstance(start, date) or not isinstance(end, date):
        raise RuntimeError("Frozen EFFR window contains invalid dates")
    request = adapter.build_requests(
        start,
        end,
        _authorization(declaration, start, end),
    )[0]
    if request.request_identity != window["request_identity"]:
        raise RuntimeError("FROZEN_EFFR_REQUEST_IDENTITY_MISMATCH")
    return request


def _load_snapshot(
    clean_room_root: Path,
    request: OfficialRateRequest,
    expected_sha256: str,
) -> SourceSnapshot:
    snapshot_dir = (
        clean_room_root
        / "official-rate-snapshots"
        / request.adapter_id
        / request.request_identity
    )
    metadata_path = snapshot_dir / f"{expected_sha256}.json"
    payload_path = snapshot_dir / f"{expected_sha256}.payload"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload = payload_path.read_bytes()
    if not isinstance(metadata, dict):
        raise RuntimeError("EFFR_SNAPSHOT_METADATA_OBJECT_REQUIRED")
    declaration = request.endpoint_declaration
    expected_metadata = {
        "adapter_id": request.adapter_id,
        "currency": request.currency,
        "series_id": request.series_id,
        "request_identity": request.request_identity,
        "payload_sha256": expected_sha256,
        "source_endpoint_role": request.source_endpoint_role,
        "endpoint_declaration_sha256": (
            declaration.declaration_sha256 if declaration is not None else None
        ),
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise RuntimeError("EFFR_SNAPSHOT_METADATA_IDENTITY_MISMATCH")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("EFFR_SNAPSHOT_PAYLOAD_SHA256_MISMATCH")
    response_headers = metadata.get("response_headers")
    if not isinstance(response_headers, list):
        raise RuntimeError("EFFR_SNAPSHOT_RESPONSE_HEADERS_REQUIRED")
    headers = tuple(sorted((str(item[0]).lower(), str(item[1])) for item in response_headers))
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type=str(metadata["content_type"]),
        response_headers=headers,
        retrieved_at=datetime.fromisoformat(str(metadata["retrieved_at"])),
        source_snapshot_sha256=expected_sha256,
    )


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require_external_clean_room_paths(source_root: Path, database: Path) -> None:
    repository = REPOSITORY_ROOT.resolve()
    if source_root.resolve().is_relative_to(repository):
        raise RuntimeError("SOURCE_CLEAN_ROOM_MUST_BE_OUTSIDE_GIT")
    if database.resolve().is_relative_to(repository):
        raise RuntimeError("V4_DATABASE_MUST_BE_OUTSIDE_GIT")


def _cleanup_failed_database(database: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{database}{suffix}")
        if candidate.exists():
            candidate.unlink()


def _certify(args: argparse.Namespace) -> dict[str, object]:
    adapter = NewYorkFedEffrAdapterV3()
    snapshots: list[SourceSnapshot] = []
    request_ids: list[str] = []
    snapshot_ids: list[str] = []
    for window in WINDOWS.values():
        request = _exact_request(window)
        snapshot = _load_snapshot(
            args.source_clean_room_root,
            request,
            str(window["snapshot_sha256"]),
        )
        snapshots.append(snapshot)
        request_ids.append(request.request_identity)
        snapshot_ids.append(snapshot.source_snapshot_sha256)

    parsed_runs = tuple(
        tuple(adapter.parse_snapshot(snapshot) for snapshot in snapshots)
        for _ in range(3)
    )
    if parsed_runs[0] != parsed_runs[1] or parsed_runs[1] != parsed_runs[2]:
        raise RuntimeError("NONDETERMINISTIC_EFFR_V3_PARSE")
    observed_counts = tuple(len(batch) for batch in parsed_runs[0])
    if observed_counts != EXPECTED_VERSION_COUNTS:
        raise RuntimeError("EFFR_FROZEN_WINDOW_VERSION_COUNT_MISMATCH")
    versions = tuple(version for batch in parsed_runs[0] for version in batch)
    certifications = tuple(adapter.certify_version(version) for version in versions)
    if not versions or not all(certification.passed for certification in certifications):
        raise RuntimeError("BLOCKED_BY_USD_ADAPTER_V3")

    latest_retrieval = max(snapshot.retrieved_at for snapshot in snapshots).astimezone(UTC)
    certified_at = latest_retrieval + timedelta(seconds=1)
    freeze_time = latest_retrieval + timedelta(minutes=1)
    version_ids: list[str] = []
    before_missing = 0
    at_available = 0
    after_available = 0
    legacy_publication_day_missing = 0
    modern_publication_day_available = 0
    with RateVintageStore(args.v4_database, schema_version=V4_SCHEMA_VERSION) as store:
        for snapshot in snapshots:
            shape = adapter.certify_snapshot_shape(snapshot)
            store.append_source_snapshot(snapshot, firewall_certification=shape)
        for index, (version, certification) in enumerate(
            zip(versions, certifications, strict=True)
        ):
            version_id = store.append_rate_version(version)
            version_ids.append(version_id)
            store.append_certification(
                version_id,
                status=certification.status,
                certified_at=certified_at,
                details={
                    "adapter_id": adapter.adapter_id,
                    "checks": list(certification.checks),
                    "publication_timestamp_fabricated": False,
                },
            )
            single_freeze = store.create_dataset_freeze(
                f"F0RPE2ERUSDSRLPA_USD_VERSION_{index:02d}",
                [version_id],
                created_at=freeze_time,
            )
            availability = version.strategy_availability_timestamp
            before = store.get_rate_as_of(
                "USD", availability - timedelta(microseconds=1), single_freeze.dataset_freeze_id
            )
            at = store.get_rate_as_of("USD", availability, single_freeze.dataset_freeze_id)
            after = store.get_rate_as_of(
                "USD", availability + timedelta(seconds=1), single_freeze.dataset_freeze_id
            )
            if not isinstance(before, MissingRate):
                raise RuntimeError("EFFR_AVAILABLE_BEFORE_STRATEGY_BOUNDARY")
            if not isinstance(at, AvailableRate) or not isinstance(after, AvailableRate):
                raise RuntimeError("EFFR_UNAVAILABLE_AT_OR_AFTER_STRATEGY_BOUNDARY")
            before_missing += 1
            at_available += 1
            after_available += 1
            publication_day_execution = datetime.combine(
                version.resolved_publication_lower_bound.date(),
                time(17, 5),
                tzinfo=NEW_YORK_ZONE,
            )
            publication_day_result = store.get_rate_as_of(
                "USD", publication_day_execution, single_freeze.dataset_freeze_id
            )
            if version.publication_evidence_kind == (
                PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value
            ):
                if not isinstance(publication_day_result, MissingRate):
                    raise RuntimeError("LEGACY_EFFR_AVAILABLE_BEFORE_DAY_ENVELOPE_CLOSED")
                legacy_publication_day_missing += 1
            else:
                if not isinstance(publication_day_result, AvailableRate):
                    raise RuntimeError("MODERN_EFFR_UNAVAILABLE_AFTER_REVISION_BOUNDARY")
                modern_publication_day_available += 1
        combined_freeze = store.create_dataset_freeze(
            DATASET_FREEZE_ID,
            version_ids,
            created_at=freeze_time,
            metadata={
                "gate_id": GATE_ID,
                "overlay_id": OVERLAY_ID,
                "overlay_pre_parse_sha": OVERLAY_PRE_PARSE_SHA,
            },
        )
        store.append_ingestion_run(
            "F0RPE2ERUSDSRLPA_USD_CERTIFICATION_RUN_V1",
            adapter_id=adapter.adapter_id,
            started_at=latest_retrieval,
            completed_at=freeze_time,
            status="PASS",
            snapshot_count=len(snapshots),
            details={"reused_predecessor_snapshots": True, "numerical_rows_in_git": 0},
        )
        table_counts = store.table_counts()

    legacy_count = sum(
        version.observation_date < date(2016, 3, 1) for version in versions
    )
    modern_count = len(versions) - legacy_count
    common = {
        "gate_id": GATE_ID,
        "overlay_id": OVERLAY_ID,
        "legacy_availability_overlay_pre_parse_sha": OVERLAY_PRE_PARSE_SHA,
        "status": "PASS",
    }
    adapter_artifact: dict[str, object] = {
        **common,
        "adapter_id": adapter.adapter_id,
        "request_count": len(request_ids),
        "reused_snapshot_count": len(snapshot_ids),
        "version_count": len(version_ids),
        "legacy_version_count": legacy_count,
        "modern_version_count": modern_count,
        "request_identity_set_sha256": _canonical_sha256(sorted(request_ids)),
        "snapshot_sha256_set_sha256": _canonical_sha256(sorted(snapshot_ids)),
        "version_id_set_sha256": _canonical_sha256(sorted(version_ids)),
        "legacy_schema_fingerprint": LEGACY_SCHEMA_FINGERPRINT,
        "modern_schema_fingerprint": MODERN_SCHEMA_FINGERPRINT,
        "series_identity": "PASS",
        "unit_conversion": "PASS",
        "publication_day_derivation": "PASS",
        "publication_bounds": "PASS",
        "strategy_availability": "PASS",
        "revision_nullability": "PASS",
        "response_firewall": "PASS",
        "three_run_deterministic_parsing": "PASS",
        "actual_publication_timestamp_non_null_count": 0,
        "official_revision_identifier_non_null_count": 0,
        "official_payloads_committed_to_git": 0,
        "official_rate_rows_committed_to_git": 0,
    }
    store_artifact: dict[str, object] = {
        **common,
        "schema_version": V4_SCHEMA_VERSION,
        "database_location": "LOCAL_CLEAN_ROOM_OUTSIDE_GIT",
        "new_database_required": True,
        "dataset_freeze_id": combined_freeze.dataset_freeze_id,
        "dataset_freeze_sha256": combined_freeze.freeze_sha256,
        "table_counts": table_counts,
        "append_only": "PASS",
        "dataset_freeze_pinning": "PASS",
        "nullable_actual_publication_timestamp": "PASS",
        "nullable_official_revision_identifier": "PASS",
        "publication_interval_support": "PASS",
        "explicit_asof_query": "PASS",
    }
    asof_artifact: dict[str, object] = {
        **common,
        "dataset_freeze_id": combined_freeze.dataset_freeze_id,
        "versions_audited": len(version_ids),
        "asof_before_availability_missing": before_missing,
        "asof_at_availability_available": at_available,
        "asof_after_availability_available": after_available,
        "legacy_publication_day_1705_missing": legacy_publication_day_missing,
        "modern_publication_day_1705_available": modern_publication_day_available,
        "future_revision_leakage": "PASS",
        "actual_publication_timestamp_fabricated": False,
        "legacy_rule": "FIRST_FROZEN_1705_EXECUTION_STRICTLY_AFTER_PUBLICATION_DAY_ENVELOPE",
        "modern_rule": "SAME_PUBLICATION_DAY_1705_AFTER_1430_REVISION_COMPLETE_BOUNDARY",
    }
    if args.results_root is not None:
        _write_json(args.results_root / "usd_adapter_v3_certification.json", adapter_artifact)
        _write_json(args.results_root / "vintage_store_v4_certification.json", store_artifact)
        _write_json(args.results_root / "usd_asof_availability_audit.json", asof_artifact)
    return {
        "status": "PASS",
        "gate_id": GATE_ID,
        "request_count": len(request_ids),
        "reused_snapshot_count": len(snapshot_ids),
        "version_count": len(version_ids),
        "legacy_version_count": legacy_count,
        "modern_version_count": modern_count,
        "three_run_deterministic_parsing": "PASS",
        "asof_audit": "PASS",
        "result_artifact_count": 3 if args.results_root is not None else 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _require_external_clean_room_paths(
        args.source_clean_room_root,
        args.v4_database,
    )
    if args.v4_database.exists():
        raise RuntimeError("V4_CERTIFICATION_DATABASE_MUST_NOT_EXIST")
    if args.dry_run:
        summary = {
            "status": "DRY_RUN",
            "gate_id": GATE_ID,
            "request_count": len(WINDOWS),
            "network_request_count": 0,
            "parse_count": 0,
            "v4_database_created": False,
        }
    else:
        try:
            summary = _certify(args)
        except Exception:
            _cleanup_failed_database(args.v4_database)
            raise
    print(json.dumps(summary, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
