"""Development-data planning for Gate Q.0 with explicit-path-only inventory."""

from __future__ import annotations

import calendar
import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from fx_smc_bot.research.quant_polarity import (
    DEVELOPMENT_INSTRUMENTS,
    PROGRAM_ID,
    authorize_explicit_path,
    authorize_request,
    canonical_json_sha256,
)

DEVELOPMENT_YEARS = tuple(range(2015, 2020))
MONTHS = tuple(range(1, 13))
SIDES = ("bid", "ask")
RAW_ROOTS = (
    "data/raw/gate_q0/dukascopy-node",
    "data/real/raw/dukascopy-node",
    "data/raw/dukascopy-node",
    "data/raw/p0rdcra1a/dukascopy-node",
)
CANONICAL_ROOTS = (
    "data/canonical/gate_q0",
    "data/canonical/dukascopy",
    "data/canonical/p0rdcra1a",
)


@dataclass(frozen=True)
class DevelopmentPartition:
    instrument: str
    year: int
    month: int
    side: str

    @property
    def partition_id(self) -> str:
        return f"{self.instrument}:{self.side}:{self.year:04d}-{self.month:02d}"


def development_partitions() -> tuple[DevelopmentPartition, ...]:
    return tuple(
        DevelopmentPartition(instrument, year, month, side)
        for instrument in DEVELOPMENT_INSTRUMENTS
        for year in DEVELOPMENT_YEARS
        for month in MONTHS
        for side in SIDES
    )


