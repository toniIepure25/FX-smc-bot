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
        return {"partition_id": partition.partition_id, "status": "COMPLETE", **existing}
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
                "partition_id": partition.partition_id,
                "status": "COMPLETE",
                **manifest,
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
