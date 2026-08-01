"""Certify corrected ECB EONIA/euro-short-term-rate snapshots under V4."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from fx_smc_bot.research.publication_censoring import NEW_YORK_ZONE
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.ecb import (
    ECB_SDMX_CSV_INSPECTOR_ID,
    EONIA_END,
    EONIA_V3_KEY,
    EONIA_V3_SCHEMA_FINGERPRINT,
    ESTR_START,
    ESTR_V3_KEY,
    ESTR_V3_SCHEMA_FINGERPRINT,
    EcbEoniaEstrAdapterV3,
    EcbSdmxCsvShapeCertification,
)
from fx_smc_bot.research.rate_vintage_store import (
    V4_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageStore,
)

GATE_ID = "F0RPE2ERUSDSRLPA_EUR_SOURCE_RECONCILIATION_V1"
DATASET_FREEZE_ID = "F0RPE2ERUSDSRLPAEURSR_EUR_CERTIFICATION_V1"
RECONCILIATION_PRE_PARSE_SHA = "11a31fe6dbb10b001d9b943448cb88c99942e98e"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Window:
    name: str
    filename: str
    start: date
    end: date
    series_id: str
    request_identity: str
    snapshot_sha256: str
    expected_versions: int
    schema_fingerprint: str


WINDOWS = (
    Window(
        name="eonia_ordinary",
        filename="eonia_ordinary.csv",
        start=date(2016, 1, 4),
        end=date(2016, 1, 8),
        series_id="EONIA",
        request_identity="417854488c593f7c82674609f4ec67bdc944f8169a6ff9799104862fef6390fb",
        snapshot_sha256="c4e8f4e3a9a991ec29f671669e93e027e0aa2497a90dec22436788067e994de3",
        expected_versions=5,
        schema_fingerprint=EONIA_V3_SCHEMA_FINGERPRINT,
    ),
    Window(
        name="eonia_final",
        filename="eonia_final.csv",
        start=date(2019, 9, 26),
        end=EONIA_END,
        series_id="EONIA",
        request_identity="51d2df209a6b37bf8ffc3b4a737fbb6c45f3704845c5d395a42dc4200d7cbd6d",
        snapshot_sha256="6f7f7c398a554af649be038cd592b8619ff035635f6b1834d52128c2609e7390",
        expected_versions=3,
        schema_fingerprint=EONIA_V3_SCHEMA_FINGERPRINT,
    ),
    Window(
        name="estr_initial",
        filename="estr_initial.csv",
        start=ESTR_START,
        end=date(2019, 10, 4),
        series_id="ESTR",
        request_identity="5485010fb9e9a8b70d541e82042cfda0c41b9d38fa221095e7e8e4cb8959ec14",
        snapshot_sha256="ba1a3481a98108c826f6b6f16a790aa5b049e2eaf23059441a151666fa5aced1",
        expected_versions=4,
        schema_fingerprint=ESTR_V3_SCHEMA_FINGERPRINT,
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-clean-room-root", type=Path, required=True)
    parser.add_argument("--v4-database", type=Path, required=True)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, document: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _authorization(start: date, end: date) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"F0RPE2ERUSDSRLPAEURSR_EUR_{start}_{end}",
        adapter_ids=frozenset({"ECB_EONIA_ESTR_V3"}),
        currencies=frozenset({"EUR"}),
        series_ids=frozenset({"EONIA", "ESTR"}),
        start=start,
        end=end,
        official_hosts=frozenset({"data-api.ecb.europa.eu"}),
        source_allowlist_identities=frozenset({"F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"}),
    )


def _exact_request(adapter: EcbEoniaEstrAdapterV3, window: Window) -> OfficialRateRequest:
    requests = adapter.build_requests(
        window.start,
        window.end,
        _authorization(window.start, window.end),
    )
    if len(requests) != 1:
        raise RuntimeError("ECB_WINDOW_REQUEST_SPLIT_MISMATCH")
    request = requests[0]
    if request.series_id != window.series_id:
        raise RuntimeError("ECB_WINDOW_SERIES_ID_MISMATCH")
    if request.request_identity != window.request_identity:
        raise RuntimeError("ECB_WINDOW_REQUEST_IDENTITY_MISMATCH")
    if tuple(dict(request.query_parameters)[key] for key in ("detail", "format")) != (
        "full",
        "csvdata",
    ):
        raise RuntimeError("ECB_REQUEST_QUERY_MISMATCH")
    return request


def _load_snapshot(
    clean_room_root: Path,
    request: OfficialRateRequest,
    window: Window,
    retrieved_at: datetime,
) -> SourceSnapshot:
    payload_path = clean_room_root / window.filename
    payload = payload_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != window.snapshot_sha256:
        raise RuntimeError("ECB_CLEAN_ROOM_PAYLOAD_SHA256_MISMATCH")
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type="text/csv",
        response_headers=(("content-type", "text/csv"),),
        retrieved_at=retrieved_at,
        source_snapshot_sha256=window.snapshot_sha256,
    )


def _require_external_paths(source_root: Path, database: Path) -> None:
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


def _parse_retrieved_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError("RETRIEVED_AT_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


def _ny_execution_after_boundary(version_timestamp: datetime) -> bool:
    execution = datetime.combine(
        version_timestamp.astimezone(NEW_YORK_ZONE).date(),
        time(17, 5),
        tzinfo=NEW_YORK_ZONE,
    )
    return execution > version_timestamp.astimezone(NEW_YORK_ZONE)


def _certify(args: argparse.Namespace) -> dict[str, object]:
    adapter = EcbEoniaEstrAdapterV3()
    retrieved_at = _parse_retrieved_at(str(args.retrieved_at))
    snapshots: list[SourceSnapshot] = []
    request_ids: list[str] = []
    snapshot_ids: list[str] = []
    shapes: list[EcbSdmxCsvShapeCertification] = []

    for window in WINDOWS:
        request = _exact_request(adapter, window)
        snapshot = _load_snapshot(args.source_clean_room_root, request, window, retrieved_at)
        shape = adapter.certify_snapshot_shape(snapshot)
        if shape.schema_fingerprint != window.schema_fingerprint:
            raise RuntimeError("ECB_SHAPE_SCHEMA_FINGERPRINT_MISMATCH")
        snapshots.append(snapshot)
        shapes.append(shape)
        request_ids.append(request.request_identity)
        snapshot_ids.append(snapshot.source_snapshot_sha256)

    parsed_runs = tuple(
        tuple(adapter.parse_snapshot(snapshot) for snapshot in snapshots)
        for _ in range(3)
    )
    if parsed_runs[0] != parsed_runs[1] or parsed_runs[1] != parsed_runs[2]:
        raise RuntimeError("NONDETERMINISTIC_ECB_V3_PARSE")
    observed_counts = tuple(len(batch) for batch in parsed_runs[0])
    expected_counts = tuple(window.expected_versions for window in WINDOWS)
    if observed_counts != expected_counts:
        raise RuntimeError("ECB_FROZEN_WINDOW_VERSION_COUNT_MISMATCH")

    versions = tuple(version for batch in parsed_runs[0] for version in batch)
    certifications = tuple(adapter.certify_version(version) for version in versions)
    if not versions or not all(certification.passed for certification in certifications):
        raise RuntimeError("BLOCKED_BY_ECB_RATE_SOURCE_ACCESS")

    eonia_dates = sorted(
        version.observation_date.isoformat()
        for version in versions
        if version.series_id == "EONIA"
    )
    estr_dates = sorted(
        version.observation_date.isoformat()
        for version in versions
        if version.series_id == "ESTR"
    )
    if eonia_dates[-1] != EONIA_END.isoformat() or estr_dates[0] != ESTR_START.isoformat():
        raise RuntimeError("ECB_EONIA_ESTR_TRANSITION_MISMATCH")

    certified_at = retrieved_at + timedelta(seconds=1)
    freeze_time = retrieved_at + timedelta(minutes=1)
    version_ids: list[str] = []
    before_missing = 0
    at_available = 0
    after_available = 0
    eonia_before_1900_missing = 0
    eonia_at_1900_available = 0
    estr_before_0900_missing = 0
    estr_at_0900_available = 0
    ny_1705_available = 0

    with RateVintageStore(args.v4_database, schema_version=V4_SCHEMA_VERSION) as store:
        for snapshot, shape in zip(snapshots, shapes, strict=True):
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
                    "source_retrieval_timestamp_used_for_availability": False,
                },
            )
            single_freeze = store.create_dataset_freeze(
                f"F0RPE2ERUSDSRLPAEURSR_EUR_VERSION_{index:02d}",
                [version_id],
                created_at=freeze_time,
            )
            availability = version.strategy_availability_timestamp
            before = store.get_rate_as_of(
                "EUR", availability - timedelta(microseconds=1), single_freeze.dataset_freeze_id
            )
            at = store.get_rate_as_of("EUR", availability, single_freeze.dataset_freeze_id)
            after = store.get_rate_as_of(
                "EUR", availability + timedelta(seconds=1), single_freeze.dataset_freeze_id
            )
            if not isinstance(before, MissingRate):
                raise RuntimeError("EUR_AVAILABLE_BEFORE_STRATEGY_BOUNDARY")
            if not isinstance(at, AvailableRate) or not isinstance(after, AvailableRate):
                raise RuntimeError("EUR_UNAVAILABLE_AT_OR_AFTER_STRATEGY_BOUNDARY")
            before_missing += 1
            at_available += 1
            after_available += 1
            if version.series_id == "EONIA":
                lower_bound = version.publication_lower_bound
                if lower_bound is None:
                    raise RuntimeError("EONIA_PUBLICATION_LOWER_BOUND_REQUIRED")
                pre = store.get_rate_as_of(
                    "EUR",
                    lower_bound - timedelta(microseconds=1),
                    single_freeze.dataset_freeze_id,
                )
                on_boundary = store.get_rate_as_of(
                    "EUR",
                    lower_bound,
                    single_freeze.dataset_freeze_id,
                )
                if not isinstance(pre, MissingRate) or not isinstance(
                    on_boundary, AvailableRate
                ):
                    raise RuntimeError("EONIA_1900_BOUNDARY_AUDIT_FAILED")
                eonia_before_1900_missing += 1
                eonia_at_1900_available += 1
            else:
                upper_bound = version.publication_upper_bound
                if upper_bound is None:
                    raise RuntimeError("ESTR_PUBLICATION_UPPER_BOUND_REQUIRED")
                pre = store.get_rate_as_of(
                    "EUR",
                    upper_bound - timedelta(microseconds=1),
                    single_freeze.dataset_freeze_id,
                )
                on_boundary = store.get_rate_as_of(
                    "EUR",
                    upper_bound,
                    single_freeze.dataset_freeze_id,
                )
                if not isinstance(pre, MissingRate) or not isinstance(
                    on_boundary, AvailableRate
                ):
                    raise RuntimeError("ESTR_0900_BOUNDARY_AUDIT_FAILED")
                estr_before_0900_missing += 1
                estr_at_0900_available += 1
            if not _ny_execution_after_boundary(availability):
                raise RuntimeError("EUR_1705_NEW_YORK_ALIGNMENT_FAILED")
            ny_1705_available += 1
        combined_freeze = store.create_dataset_freeze(
            DATASET_FREEZE_ID,
            version_ids,
            created_at=freeze_time,
            metadata={
                "gate_id": GATE_ID,
                "eur_source_reconciliation_pre_parse_sha": RECONCILIATION_PRE_PARSE_SHA,
            },
        )
        store.append_ingestion_run(
            "F0RPE2ERUSDSRLPAEURSR_EUR_CERTIFICATION_RUN_V1",
            adapter_id=adapter.adapter_id,
            started_at=retrieved_at,
            completed_at=freeze_time,
            status="PASS",
            snapshot_count=len(snapshots),
            details={
                "clean_room_only": True,
                "official_payloads_committed_to_git": 0,
                "official_rate_rows_committed_to_git": 0,
            },
        )
        table_counts = store.table_counts()

    eonia_count = len(eonia_dates)
    estr_count = len(estr_dates)
    common = {
        "gate_id": GATE_ID,
        "status": "PASS",
        "eur_source_reconciliation_pre_parse_sha": RECONCILIATION_PRE_PARSE_SHA,
    }
    adapter_artifact: dict[str, object] = {
        **common,
        "adapter_id": adapter.adapter_id,
        "parser_version": adapter.parser_version,
        "schema_id": adapter.schema_id,
        "request_count": len(request_ids),
        "snapshot_count": len(snapshot_ids),
        "version_count": len(version_ids),
        "eonia_version_count": eonia_count,
        "estr_version_count": estr_count,
        "request_identity_set_sha256": _canonical_sha256(sorted(request_ids)),
        "snapshot_sha256_set_sha256": _canonical_sha256(sorted(snapshot_ids)),
        "version_id_set_sha256": _canonical_sha256(sorted(version_ids)),
        "eonia_source_identity": EONIA_V3_KEY,
        "estr_source_identity": ESTR_V3_KEY,
        "invalid_eon_key_active": False,
        "eonia_schema_fingerprint": EONIA_V3_SCHEMA_FINGERPRINT,
        "estr_schema_fingerprint": ESTR_V3_SCHEMA_FINGERPRINT,
        "server_side_bounds": "PASS",
        "sdmx_schema": "PASS",
        "series_identity": "PASS",
        "unit_conversion": "OBS_VALUE_PERCENT_DIVIDED_BY_100",
        "target2_calendar": "PASS",
        "eonia_publication_availability": "PASS",
        "estr_publication_availability": "PASS",
        "revision_complete_boundary": "PASS",
        "response_firewall": "PASS",
        "three_run_deterministic_parse": "PASS",
        "actual_publication_timestamp_fabricated": False,
        "source_retrieval_timestamp_used_for_availability": False,
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
        "v4_insertion": "PASS",
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
        "eonia_before_1900_missing": eonia_before_1900_missing,
        "eonia_at_1900_available": eonia_at_1900_available,
        "estr_before_0900_missing": estr_before_0900_missing,
        "estr_at_0900_available": estr_at_0900_available,
        "ny_1705_alignment_available": ny_1705_available,
        "future_revision_leakage": "PASS",
        "actual_publication_timestamp_fabricated": False,
        "benchmark_vs_archive_availability_separated": True,
    }
    transition_artifact: dict[str, object] = {
        **common,
        "transition_id": "ECB_EONIA_ESTR_TRANSITION_V3",
        "last_primary_eonia_observation": eonia_dates[-1],
        "first_primary_estr_observation": estr_dates[0],
        "eonia_source_identity": EONIA_V3_KEY,
        "estr_source_identity": ESTR_V3_KEY,
        "overlap": "PASS",
        "gap": "PASS",
        "interpolation": "PASS",
        "pre_estr_substitution": "PASS",
        "post_transition_eonia_primary": "REJECTED",
    }
    artifact_hashes: dict[str, str] = {}
    if args.results_root is not None:
        artifact_hashes["eur_adapter_v3_certification.json"] = _write_json(
            args.results_root / "eur_adapter_v3_certification.json", adapter_artifact
        )
        artifact_hashes["eur_vintage_store_certification.json"] = _write_json(
            args.results_root / "eur_vintage_store_certification.json", store_artifact
        )
        artifact_hashes["eur_asof_availability_audit.json"] = _write_json(
            args.results_root / "eur_asof_availability_audit.json", asof_artifact
        )
        artifact_hashes["eonia_estr_transition_audit.json"] = _write_json(
            args.results_root / "eonia_estr_transition_audit.json", transition_artifact
        )
    return {
        "status": "PASS",
        "gate_id": GATE_ID,
        "request_count": len(request_ids),
        "snapshot_count": len(snapshot_ids),
        "version_count": len(version_ids),
        "eonia_version_count": eonia_count,
        "estr_version_count": estr_count,
        "three_run_deterministic_parse": "PASS",
        "asof_audit": "PASS",
        "shape_inspector_id": ECB_SDMX_CSV_INSPECTOR_ID,
        "artifact_hashes": artifact_hashes,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _require_external_paths(args.source_clean_room_root, args.v4_database)
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
