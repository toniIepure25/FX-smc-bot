"""Frozen clean-room acquisition for Gate Q.0-R."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.quant_safe_io import (
    MarketIOAuthorization,
    MarketPartition,
    OperationType,
    authorize_provider_request,
    create_authorization,
    partition_path,
    safe_atomic_write,
    safe_prepare_partition_directory,
    safe_read_bytes,
    safe_stat,
    safe_unlink,
)

DEVELOPMENT_INSTRUMENTS = frozenset({"AUDUSD", "NZDUSD", "USDCAD", "USDCHF"})
REPLICATION_INSTRUMENTS = frozenset(
    {"AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURJPY", "GBPJPY"}
)
SIDES = ("bid", "ask")
MAXIMUM_WORKERS = 8
PROVIDER_PAYLOAD = "provider-payload.json"
RAW_PAYLOAD = "data.json"
MANIFEST = "manifest.json"
M1_CANONICAL = "m1.parquet"
M5_CANONICAL = "m5.parquet"
CANONICAL_MANIFEST = "canonical-manifest.json"


@dataclass(frozen=True)
class AuthorizationBundle:
    provider: MarketIOAuthorization
    read: MarketIOAuthorization
    write: MarketIOAuthorization
    stat: MarketIOAuthorization
    delete: MarketIOAuthorization


def planned_partitions(
    instruments: frozenset[str], start_year: int, end_year: int
) -> frozenset[MarketPartition]:
    return frozenset(
        MarketPartition(instrument, side, year, month)
        for instrument in instruments
        for side in SIDES
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    )


def authorization_bundle(
    *,
    root: Path,
    repository_root: Path,
    instruments: frozenset[str],
    start: date,
    end: date,
    partitions: frozenset[MarketPartition],
) -> AuthorizationBundle:
    common: dict[str, Any] = {
        "root": root,
        "repository_root": repository_root,
        "instruments": instruments,
        "start": start,
        "end": end,
        "partitions": partitions,
        "forbidden_roots": (repository_root / "data",),
    }
    return AuthorizationBundle(
        provider=create_authorization(operation=OperationType.PROVIDER_REQUEST, **common),
        read=create_authorization(operation=OperationType.READ, **common),
        write=create_authorization(operation=OperationType.WRITE, **common),
        stat=create_authorization(operation=OperationType.STAT, **common),
        delete=create_authorization(operation=OperationType.DELETE, **common),
    )


def development_authorizations(root: Path, repository_root: Path) -> AuthorizationBundle:
    partitions = planned_partitions(DEVELOPMENT_INSTRUMENTS, 2015, 2019)
    return authorization_bundle(
        root=root,
        repository_root=repository_root,
        instruments=DEVELOPMENT_INSTRUMENTS,
        start=date(2015, 1, 1),
        end=date(2019, 12, 31),
        partitions=partitions,
    )


def replication_authorizations(root: Path, repository_root: Path) -> AuthorizationBundle:
    partitions = planned_partitions(REPLICATION_INSTRUMENTS, 2020, 2022)
    return authorization_bundle(
        root=root,
        repository_root=repository_root,
        instruments=REPLICATION_INSTRUMENTS,
        start=date(2020, 1, 1),
        end=date(2022, 12, 31),
        partitions=partitions,
    )


def _next_month(partition: MarketPartition) -> date:
    if partition.month == 12:
        return date(partition.year + 1, 1, 1)
    return date(partition.year, partition.month + 1, 1)


def _provider_dates(partition: MarketPartition) -> tuple[str, str]:
    return partition.first_day.isoformat(), _next_month(partition).isoformat()


def _retry_after_seconds(message: str) -> float | None:
    match = re.search(r"retry-after\D+(\d+(?:\.\d+)?)", message, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _run_provider_once(
    repository_root: Path,
    authorizations: AuthorizationBundle,
    partition: MarketPartition,
) -> tuple[list[dict[str, Any]], str, str]:
    authorize_provider_request(
        authorizations.provider,
        partition.instrument,
        partition.first_day,
        partition.last_day,
    )
    provider_path = partition_path(authorizations.write, partition, PROVIDER_PAYLOAD)
    safe_prepare_partition_directory(authorizations.write, partition)
    date_from, date_to = _provider_dates(partition)
    tool_root = repository_root / "tools" / "dukascopy-node"
    node_binary = os.environ.get("FX_Q0R_NODE_BINARY") or shutil.which("node")
    if not node_binary:
        raise RuntimeError("Node.js is unavailable; set FX_Q0R_NODE_BINARY")
    command = [
        node_binary,
        str(tool_root / "acquire.mjs"),
        "--instrument",
        partition.instrument.lower(),
        "--from",
        date_from,
        "--to",
        date_to,
        "--timeframe",
        "m1",
        "--priceType",
        partition.side,
        "--format",
        "json",
        "--outDir",
        str(provider_path.parent),
        "--outFileName",
        PROVIDER_PAYLOAD,
        "--batchSize",
        "30",
        "--retries",
        "5",
        "--pauseBetweenBatchesMs",
        "250",
        "--cache",
        "false",
    ]
    result = subprocess.run(
        command,
        cwd=tool_root,
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    error = result.stderr.strip()
    category = "PROVIDER_ERROR"
    for line in result.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "acquisition_error":
            error = str(record.get("error", "provider error"))
        if record.get("type") == "acquisition_complete":
            error = ""
    if result.returncode != 0 and not error:
        error = f"provider exit code {result.returncode}"
    if error:
        if "429" in error or "rate limit" in error.lower():
            category = "HTTP_429"
        safe_unlink(authorizations.delete, partition, PROVIDER_PAYLOAD)
        return [], error[:500], category
    try:
        payload = safe_read_bytes(authorizations.read, partition, PROVIDER_PAYLOAD)
        rows = json.loads(payload)
    finally:
        safe_unlink(authorizations.delete, partition, PROVIDER_PAYLOAD)
    if not isinstance(rows, list):
        return [], "Provider payload is not a JSON row array", "INVALID_PAYLOAD"
    return rows, "", "NONE"


def _validate_rows(partition: MarketPartition, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Zero-row monthly payload cannot be promoted")
    start_ms = int(
        datetime(
            partition.year, partition.month, 1, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    next_month = _next_month(partition)
    end_ms = int(
        datetime(
            next_month.year, next_month.month, 1, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    timestamps = [int(row["timestamp"]) for row in rows]
    if timestamps != sorted(timestamps):
        raise ValueError("Provider timestamps are not monotonic")
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Provider payload contains duplicate timestamps")
    if timestamps[0] < start_ms or timestamps[-1] >= end_ms:
        raise ValueError("Provider payload escapes its planned month")
    for row in rows:
        prices = [float(row[field]) for field in ("open", "high", "low", "close")]
        if not all(value > 0.0 for value in prices):
            raise ValueError("Provider payload contains a non-positive price")


def _existing_partition(
    authorizations: AuthorizationBundle, partition: MarketPartition
) -> dict[str, Any] | None:
    data_stat = safe_stat(authorizations.stat, partition, RAW_PAYLOAD)
    manifest_stat = safe_stat(authorizations.stat, partition, MANIFEST)
    if data_stat is None or manifest_stat is None or data_stat.st_size <= 2:
        return None
    manifest = json.loads(safe_read_bytes(authorizations.read, partition, MANIFEST))
    payload = safe_read_bytes(authorizations.read, partition, RAW_PAYLOAD)
    if manifest.get("sha256") != hashlib.sha256(payload).hexdigest():
        return None
    rows = json.loads(payload)
    _validate_rows(partition, rows)
    return manifest


def acquire_partition(
    repository_root: Path,
    authorizations: AuthorizationBundle,
    partition: MarketPartition,
) -> dict[str, Any]:
    existing = _existing_partition(authorizations, partition)
    if existing is not None:
        return {**existing, "partition_id": partition.partition_id, "status": "COMPLETE"}
    started = time.monotonic()
    failures: list[dict[str, Any]] = []
    for attempt in range(1, 6):
        rows, error, category = _run_provider_once(repository_root, authorizations, partition)
        if not error:
            _validate_rows(partition, rows)
            payload = json.dumps(rows, allow_nan=False, separators=(",", ":")).encode("utf-8")
            digest = safe_atomic_write(
                authorizations.write, partition, RAW_PAYLOAD, payload
            )
            manifest = {
                "instrument": partition.instrument,
                "side": partition.side,
                "year": partition.year,
                "month": partition.month,
                "rows": len(rows),
                "sha256": digest,
                "provider": "dukascopy-node@1.46.4",
                "status": "COMPLETE_PENDING_CERTIFICATION",
            }
            safe_atomic_write(
                authorizations.write,
                partition,
                MANIFEST,
                json.dumps(manifest, sort_keys=True).encode("utf-8"),
            )
            return {
                **manifest,
                "partition_id": partition.partition_id,
                "status": "COMPLETE",
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "failures": failures,
            }
        failures.append({"attempt": attempt, "category": category, "error": error})
        if attempt < 5:
            delay = _retry_after_seconds(error) or min(2 ** (attempt - 1), 16)
            time.sleep(delay)
    return {
        "partition_id": partition.partition_id,
        "status": "FAILED",
        "attempts": 5,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "failures": failures,
    }


def acquire_plan(
    repository_root: Path,
    authorizations: AuthorizationBundle,
    *,
    workers: int,
) -> dict[str, Any]:
    if not 1 <= workers <= MAXIMUM_WORKERS:
        raise ValueError("Worker count outside frozen bound")
    partitions = tuple(sorted(authorizations.provider.authorized_partitions))
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="q0r-acquire") as pool:
        futures = {
            pool.submit(acquire_partition, repository_root, authorizations, partition): partition
            for partition in partitions
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed = len(results)
            if completed % 10 == 0 or result["status"] != "COMPLETE":
                print(
                    json.dumps(
                        {
                            "completed": completed,
                            "total": len(partitions),
                            "latest": result["partition_id"],
                            "status": result["status"],
                        }
                    ),
                    flush=True,
                )
    complete = sum(result["status"] == "COMPLETE" for result in results)
    failures = [result for result in results if result["status"] != "COMPLETE"]
    return {
        "planned_partitions": len(partitions),
        "completed_partitions": complete,
        "failed_partitions": len(failures),
        "total_rows": sum(int(result.get("rows", 0)) for result in results),
        "workers": workers,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "failure_summaries": failures,
        "status": "COMPLETE_PENDING_CERTIFICATION" if not failures else "INCOMPLETE",
    }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_side_payload(
    payload: bytes, partition: MarketPartition
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = json.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Raw container is not a nonempty JSON row array")
    required = ("timestamp", "open", "high", "low", "close")
    if any(
        not isinstance(row, dict) or any(field not in row for field in required)
        for row in rows
    ):
        raise ValueError("Raw row schema mismatch")
    timestamps = pd.to_datetime(
        [int(row["timestamp"]) for row in rows], unit="ms", utc=True
    )
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Raw timestamps are not monotonic")
    if timestamps.has_duplicates:
        raise ValueError("Raw timestamps contain duplicates")
    if timestamps[0].date() < partition.first_day or timestamps[-1].date() > partition.last_day:
        raise ValueError("Raw timestamps escape the planned pair-month")
    if any(timestamp.second != 0 or timestamp.microsecond != 0 for timestamp in timestamps):
        raise ValueError("Raw timestamps are not normalized to UTC minute boundaries")
    data = {
        field: np.asarray([float(row[field]) for row in rows], dtype=np.float64)
        for field in ("open", "high", "low", "close")
    }
    for values in data.values():
        if not bool(np.isfinite(values).all()) or bool((values <= 0.0).any()):
            raise ValueError("Raw payload contains non-positive or non-finite prices")
    if bool((data["high"] < np.maximum(data["open"], data["close"])).any()):
        raise ValueError("Raw high violates OHLC invariants")
    if bool((data["low"] > np.minimum(data["open"], data["close"])).any()):
        raise ValueError("Raw low violates OHLC invariants")
    frame = pd.DataFrame(data, index=timestamps)
    frame.index.name = "timestamp"
    return frame, {
        "rows": len(frame),
        "first_timestamp": timestamps[0].isoformat(),
        "last_timestamp": timestamps[-1].isoformat(),
        "utc_normalized": str(timestamps.tz) == "UTC",
    }


def _combine_bid_ask(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    if not bid.index.equals(ask.index):
        raise ValueError("Raw bid/ask timestamps do not match exactly")
    combined = pd.concat((bid.add_prefix("bid_"), ask.add_prefix("ask_")), axis=1)
    for field in ("open", "high", "low", "close"):
        if bool((combined[f"ask_{field}"] <= combined[f"bid_{field}"]).any()):
            raise ValueError("Bid/ask spread is not strictly positive")
    return combined


def _aggregate_m5(m1: pd.DataFrame) -> pd.DataFrame:
    aggregations = {
        **{f"{side}_open": "first" for side in SIDES},
        **{f"{side}_high": "max" for side in SIDES},
        **{f"{side}_low": "min" for side in SIDES},
        **{f"{side}_close": "last" for side in SIDES},
    }
    m5 = m1.resample("5min", label="left", closed="left").agg(aggregations).dropna()
    if m5.empty:
        raise ValueError("M5 canonicalization produced zero rows")
    return m5


def _frame_semantic_sha256(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(frame.index.view("i8"), dtype="<i8").tobytes())
    for column in frame.columns:
        digest.update(column.encode("ascii"))
        digest.update(np.asarray(frame[column], dtype="<f8").tobytes())
    return digest.hexdigest()


def _frame_to_parquet(frame: pd.DataFrame) -> bytes:
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    output = frame.reset_index()
    table = pa.Table.from_pandas(output, preserve_index=False)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


def _raw_manifest(
    authorizations: AuthorizationBundle, partition: MarketPartition, payload: bytes
) -> dict[str, Any]:
    manifest = json.loads(safe_read_bytes(authorizations.read, partition, MANIFEST))
    if manifest.get("instrument") != partition.instrument or manifest.get("side") != partition.side:
        raise ValueError("Raw manifest instrument or side mismatch")
    if manifest.get("year") != partition.year or manifest.get("month") != partition.month:
        raise ValueError("Raw manifest date mismatch")
    if manifest.get("sha256") != _sha256(payload):
        raise ValueError("Raw manifest checksum mismatch")
    if int(manifest.get("rows", 0)) <= 0:
        raise ValueError("Raw manifest certifies zero rows")
    return manifest


def _existing_canonical(
    authorizations: AuthorizationBundle,
    partition: MarketPartition,
    source_hashes: dict[str, str],
) -> dict[str, Any] | None:
    if safe_stat(authorizations.stat, partition, CANONICAL_MANIFEST) is None:
        return None
    manifest = json.loads(
        safe_read_bytes(authorizations.read, partition, CANONICAL_MANIFEST)
    )
    if manifest.get("source_sha256") != source_hashes:
        return None
    m1_payload = safe_read_bytes(authorizations.read, partition, M1_CANONICAL)
    m5_payload = safe_read_bytes(authorizations.read, partition, M5_CANONICAL)
    if manifest.get("m1_file_sha256") != _sha256(m1_payload):
        return None
    if manifest.get("m5_file_sha256") != _sha256(m5_payload):
        return None
    return manifest


def certify_pair_month(
    authorizations: AuthorizationBundle,
    instrument: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    bid_partition = MarketPartition(instrument, "bid", year, month)
    ask_partition = MarketPartition(instrument, "ask", year, month)
    bid_payload = safe_read_bytes(authorizations.read, bid_partition, RAW_PAYLOAD)
    ask_payload = safe_read_bytes(authorizations.read, ask_partition, RAW_PAYLOAD)
    bid_manifest = _raw_manifest(authorizations, bid_partition, bid_payload)
    ask_manifest = _raw_manifest(authorizations, ask_partition, ask_payload)
    source_hashes = {"ask": _sha256(ask_payload), "bid": _sha256(bid_payload)}
    existing = _existing_canonical(authorizations, bid_partition, source_hashes)
    if existing is not None:
        return {**existing, "status": "CERTIFIED"}

    run_hashes: list[dict[str, str]] = []
    first_m1: pd.DataFrame | None = None
    first_m5: pd.DataFrame | None = None
    side_metadata: dict[str, dict[str, Any]] = {}
    for _ in range(3):
        bid, bid_metadata = _parse_side_payload(bid_payload, bid_partition)
        ask, ask_metadata = _parse_side_payload(ask_payload, ask_partition)
        m1 = _combine_bid_ask(bid, ask)
        m5 = _aggregate_m5(m1)
        run_hashes.append(
            {"m1": _frame_semantic_sha256(m1), "m5": _frame_semantic_sha256(m5)}
        )
        if first_m1 is None:
            first_m1, first_m5 = m1, m5
            side_metadata = {"ask": ask_metadata, "bid": bid_metadata}
    if len({(run["m1"], run["m5"]) for run in run_hashes}) != 1:
        raise ValueError("Three-run canonical semantic parity failed")
    assert first_m1 is not None and first_m5 is not None
    m1_payload = _frame_to_parquet(first_m1)
    m5_payload = _frame_to_parquet(first_m5)
    m1_file_hash = safe_atomic_write(
        authorizations.write, bid_partition, M1_CANONICAL, m1_payload
    )
    m5_file_hash = safe_atomic_write(
        authorizations.write, bid_partition, M5_CANONICAL, m5_payload
    )
    manifest = {
        "instrument": instrument,
        "year": year,
        "month": month,
        "source_rows": {"ask": int(ask_manifest["rows"]), "bid": int(bid_manifest["rows"])},
        "source_sha256": source_hashes,
        "m1_rows": len(first_m1),
        "m5_rows": len(first_m5),
        "m1_semantic_sha256": run_hashes[0]["m1"],
        "m5_semantic_sha256": run_hashes[0]["m5"],
        "m1_file_sha256": m1_file_hash,
        "m5_file_sha256": m5_file_hash,
        "side_metadata": side_metadata,
        "three_run_semantic_parity": True,
        "utc_session_basis": "UTC_WITH_IANA_SESSION_CONVERSION_AT_SIGNAL_TIME",
        "status": "CERTIFIED",
    }
    safe_atomic_write(
        authorizations.write,
        bid_partition,
        CANONICAL_MANIFEST,
        json.dumps(manifest, allow_nan=False, sort_keys=True).encode("utf-8"),
    )
    return manifest


def certify_development_plan(
    authorizations: AuthorizationBundle, *, workers: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 1 <= workers <= MAXIMUM_WORKERS:
        raise ValueError("Certification worker count outside frozen bound")
    pair_months = tuple(
        (instrument, year, month)
        for instrument in sorted(DEVELOPMENT_INSTRUMENTS)
        for year in range(2015, 2020)
        for month in range(1, 13)
    )
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="q0r-certify") as pool:
        futures = {
            pool.submit(certify_pair_month, authorizations, *pair_month): pair_month
            for pair_month in pair_months
        }
        for future in as_completed(futures):
            instrument, year, month = futures[future]
            try:
                record = future.result()
                records.append(record)
            except Exception as exc:
                failures.append(
                    {
                        "pair_month": f"{instrument}:{year:04d}-{month:02d}",
                        "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    }
                )
            completed = len(records) + len(failures)
            if completed % 10 == 0 or failures:
                print(
                    json.dumps(
                        {
                            "certified": len(records),
                            "checked": completed,
                            "failed": len(failures),
                            "total": len(pair_months),
                        }
                    ),
                    flush=True,
                )
    records.sort(key=lambda row: (str(row["instrument"]), int(row["year"]), int(row["month"])))
    zero_rows = sum(
        int(record["m1_rows"]) == 0 or int(record["m5_rows"]) == 0 for record in records
    )
    certified = len(records)
    status = "PASS" if certified == len(pair_months) and not failures and zero_rows == 0 else "FAIL"
    certification = {
        "pair_months_planned": len(pair_months),
        "pair_months_certified": certified,
        "missing": len(pair_months) - certified,
        "failed": len(failures),
        "successful_zero_row": zero_rows,
        "total_m1_rows": sum(int(record["m1_rows"]) for record in records),
        "total_m5_rows": sum(int(record["m5_rows"]) for record in records),
        "checks": [
            "instrument_and_side_identity",
            "date_containment",
            "container_integrity",
            "nonzero_payload",
            "deterministic_parsing",
            "utc_normalization",
            "monotonicity",
            "duplicate_consistency",
            "positive_finite_prices",
            "bid_ask_spread_validity",
            "m1_deterministic_canonicalization",
            "m5_deterministic_aggregation",
            "dst_session_basis",
            "manifest_consistency",
            "three_run_canonical_parity",
        ],
        "failures": failures,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "status": status,
    }
    freeze_payload = [
        {
            "instrument": record["instrument"],
            "year": record["year"],
            "month": record["month"],
            "source_sha256": record["source_sha256"],
            "m1_semantic_sha256": record["m1_semantic_sha256"],
            "m5_semantic_sha256": record["m5_semantic_sha256"],
            "m1_rows": record["m1_rows"],
            "m5_rows": record["m5_rows"],
        }
        for record in records
    ]
    freeze = {
        "dataset_freeze_id": "FX_QUANT_POLARITY_DEVELOPMENT_2015_2019_V2",
        "pair_month_count": len(freeze_payload),
        "dataset_manifest_sha256": _sha256(
            json.dumps(
                freeze_payload,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ),
        "raw_or_canonical_committed": False,
        "three_run_canonical_parity": status == "PASS",
        "status": status,
    }
    return certification, freeze