def _explicit_file_record(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    authorize_explicit_path(path.as_posix(), "development")
    exists = path.is_file()
    return {
        "path": path.relative_to(root).as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
    }


def explicit_development_inventory(root: Path) -> dict[str, Any]:
    """Inspect only fully specified files; never enumerate a directory."""
    root_counts: dict[str, dict[str, int]] = {}
    total_present_bytes = 0
    total_present_files = 0
    pair_month_presence: dict[str, dict[str, bool]] = {}
    for instrument in DEVELOPMENT_INSTRUMENTS:
        for year in DEVELOPMENT_YEARS:
            for month in MONTHS:
                key = f"{instrument}:{year:04d}-{month:02d}"
                pair_month_presence[key] = {"raw": False, "m1": False, "m5": False}
                for raw_root in RAW_ROOTS:
                    for side in SIDES:
                        base = Path(raw_root) / instrument / f"price={side}"
                        base = base / f"year={year}" / f"month={month:02d}"
                        for filename in ("data.json", "manifest.json"):
                            record = _explicit_file_record(root, base / filename)
                            counts = root_counts.setdefault(
                                raw_root, {"present_files": 0, "present_bytes": 0}
                            )
                            if record["exists"]:
                                counts["present_files"] += 1
                                counts["present_bytes"] += int(record["size_bytes"])
                                total_present_files += 1
                                total_present_bytes += int(record["size_bytes"])
                                pair_month_presence[key]["raw"] = True
                for canonical_root in CANONICAL_ROOTS:
                    for timeframe in ("M1", "M5"):
                        relative = (
                            Path(canonical_root)
                            / instrument
                            / f"timeframe={timeframe}"
                            / f"year={year}"
                            / f"month={month:02d}"
                            / "part.parquet"
                        )
                        record = _explicit_file_record(root, relative)
                        counts = root_counts.setdefault(
                            canonical_root, {"present_files": 0, "present_bytes": 0}
                        )
                        if record["exists"]:
                            counts["present_files"] += 1
                            counts["present_bytes"] += int(record["size_bytes"])
                            total_present_files += 1
                            total_present_bytes += int(record["size_bytes"])
                            pair_month_presence[key][timeframe.lower()] = True

    classifications = {
        "COMPLETE_REQUIRES_RECERTIFICATION": 0,
        "PARTIAL_REQUIRES_RECOVERY": 0,
        "MISSING": 0,
    }
    for presence in pair_month_presence.values():
        if all(presence.values()):
            classifications["COMPLETE_REQUIRES_RECERTIFICATION"] += 1
        elif any(presence.values()):
            classifications["PARTIAL_REQUIRES_RECOVERY"] += 1
        else:
            classifications["MISSING"] += 1
    return {
        "authorized_instruments": list(DEVELOPMENT_INSTRUMENTS),
        "authorized_years": list(DEVELOPMENT_YEARS),
        "pair_month_count": len(pair_month_presence),
        "side_month_count": len(development_partitions()),
        "classification_counts": classifications,
        "root_summaries": root_counts,
        "present_file_count": total_present_files,
        "present_bytes": total_present_bytes,
        "parent_directories_enumerated": False,
        "holdout_paths_constructed_or_tested": False,
        "replication_paths_constructed_or_tested": False,
        "status": "PASS",
    }


def development_storage_budget(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    usage = shutil.disk_usage(root)
    pair_months = len(DEVELOPMENT_INSTRUMENTS) * len(DEVELOPMENT_YEARS) * len(MONTHS)
    missing_pair_months = int(inventory["classification_counts"]["MISSING"])
    partial_pair_months = int(inventory["classification_counts"]["PARTIAL_REQUIRES_RECOVERY"])
    estimated_raw = (missing_pair_months * 2 + partial_pair_months) * 8 * 1024**2
    estimated_m1 = pair_months * 4 * 1024**2
    estimated_m5 = pair_months * 1 * 1024**2
    scratch = (estimated_m1 + estimated_m5) // 2
    peak = estimated_raw + estimated_m1 + estimated_m5 + scratch
    safety_margin = min(10 * 1024**3, int(usage.total * 0.20))
    remaining = usage.free - peak
    return {
        "filesystem_total_bytes": usage.total,
        "current_free_bytes": usage.free,
        "estimated_missing_raw_bytes": estimated_raw,
        "estimated_m1_canonical_bytes": estimated_m1,
        "estimated_m5_canonical_bytes": estimated_m5,
        "certification_scratch_bytes": scratch,
        "estimated_temporary_peak_bytes": peak,
        "estimated_remaining_after_peak_bytes": remaining,
        "required_safety_margin_bytes": safety_margin,
        "status": "PASS" if remaining >= safety_margin else "FAIL",
    }


def development_recovery_protocol(root: Path, preregistration_sha: str) -> dict[str, Any]:
    inventory = explicit_development_inventory(root)
    budget = development_storage_budget(root, inventory)
    partitions = tuple(
        sorted(
            development_partitions(),
            key=lambda item: (item.side, item.instrument, item.year, item.month),
        )
    )
    payload: dict[str, Any] = {
        "program_id": PROGRAM_ID,
        "protocol_id": "Q0_DEVELOPMENT_DATA_RECOVERY_V1",
        "preregistration_sha": preregistration_sha,
        "instruments": list(DEVELOPMENT_INSTRUMENTS),
        "start": "2015-01-01",
        "end": "2019-12-31",
        "pair_month_count": 240,
        "side_month_count": 480,
        "planned_partition_ids": [partition.partition_id for partition in partitions],
        "primary_provider": "dukascopy-node@1.46.4",
        "fallback_provider": "native Dukascopy BI5 parity-certified transport",
        "raw_source": "DUKASCOPY_TICK_BI5_BID_ASK",
        "canonical_hierarchy": ["UTC_M1_BID_ASK_OHLC", "M5_BID_ASK_OHLC"],
        "inventory": inventory,
        "storage_budget": budget,
        "retry_policy": {
            "maximum_attempts_per_unit": 5,
            "backoff": "bounded exponential",
            "http_429": "honor Retry-After",
        },
        "concurrency": {
            "maximum_workers": 8,
            "worker_unit": "instrument-side-month",
            "adaptive_reduction_on_rate_limit": True,
        },
        "certification": {
            "all_pair_months_required": True,
            "zero_unresolved_partitions_required": True,
            "zero_certified_zero_row_partitions_required": True,
            "positive_finite_spread_required": True,
            "deterministic_canonicalization_runs": 3,
        },
        "guards": {
            "authorize_before_path_or_provider_access": True,
            "development_mode_only": True,
            "request_end_lte": "2019-12-31",
            "replication_access": False,
            "holdout_access": False,
        },
        "local_storage": {
            "raw": "data/raw/gate_q0/dukascopy-node",
            "canonical": "data/canonical/gate_q0",
            "state": "data/acquisition_state/gate_q0",
            "logs": "logs/gate_q0",
        },
        "raw_or_canonical_git_commit_permitted": False,
        "status": "FROZEN_BEFORE_PROVIDER_ACCESS"
        if budget["status"] == "PASS" and inventory["status"] == "PASS"
        else "BLOCKED_BY_STORAGE_BUDGET",
    }
    payload["protocol_hash"] = canonical_json_sha256(payload)
    return payload


def validate_recovery_protocol(protocol: dict[str, Any]) -> None:
    hash_payload = {key: value for key, value in protocol.items() if key != "protocol_hash"}
    if canonical_json_sha256(hash_payload) != protocol.get("protocol_hash"):
        raise ValueError("Development recovery protocol hash mismatch")
    if protocol.get("status") != "FROZEN_BEFORE_PROVIDER_ACCESS":
        raise ValueError("Development recovery protocol is not frozen")
    if protocol.get("instruments") != list(DEVELOPMENT_INSTRUMENTS):
        raise ValueError("Development recovery instrument universe mismatch")
    if protocol.get("end") != "2019-12-31":
        raise ValueError("Development recovery end date mismatch")


def _append_operational_record(path: Path, record: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _acquire_development_partition(
    partition: DevelopmentPartition,
    root: Path,
) -> dict[str, Any]:
    from fx_smc_bot.data.daily_checkpoint import (
        acquire_month_bulk,
        load_month_manifest,
        save_month_manifest,
    )

    last_day = calendar.monthrange(partition.year, partition.month)[1]
    start = date(partition.year, partition.month, 1)
    end = date(partition.year, partition.month, last_day)
    authorize_request(partition.instrument, start, end, "development")
    raw_root = root / "data" / "raw" / "gate_q0" / "dukascopy-node"
    explicit_data_path = (
        raw_root
        / partition.instrument
        / f"price={partition.side}"
        / f"year={partition.year}"
        / f"month={partition.month:02d}"
        / "data.json"
    )
    authorize_explicit_path(explicit_data_path.as_posix(), "development")
    existing = load_month_manifest(
        raw_root,
        partition.instrument,
        partition.side,
        partition.year,
        partition.month,
    )
    if existing is not None:
        changed = False
        for day_status in existing.days:
            if day_status.status == "failed":
                day_status.status = "pending"
                day_status.failure_category = ""
                day_status.error = ""
                changed = True
        if changed:
            existing.compacted = False
            existing.compacted_checksum = ""
            existing.compacted_rows = 0
            save_month_manifest(raw_root, existing)
    started = time.monotonic()
    try:
        manifest = acquire_month_bulk(
            partition.instrument,
            partition.side,
            partition.year,
            partition.month,
            raw_root,
            timeframe="m1",
            batch_size=30,
            retries=5,
            pause_between_batches_ms=250,
        )
        failed_days = sum(day.status == "failed" for day in manifest.days)
        status = (
            "COMPLETE_PENDING_CERTIFICATION"
            if manifest.compacted and manifest.compacted_rows > 0 and failed_days == 0
            else "FAILED_OR_INCOMPLETE"
        )
        return {
            "partition_id": partition.partition_id,
            "instrument": partition.instrument,
            "side": partition.side,
            "year": partition.year,
            "month": partition.month,
            "status": status,
            "rows": manifest.compacted_rows,
            "failed_days": failed_days,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": "",
        }
    except Exception as exc:
        return {
            "partition_id": partition.partition_id,
            "instrument": partition.instrument,
            "side": partition.side,
            "year": partition.year,
            "month": partition.month,
            "status": "PROVIDER_OR_ACQUISITION_ERROR",
            "rows": 0,
            "failed_days": 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }


def acquire_development_data(
    root: Path,
    protocol: dict[str, Any],
    *,
    workers: int,
) -> dict[str, Any]:
    validate_recovery_protocol(protocol)
    if not 1 <= workers <= int(protocol["concurrency"]["maximum_workers"]):
        raise ValueError("Worker count outside frozen concurrency bound")
    operational_log = root / "logs" / "gate_q0" / "development_acquisition.jsonl"
    lock = threading.Lock()
    partitions = tuple(
        sorted(
            development_partitions(),
            key=lambda item: (item.side, item.instrument, item.year, item.month),
        )
    )
    queue_ids = [partition.partition_id for partition in partitions]
    planned_ids = list(protocol["planned_partition_ids"])
    if len(queue_ids) != len(set(queue_ids)) or set(queue_ids) != set(planned_ids):
        raise ValueError("Acquisition queue differs from the frozen partition scope")
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="q0-acquire") as executor:
        futures = {
            executor.submit(_acquire_development_partition, partition, root): partition
            for partition in partitions
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            _append_operational_record(
                operational_log,
                {"type": "development_partition_result", **result},
                lock,
            )
            completed = len(results)
            if completed % 10 == 0 or result["status"] != "COMPLETE_PENDING_CERTIFICATION":
                print(
                    json.dumps(
                        {
                            "completed": completed,
                            "total": len(partitions),
                            "latest": result["partition_id"],
                            "latest_status": result["status"],
                        }
                    ),
                    flush=True,
                )
    status_counts = {
        status: sum(result["status"] == status for result in results)
        for status in sorted({str(result["status"]) for result in results})
    }
    complete = status_counts.get("COMPLETE_PENDING_CERTIFICATION", 0)
    return {
        "program_id": PROGRAM_ID,
        "protocol_hash": protocol["protocol_hash"],
        "workers": workers,
        "planned_partitions": len(partitions),
        "completed_partitions": complete,
        "status_counts": status_counts,
        "total_rows": sum(int(result["rows"]) for result in results),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "provider_request_latest_permitted_date": "2019-12-31",
        "replication_provider_requests_sent": False,
        "holdout_provider_requests_sent": False,
        "status": "COMPLETE_PENDING_CERTIFICATION"
        if complete == len(partitions)
        else "INCOMPLETE_REQUIRES_REPAIR",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _series_semantic_sha256(series: Any) -> str:
    digest = hashlib.sha256()
    digest.update(str(series.pair.value).encode("ascii"))
    digest.update(str(series.timeframe.value).encode("ascii"))
    digest.update(
        np.asarray(series.timestamps).astype("datetime64[ns]").astype("<i8").tobytes()
    )
    for field in (
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    ):
        digest.update(np.asarray(getattr(series, field), dtype="<f8").tobytes())
    return digest.hexdigest()


def _canonical_series_from_raw_rows(
    instrument: str,
    bid_rows: list[dict[str, Any]],
    ask_rows: list[dict[str, Any]],
) -> Any:
    from fx_smc_bot.config import Timeframe, TradingPair
    from fx_smc_bot.data.bidask import BidAskBarSeries

    bid = {int(item["timestamp"]): item for item in bid_rows}
    ask = {int(item["timestamp"]): item for item in ask_rows}
    if len(bid) != len(bid_rows) or len(ask) != len(ask_rows):
        raise ValueError("Duplicate raw M1 timestamp")
    if set(bid) != set(ask):
        raise ValueError("Raw M1 bid/ask timestamp mismatch")
    timestamps = sorted(bid)
    if not timestamps:
        raise ValueError("Zero-row canonical M1 partition")

    def values(side: dict[int, dict[str, Any]], field: str) -> Any:
        return np.asarray([float(side[ts][field]) for ts in timestamps], dtype=np.float64)

    return BidAskBarSeries(
        pair=TradingPair(instrument),
        timeframe=Timeframe.M1,
        timestamps=np.asarray(timestamps, dtype="datetime64[ms]").astype("datetime64[ns]"),
        bid_open=values(bid, "open"),
        bid_high=values(bid, "high"),
        bid_low=values(bid, "low"),
        bid_close=values(bid, "close"),
        ask_open=values(ask, "open"),
        ask_high=values(ask, "high"),
        ask_low=values(ask, "low"),
        ask_close=values(ask, "close"),
    )


def _write_series_parquet_atomic(series: Any, path: Path) -> None:
    import pandas as pd  # type: ignore[import-untyped]

    frame = pd.DataFrame(
        {
            "timestamp": series.timestamps,
            "bid_open": series.bid_open,
            "bid_high": series.bid_high,
            "bid_low": series.bid_low,
            "bid_close": series.bid_close,
            "ask_open": series.ask_open,
            "ask_high": series.ask_high,
            "ask_low": series.ask_low,
            "ask_close": series.ask_close,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, engine="pyarrow")
    temporary.replace(path)


def _canonicalize_development_pair_month(
    root: Path,
    instrument: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    from fx_smc_bot.config import Timeframe
    from fx_smc_bot.data.bidask_resampling import resample_bidask
    from fx_smc_bot.data.daily_checkpoint import load_month_manifest
    from fx_smc_bot.data.dukascopy_node_provider import (
        _compute_checksum,
        parquet_to_bidask_series,
    )

    raw_root = root / "data" / "raw" / "gate_q0" / "dukascopy-node"
    canonical_root = root / "data" / "canonical" / "gate_q0"
    rows_by_side: dict[str, list[dict[str, Any]]] = {}
    source_hashes: dict[str, str] = {}
    for side in SIDES:
        manifest = load_month_manifest(raw_root, instrument, side, year, month)
        if manifest is None:
            raise ValueError(f"Missing {side} manifest")
        expected_days = calendar.monthrange(year, month)[1]
        if len({item.day for item in manifest.days}) != expected_days:
            raise ValueError(f"Incomplete {side} manifest")
        if any(item.status not in {"complete", "market_closed"} for item in manifest.days):
            raise ValueError(f"Unresolved {side} manifest day")
        if not manifest.compacted or manifest.compacted_rows <= 0:
            raise ValueError(f"Uncompacted or zero-row {side} month")
        path = (
            raw_root
            / instrument
            / f"price={side}"
            / f"year={year}"
            / f"month={month:02d}"
            / "data.json"
        )
        authorize_explicit_path(path.as_posix(), "development")
        if not path.is_file() or path.stat().st_size <= 2:
            raise ValueError(f"Missing or empty {side} raw file")
        if _compute_checksum(path) != manifest.compacted_checksum:
            raise ValueError(f"{side} compacted checksum mismatch")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) != manifest.compacted_rows:
            raise ValueError(f"{side} raw row-count mismatch")
        rows_by_side[side] = rows
        source_hashes[side] = _sha256(path)

    run_hashes: list[dict[str, str]] = []
    first_m1: Any = None
    first_m5: Any = None
    for _ in range(3):
        m1 = _canonical_series_from_raw_rows(
            instrument, rows_by_side["bid"], rows_by_side["ask"]
        )
        m5 = resample_bidask(m1, Timeframe.M5)
        run_hashes.append(
            {
                "m1": _series_semantic_sha256(m1),
                "m5": _series_semantic_sha256(m5),
            }
        )
        if first_m1 is None:
            first_m1 = m1
            first_m5 = m5
    deterministic = len({(row["m1"], row["m5"]) for row in run_hashes}) == 1
    if not deterministic:
        raise ValueError("Three-run canonicalization is non-deterministic")
    if first_m1.validate_invariants() or first_m5.validate_invariants():
        raise ValueError("Canonical bid/ask invariant failure")
    for series in (first_m1, first_m5):
        for field in ("open", "high", "low", "close"):
            if bool((getattr(series, f"ask_{field}") <= getattr(series, f"bid_{field}")).any()):
                raise ValueError(f"Non-positive canonical {field} spread")

    m1_path = (
        canonical_root
        / instrument
        / "timeframe=M1"
        / f"year={year}"
        / f"month={month:02d}"
        / "part.parquet"
    )
    m5_path = (
        canonical_root
        / instrument
        / "timeframe=M5"
        / f"year={year}"
        / f"month={month:02d}"
        / "part.parquet"
    )
    for path in (m1_path, m5_path):
        authorize_explicit_path(path.as_posix(), "development")
    _write_series_parquet_atomic(first_m1, m1_path)
    _write_series_parquet_atomic(first_m5, m5_path)
    m1_roundtrip = parquet_to_bidask_series(m1_path, first_m1.pair, Timeframe.M1)
    m5_roundtrip = parquet_to_bidask_series(m5_path, first_m1.pair, Timeframe.M5)
    if _series_semantic_sha256(m1_roundtrip) != run_hashes[0]["m1"]:
        raise ValueError("Canonical M1 parquet roundtrip mismatch")
    if _series_semantic_sha256(m5_roundtrip) != run_hashes[0]["m5"]:
        raise ValueError("Canonical M5 parquet roundtrip mismatch")
    return {
        "partition_id": f"{instrument}:{year:04d}-{month:02d}",
        "instrument": instrument,
        "year": year,
        "month": month,
        "source_bid_sha256": source_hashes["bid"],
        "source_ask_sha256": source_hashes["ask"],
        "m1_rows": len(first_m1),
        "m5_rows": len(first_m5),
        "m1_file_sha256": _sha256(m1_path),
        "m5_file_sha256": _sha256(m5_path),
        "m1_semantic_sha256": run_hashes[0]["m1"],
        "m5_semantic_sha256": run_hashes[0]["m5"],
        "minimum_timestamp": str(first_m1.timestamps[0]),
        "maximum_timestamp": str(first_m1.timestamps[-1]),
        "three_run_hashes": run_hashes,
        "three_run_deterministic": True,
        "parquet_roundtrip": "PASS",
        "status": "CERTIFIED",
    }


def certify_development_data(
    root: Path,
    protocol: dict[str, Any],
    *,
    workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_recovery_protocol(protocol)
    units = [
        (instrument, year, month)
        for instrument in DEVELOPMENT_INSTRUMENTS
        for year in DEVELOPMENT_YEARS
        for month in MONTHS
    ]
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="q0-canonical") as executor:
        futures = {
            executor.submit(_canonicalize_development_pair_month, root, *unit): unit
            for unit in units
        }
        for future in as_completed(futures):
            instrument, year, month = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {
                    "partition_id": f"{instrument}:{year:04d}-{month:02d}",
                    "instrument": instrument,
                    "year": year,
                    "month": month,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            records.append(record)
            if len(records) % 10 == 0 or record["status"] != "CERTIFIED":
                print(
                    json.dumps(
                        {
                            "certified_or_checked": len(records),
                            "total": len(units),
                            "latest": record["partition_id"],
                            "latest_status": record["status"],
                        }
                    ),
                    flush=True,
                )
    records.sort(key=lambda row: str(row["partition_id"]))
    local_path = root / "data" / "acquisition_state" / "gate_q0"
    local_path /= "development_certification_partitions.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    certified = [record for record in records if record["status"] == "CERTIFIED"]
    failed = [record for record in records if record["status"] != "CERTIFIED"]
    per_instrument = {
        instrument: {
            "certified_pair_months": sum(
                row["instrument"] == instrument and row["status"] == "CERTIFIED"
                for row in records
            ),
            "m1_rows": sum(
                int(row.get("m1_rows", 0))
                for row in records
                if row["instrument"] == instrument
            ),
            "m5_rows": sum(
                int(row.get("m5_rows", 0))
                for row in records
                if row["instrument"] == instrument
            ),
        }
        for instrument in DEVELOPMENT_INSTRUMENTS
    }
    dataset_hash = canonical_json_sha256(
        [
            {
                key: row[key]
                for key in (
                    "partition_id",
                    "source_bid_sha256",
                    "source_ask_sha256",
                    "m1_semantic_sha256",
                    "m5_semantic_sha256",
                )
            }
            for row in certified
        ]
    )
    certification = {
        "program_id": PROGRAM_ID,
        "protocol_hash": protocol["protocol_hash"],
        "required_pair_months": len(units),
        "certified_pair_months": len(certified),
        "unresolved_partitions": len(failed),
        "certified_zero_row_partitions": sum(
            int(row.get("m1_rows", 0)) == 0 for row in certified
        ),
        "three_run_deterministic_partitions": sum(
            bool(row.get("three_run_deterministic")) for row in certified
        ),
        "parquet_roundtrip_pass_partitions": sum(
            row.get("parquet_roundtrip") == "PASS" for row in certified
        ),
        "m1_rows": sum(int(row.get("m1_rows", 0)) for row in certified),
        "m5_rows": sum(int(row.get("m5_rows", 0)) for row in certified),
        "per_instrument": per_instrument,
        "local_partition_ledger_sha256": _sha256(local_path),
        "dataset_hash": dataset_hash,
        "failure_summary": [
            {"partition_id": row["partition_id"], "error": row.get("error", "")}
            for row in failed
        ],
        "status": "PASS"
        if len(certified) == len(units)
        and not failed
        and all(int(row["m1_rows"]) > 0 for row in certified)
        else "FAIL",
    }
    certification["certification_hash"] = canonical_json_sha256(certification)
    freeze = {
        "program_id": PROGRAM_ID,
        "dataset_id": "Q0_DEVELOPMENT_2015_2019_V1",
        "instruments": list(DEVELOPMENT_INSTRUMENTS),
        "start": "2015-01-01",
        "end": "2019-12-31",
        "source": "DUKASCOPY_TICK_BI5_BID_ASK",
        "canonical": ["UTC_M1_BID_ASK_OHLC", "M5_BID_ASK_OHLC"],
        "protocol_hash": protocol["protocol_hash"],
        "certification_hash": certification["certification_hash"],
        "dataset_hash": dataset_hash,
        "raw_or_canonical_committed": False,
        "replication_data_included": False,
        "holdout_data_included": False,
        "status": "FROZEN" if certification["status"] == "PASS" else "NOT_FROZEN",
    }
    freeze["freeze_hash"] = canonical_json_sha256(freeze)
    return certification, freeze
