"""Gate F.0 clean-room development market-data orchestration.

The module deliberately separates planning, provider execution, and local
certification.  Every provider callback and every local file operation is
scoped by ``classical_factor_safe_io`` before it can cross an I/O boundary.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, Final, Protocol, TypeVar
from zoneinfo import ZoneInfo

from fx_smc_bot.research.classical_factor_safe_io import (
    FROZEN_CURRENCIES,
    FROZEN_INSTRUMENTS,
    DataProvider,
    IOAuthorization,
    MarketPartition,
    OperationType,
    ProviderRequest,
    create_authorization,
    safe_atomic_write,
    safe_prepare_partition_directory,
    safe_provider_request,
    safe_read_bytes,
    safe_stat,
    safe_unlink,
)

PROGRAM_ID: Final = "FX_CLASSICAL_RISK_PREMIA_V1"
LINEAGE_ID: Final = "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1"
DEVELOPMENT_START: Final = date(2010, 1, 1)
DEVELOPMENT_END: Final = date(2016, 12, 31)
DEVELOPMENT_YEARS: Final = tuple(range(2010, 2017))
INSTRUMENT_ORDER: Final = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
SIDES: Final = ("bid", "ask")
MONTHS: Final = tuple(range(1, 13))
EXPECTED_PARTITION_TASKS: Final = 1_680
EXPECTED_PAIR_MONTHS: Final = 840
MAXIMUM_WORKERS: Final = 8
MINIMUM_FREE_SPACE_RESERVE_BYTES: Final = 10 * 1024**3
NODE_PACKAGE: Final = "dukascopy-node"
NODE_PACKAGE_VERSION: Final = "1.46.4"
NODE_WRAPPER_RELATIVE: Final = Path("tools") / "dukascopy-node" / "acquire.mjs"

F0_PROVIDER_PAYLOAD: Final = "f0-provider-payload.json"
F0_RAW_M1: Final = "f0-raw-m1.json"
F0_RAW_MANIFEST: Final = "f0-raw-manifest.json"
F0_CHECKPOINT: Final = "f0-checkpoint.json"
F0_CANONICAL_M1: Final = "f0-canonical-m1.json"
F0_CANONICAL_M5: Final = "f0-canonical-m5.json"
F0_DAILY_FRAGMENTS: Final = "f0-daily-fragments.json"
F0_CANONICAL_DAILY: Final = "f0-canonical-daily.json"
F0_CERTIFICATION: Final = "f0-certification.json"
F0_DAILY_ASSEMBLY_CERTIFICATION: Final = "f0-daily-assembly-certification.json"

_NY_ZONE: Final = ZoneInfo("America/New_York")
_NY_CLOSE: Final = datetime_time(17, 0)
_OHLC_FIELDS: Final = ("open", "high", "low", "close")
_COMBINED_FIELDS: Final = tuple(f"{side}_{field}" for side in SIDES for field in _OHLC_FIELDS)

RunResult = subprocess.CompletedProcess[str]
SubprocessRunner = Callable[..., RunResult]
T = TypeVar("T")


class DiskUsageSnapshot(Protocol):
    """Minimum disk-usage surface required by the storage guard."""

    @property
    def free(self) -> int: ...


DiskUsageProbe = Callable[[Path], DiskUsageSnapshot]


def _disk_usage(root: Path) -> DiskUsageSnapshot:
    return shutil.disk_usage(root)


@dataclass(frozen=True)
class AuthorizationBundle:
    """Operation-specific capabilities over the same frozen partition set."""

    provider: IOAuthorization
    read: IOAuthorization
    write: IOAuthorization
    stat: IOAuthorization
    delete: IOAuthorization


@dataclass(frozen=True)
class OHLCBar:
    """One normalized UTC bar; ``timestamp_ms`` denotes the bar open."""

    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def validate_development_interval(start: date, end: date) -> None:
    """Reject every development command not using the complete frozen interval."""
    if start != DEVELOPMENT_START or end != DEVELOPMENT_END:
        raise ValueError("Gate F.0 development commands require exactly 2010-01-01..2016-12-31")


def development_partitions() -> tuple[MarketPartition, ...]:
    """Return the immutable 1,680 instrument-side-month task plan."""
    partitions = tuple(
        MarketPartition(
            instrument=instrument,
            side=side,
            start=date(year, month, 1),
            end=_month_end(year, month),
        )
        for instrument in INSTRUMENT_ORDER
        for side in SIDES
        for year in DEVELOPMENT_YEARS
        for month in MONTHS
    )
    if len(partitions) != EXPECTED_PARTITION_TASKS or len(set(partitions)) != len(partitions):
        raise AssertionError("Gate F.0 development plan is not exactly 1,680 unique tasks")
    return partitions


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def development_plan(
    *, start: date = DEVELOPMENT_START, end: date = DEVELOPMENT_END
) -> dict[str, Any]:
    validate_development_interval(start, end)
    tasks = [
        {
            "end": partition.end.isoformat(),
            "instrument": partition.instrument,
            "partition_id": partition.partition_id,
            "side": partition.side,
            "start": partition.start.isoformat(),
        }
        for partition in development_partitions()
    ]
    plan: dict[str, Any] = {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "stage": "DEVELOPMENT_MARKET_DATA",
        "interval": {"start": start.isoformat(), "end": end.isoformat()},
        "instruments": list(INSTRUMENT_ORDER),
        "sides": list(SIDES),
        "pair_months": EXPECTED_PAIR_MONTHS,
        "partition_tasks": len(tasks),
        "maximum_workers": MAXIMUM_WORKERS,
        "provider": {
            "name": NODE_PACKAGE,
            "version": NODE_PACKAGE_VERSION,
            "wrapper": NODE_WRAPPER_RELATIVE.as_posix(),
            "timeframe": "m1",
            "format": "json",
            "pause_between_batches_ms": 200,
            "cache": False,
        },
        "canonicalization": {
            "source": "M1_BID_ASK_OHLC",
            "derived": ["M5_BID_ASK_OHLC", "DAILY_BID_ASK_OHLC"],
            "aggregation_chain": "M1_TO_CERTIFIED_M5_TO_CROSS_MONTH_DAILY",
            "m5_complete_bucket_minutes": 5,
            "incomplete_m5_bucket_policy": "EXCLUDE_WITH_RECORDED_REASON_NO_FILL",
            "pair_month_daily_scope": "FRAGMENTS_ONLY",
            "cross_month_timestamp_deduplication": "STRICT_REJECTION",
            "daily_close": "17:00 America/New_York",
            "daily_final_bar": "EXACT_M5_PRECEDING_CLOSE",
            "forward_fill": False,
        },
        "storage": {
            "format": "JSON_LOCAL_ONLY",
            "resource_prefix": "f0-",
            "foreign_payload_or_checkpoint_reuse": False,
            "minimum_free_reserve_bytes": MINIMUM_FREE_SPACE_RESERVE_BYTES,
        },
        "tasks": tasks,
        "status": "FROZEN_DRY_RUN_PLAN",
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def verify_development_plan(plan: Mapping[str, Any]) -> None:
    payload = dict(plan)
    digest = payload.pop("plan_sha256", None)
    if digest != canonical_sha256(payload):
        raise ValueError("Gate F.0 development plan hash mismatch")
    if payload.get("partition_tasks") != EXPECTED_PARTITION_TASKS:
        raise ValueError("Gate F.0 development plan must contain exactly 1,680 tasks")
    if payload.get("interval") != {"start": "2010-01-01", "end": "2016-12-31"}:
        raise ValueError("Gate F.0 development plan interval mismatch")
    task_ids = [str(task["partition_id"]) for task in payload.get("tasks", [])]
    if len(task_ids) != EXPECTED_PARTITION_TASKS or len(set(task_ids)) != len(task_ids):
        raise ValueError("Gate F.0 development task IDs are incomplete or duplicated")


def require_storage_reserve(
    root: Path,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, int | str]:
    """Fail before a batch boundary unless the exact clean root has 10 GiB free."""
    usage = usage_probe(root)
    free = int(usage.free)
    if free < MINIMUM_FREE_SPACE_RESERVE_BYTES:
        raise RuntimeError(
            "Gate F.0 clean-room root has less than the required 10 GiB free reserve"
        )
    return {
        "checked_root": str(root),
        "free_bytes": free,
        "required_reserve_bytes": MINIMUM_FREE_SPACE_RESERVE_BYTES,
        "status": "PASS",
    }


def development_authorizations(root: Path, repository_root: Path) -> AuthorizationBundle:
    partitions = frozenset(development_partitions())
    common: dict[str, Any] = {
        "root": root,
        "repository_root": repository_root,
        "instruments": frozenset(INSTRUMENT_ORDER),
        "currencies": FROZEN_CURRENCIES,
        "start": DEVELOPMENT_START,
        "end": DEVELOPMENT_END,
        "partitions": partitions,
        "provider": DataProvider.DUKASCOPY_BI5_BID_ASK,
        "forbidden_roots": (repository_root / "data",),
    }
    return AuthorizationBundle(
        provider=create_authorization(operation=OperationType.PROVIDER_REQUEST, **common),
        read=create_authorization(operation=OperationType.READ, **common),
        write=create_authorization(operation=OperationType.WRITE, **common),
        stat=create_authorization(operation=OperationType.STAT, **common),
        delete=create_authorization(operation=OperationType.DELETE, **common),
    )


def _parse_timestamp_ms(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean timestamp is invalid")
    if isinstance(value, int):
        timestamp_ms = value
    elif isinstance(value, float) and value.is_integer():
        timestamp_ms = int(value)
    elif isinstance(value, str):
        try:
            timestamp_ms = int(value)
        except ValueError:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("String timestamps must include an offset") from None
            timestamp_ms = int(parsed.timestamp() * 1000)
    else:
        raise ValueError("Unsupported timestamp type")
    if timestamp_ms < 0:
        raise ValueError("Negative timestamp is invalid")
    return timestamp_ms


def parse_m1_payload(payload: bytes, partition: MarketPartition) -> tuple[OHLCBar, ...]:
    decoded = json.loads(payload)
    if not isinstance(decoded, list) or not decoded:
        raise ValueError("F0 provider payload must be a nonempty JSON row array")
    bars: list[OHLCBar] = []
    for raw in decoded:
        if not isinstance(raw, dict) or any(
            field not in raw for field in ("timestamp", *_OHLC_FIELDS)
        ):
            raise ValueError("F0 provider row schema mismatch")
        values = tuple(float(raw[field]) for field in _OHLC_FIELDS)
        if not all(value > 0.0 and value < float("inf") for value in values):
            raise ValueError("F0 provider row contains a non-positive or non-finite price")
        bar = OHLCBar(_parse_timestamp_ms(raw["timestamp"]), *values)
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise ValueError("F0 provider row violates OHLC invariants")
        bars.append(bar)
    timestamps = [bar.timestamp_ms for bar in bars]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("F0 provider timestamps must be unique and increasing")
    first = datetime.fromtimestamp(timestamps[0] / 1000, tz=UTC).date()
    last = datetime.fromtimestamp(timestamps[-1] / 1000, tz=UTC).date()
    if first < partition.start or last > partition.end:
        raise ValueError("F0 provider payload escapes its planned month")
    if any(timestamp % 60_000 != 0 for timestamp in timestamps):
        raise ValueError("F0 M1 timestamps must be on UTC minute boundaries")
    return tuple(bars)


def _bar_as_dict(bar: OHLCBar) -> dict[str, int | float]:
    return {
        "timestamp": bar.timestamp_ms,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
    }


def _combine_sides(bid: Sequence[OHLCBar], ask: Sequence[OHLCBar]) -> list[dict[str, Any]]:
    if [bar.timestamp_ms for bar in bid] != [bar.timestamp_ms for bar in ask]:
        raise ValueError("F0 bid and ask timestamps must match exactly")
    combined: list[dict[str, Any]] = []
    for bid_bar, ask_bar in zip(bid, ask, strict=True):
        row: dict[str, Any] = {"timestamp": bid_bar.timestamp_ms}
        for side, bar in (("bid", bid_bar), ("ask", ask_bar)):
            for field in _OHLC_FIELDS:
                row[f"{side}_{field}"] = getattr(bar, field)
        if any(row[f"ask_{field}"] <= row[f"bid_{field}"] for field in _OHLC_FIELDS):
            raise ValueError("F0 bid/ask spread must be strictly positive")
        combined.append(row)
    return combined


def _aggregate_group(rows: Sequence[Mapping[str, Any]], label: int | str) -> dict[str, Any]:
    first, last = rows[0], rows[-1]
    result: dict[str, Any] = {"timestamp" if isinstance(label, int) else "fx_close_date": label}
    for side in SIDES:
        result[f"{side}_open"] = float(first[f"{side}_open"])
        result[f"{side}_high"] = max(float(row[f"{side}_high"]) for row in rows)
        result[f"{side}_low"] = min(float(row[f"{side}_low"]) for row in rows)
        result[f"{side}_close"] = float(last[f"{side}_close"])
    return result


def aggregate_m5(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Certify only M5 buckets containing their exact five consecutive M1 bars."""
    timestamps = [int(row["timestamp"]) for row in rows]
    if timestamps != sorted(timestamps):
        raise ValueError("F0 M1 rows must be increasing before M5 aggregation")
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("F0 M1 rows must be unique before M5 aggregation")

    groups: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        timestamp = int(row["timestamp"])
        bucket = timestamp - timestamp % 300_000
        groups.setdefault(bucket, []).append(row)

    certified: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for bucket in sorted(groups):
        observed = [int(row["timestamp"]) for row in groups[bucket]]
        expected = [bucket + offset * 60_000 for offset in range(5)]
        if observed != expected:
            incomplete.append(
                {
                    "bucket_timestamp": bucket,
                    "expected_timestamps": expected,
                    "observed_timestamps": observed,
                    "missing_timestamps": [value for value in expected if value not in observed],
                    "reason": "INCOMPLETE_M5_BUCKET_MISSING_CONSECUTIVE_M1_NO_FILL",
                }
            )
            continue
        certified.append(_aggregate_group(groups[bucket], bucket))
    return {
        "certified_bars": certified,
        "incomplete_buckets": incomplete,
        "status": (
            "CERTIFIED_ALL_OBSERVED_M5_BUCKETS"
            if not incomplete
            else "CERTIFIED_M5_WITH_EXPLICIT_INCOMPLETE_BUCKET_EXCLUSIONS"
        ),
    }


def fx_close_date(timestamp_ms: int) -> str:
    """Label a bar by the New York 17:00 close ending its FX day."""
    local = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).astimezone(_NY_ZONE)
    close_date = local.date() if local.time() < _NY_CLOSE else local.date() + timedelta(days=1)
    return close_date.isoformat()


def daily_fragments_from_certified_m5(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve pair-month fragments without claiming complete FX daily bars."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        timestamp = int(row["timestamp"])
        if timestamp % 300_000 != 0:
            raise ValueError("Daily fragments require certified M5 timestamps")
        label = fx_close_date(timestamp)
        groups.setdefault(label, []).append(dict(row))
    return [
        {
            "fx_close_date": label,
            "m5_bars": groups[label],
            "status": "PAIR_MONTH_FRAGMENT_NOT_DAILY_COMPLETENESS_CLAIM",
        }
        for label in sorted(groups)
    ]


def _final_m5_before_ny_close(label: str) -> int:
    close_day = date.fromisoformat(label)
    local_close = datetime.combine(close_day, _NY_CLOSE, tzinfo=_NY_ZONE)
    return int((local_close.astimezone(UTC) - timedelta(minutes=5)).timestamp() * 1000)


def assemble_daily_from_m5_fragments(
    fragments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assemble cross-month daily bars from certified M5 with strict uniqueness."""
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    labels_by_timestamp: dict[int, str] = {}
    for fragment in fragments:
        label = str(fragment["fx_close_date"])
        if fragment.get("status") != "PAIR_MONTH_FRAGMENT_NOT_DAILY_COMPLETENESS_CLAIM":
            raise ValueError("F0 daily assembly requires an explicit pair-month fragment")
        raw_rows = fragment.get("m5_bars")
        if not isinstance(raw_rows, list):
            raise ValueError("F0 daily fragment must contain an M5 row list")
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise ValueError("F0 daily fragment contains an invalid M5 row")
            row = dict(raw_row)
            timestamp = int(row["timestamp"])
            if timestamp % 300_000 != 0:
                raise ValueError("F0 daily assembly accepts certified M5 timestamps only")
            if fx_close_date(timestamp) != label:
                raise ValueError("F0 daily fragment label does not match its M5 timestamp")
            if timestamp in rows_by_timestamp:
                raise ValueError("F0 cross-month M5 timestamps must be strictly unique")
            rows_by_timestamp[timestamp] = row
            labels_by_timestamp[timestamp] = label

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for timestamp in sorted(rows_by_timestamp):
        groups.setdefault(labels_by_timestamp[timestamp], []).append(rows_by_timestamp[timestamp])

    daily: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for label in sorted(groups):
        observed_final = int(groups[label][-1]["timestamp"])
        expected_final = _final_m5_before_ny_close(label)
        if observed_final != expected_final:
            incomplete.append(
                {
                    "fx_close_date": label,
                    "expected_final_m5_timestamp": expected_final,
                    "observed_final_m5_timestamp": observed_final,
                    "reason": "MISSING_EXACT_FINAL_CERTIFIED_M5_BEFORE_1700_NEW_YORK_NO_FILL",
                }
            )
            continue
        daily.append(_aggregate_group(groups[label], label))
    return {
        "certified_daily_bars": daily,
        "incomplete_days": incomplete,
        "status": (
            "CERTIFIED_DAILY_FROM_CROSS_MONTH_M5"
            if not incomplete
            else "CERTIFIED_DAILY_WITH_EXPLICIT_INCOMPLETE_DAY_EXCLUSIONS"
        ),
    }


def aggregate_daily(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate daily only through the certified-M5 fragment contract."""
    return assemble_daily_from_m5_fragments(daily_fragments_from_certified_m5(rows))


def canonicalize_pair_month(
    bid_payload: bytes,
    ask_payload: bytes,
    bid_partition: MarketPartition,
    ask_partition: MarketPartition,
) -> dict[str, Any]:
    if bid_partition.side != "bid" or ask_partition.side != "ask":
        raise ValueError("F0 canonicalization requires bid then ask partitions")
    if (
        bid_partition.instrument != ask_partition.instrument
        or bid_partition.start != ask_partition.start
        or bid_partition.end != ask_partition.end
    ):
        raise ValueError("F0 bid/ask partitions must describe the same pair-month")
    bid = parse_m1_payload(bid_payload, bid_partition)
    ask = parse_m1_payload(ask_payload, ask_partition)
    m1 = _combine_sides(bid, ask)
    m5_result = aggregate_m5(m1)
    m5 = m5_result["certified_bars"]
    return {
        "m1": m1,
        "m5": m5,
        "m5_certification": {
            "incomplete_buckets": m5_result["incomplete_buckets"],
            "status": m5_result["status"],
        },
        "daily_fragments": daily_fragments_from_certified_m5(m5),
    }


def _verify_pinned_node_wrapper(repository_root: Path) -> Path:
    tool_root = repository_root / "tools" / "dukascopy-node"
    package = json.loads((tool_root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((tool_root / "package-lock.json").read_text(encoding="utf-8"))
    if package.get("dependencies", {}).get(NODE_PACKAGE) != NODE_PACKAGE_VERSION:
        raise RuntimeError("Gate F.0 requires dukascopy-node exactly 1.46.4")
    locked = lock.get("packages", {}).get("node_modules/dukascopy-node", {}).get("version")
    if locked != NODE_PACKAGE_VERSION:
        raise RuntimeError("Gate F.0 package lock does not pin dukascopy-node 1.46.4")
    wrapper = repository_root / NODE_WRAPPER_RELATIVE
    if not wrapper.is_file():
        raise RuntimeError("Pinned Gate F.0 Node wrapper is missing")
    return wrapper


def _node_command(
    repository_root: Path,
    partition: MarketPartition,
    output_directory: Path,
) -> list[str]:
    wrapper = _verify_pinned_node_wrapper(repository_root)
    node_binary = os.environ.get("FX_F0_NODE_BINARY", "node")
    # The timestamp remains inside the frozen year, including December 2016.
    inclusive_end = f"{partition.end.isoformat()}T23:59:59.999Z"
    return [
        node_binary,
        str(wrapper),
        "--instrument",
        partition.instrument.lower(),
        "--from",
        partition.start.isoformat(),
        "--to",
        inclusive_end,
        "--timeframe",
        "m1",
        "--priceType",
        partition.side,
        "--format",
        "json",
        "--outDir",
        str(output_directory),
        "--outFileName",
        F0_PROVIDER_PAYLOAD,
        "--batchSize",
        "30",
        "--retries",
        "5",
        "--pauseBetweenBatchesMs",
        "200",
        "--cache",
        "false",
    ]


def _raw_manifest_is_current(
    authorizations: AuthorizationBundle,
    partition: MarketPartition,
) -> bool:
    if safe_stat(authorizations.stat, partition, F0_RAW_M1) is None:
        return False
    if safe_stat(authorizations.stat, partition, F0_RAW_MANIFEST) is None:
        return False
    payload = safe_read_bytes(authorizations.read, partition, F0_RAW_M1)
    manifest = json.loads(safe_read_bytes(authorizations.read, partition, F0_RAW_MANIFEST))
    return bool(
        manifest.get("program_id") == PROGRAM_ID
        and manifest.get("partition_id") == partition.partition_id
        and manifest.get("payload_sha256") == hashlib.sha256(payload).hexdigest()
        and manifest.get("status") == "F0_RAW_COMPLETE"
    )


def _acquire_partition(
    repository_root: Path,
    authorizations: AuthorizationBundle,
    partition: MarketPartition,
    runner: SubprocessRunner,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, Any]:
    if _raw_manifest_is_current(authorizations, partition):
        return {"partition_id": partition.partition_id, "status": "F0_RAW_COMPLETE_REUSED"}
    request = ProviderRequest(
        provider=DataProvider.DUKASCOPY_BI5_BID_ASK,
        partition=partition,
        start=partition.start,
        end=partition.end,
        resource_name=F0_PROVIDER_PAYLOAD,
    )

    def run_after_safe_provider_request(validated: ProviderRequest) -> RunResult:
        if validated != request:
            raise RuntimeError("Validated Gate F.0 provider request changed unexpectedly")
        require_storage_reserve(authorizations.provider.clean_room_root, usage_probe)
        output_directory = safe_prepare_partition_directory(authorizations.write, partition)
        command = _node_command(repository_root, partition, output_directory)
        return runner(
            command,
            cwd=repository_root / "tools" / "dukascopy-node",
            capture_output=True,
            text=True,
            timeout=1_200,
            check=False,
        )

    started = time.monotonic()
    result = safe_provider_request(
        authorizations.provider,
        request,
        run_after_safe_provider_request,
    )
    if result.returncode != 0:
        safe_unlink(authorizations.delete, partition, F0_PROVIDER_PAYLOAD)
        raise RuntimeError(f"Pinned Node provider failed: {result.stderr.strip()[:500]}")
    try:
        provider_payload = safe_read_bytes(authorizations.read, partition, F0_PROVIDER_PAYLOAD)
        bars = parse_m1_payload(provider_payload, partition)
        normalized = canonical_json_bytes([_bar_as_dict(bar) for bar in bars])
        payload_hash = safe_atomic_write(
            authorizations.write,
            partition,
            F0_RAW_M1,
            normalized,
        )
        manifest = {
            "program_id": PROGRAM_ID,
            "lineage_id": LINEAGE_ID,
            "partition_id": partition.partition_id,
            "provider": f"{NODE_PACKAGE}@{NODE_PACKAGE_VERSION}",
            "rows": len(bars),
            "payload_sha256": payload_hash,
            "status": "F0_RAW_COMPLETE",
        }
        manifest_hash = safe_atomic_write(
            authorizations.write,
            partition,
            F0_RAW_MANIFEST,
            canonical_json_bytes(manifest),
        )
        checkpoint = {
            "program_id": PROGRAM_ID,
            "partition_id": partition.partition_id,
            "f0_raw_manifest_sha256": manifest_hash,
            "status": "F0_CHECKPOINT_RAW_COMPLETE",
        }
        safe_atomic_write(
            authorizations.write,
            partition,
            F0_CHECKPOINT,
            canonical_json_bytes(checkpoint),
        )
    finally:
        safe_unlink(authorizations.delete, partition, F0_PROVIDER_PAYLOAD)
    return {
        "partition_id": partition.partition_id,
        "rows": len(bars),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "status": "F0_RAW_COMPLETE",
    }


def _validate_workers(workers: int) -> None:
    if not 1 <= workers <= MAXIMUM_WORKERS:
        raise ValueError("Gate F.0 workers must be between 1 and 8")


def _collect_futures_fail_fast(futures: Mapping[Future[T], object]) -> list[T]:
    """Collect results and cancel work not yet started after the first failure."""
    results: list[T] = []
    try:
        for future in as_completed(futures):
            results.append(future.result())
    except BaseException:
        for pending in futures:
            if not pending.done():
                pending.cancel()
        raise
    return results


def acquire_development_market(
    root: Path,
    repository_root: Path,
    *,
    workers: int = MAXIMUM_WORKERS,
    execute_provider: bool = False,
    runner: SubprocessRunner = subprocess.run,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, Any]:
    """Plan by default; provider execution requires ``execute_provider=True``."""
    _validate_workers(workers)
    plan = development_plan()
    if not execute_provider:
        return {
            "program_id": PROGRAM_ID,
            "stage": "acquire-development-market",
            "dry_run": True,
            "provider_requests_sent": 0,
            "planned_partitions": EXPECTED_PARTITION_TASKS,
            "workers": workers,
            "plan_sha256": plan["plan_sha256"],
            "status": "DRY_RUN_NO_PROVIDER_ACCESS",
        }
    authorizations = development_authorizations(root, repository_root)
    require_storage_reserve(authorizations.provider.clean_room_root, usage_probe)
    partitions = development_partitions()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="f0-market")
    try:
        futures = {
            pool.submit(
                _acquire_partition,
                repository_root,
                authorizations,
                partition,
                runner,
                usage_probe,
            ): partition
            for partition in partitions
        }
        results = _collect_futures_fail_fast(futures)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    completed = sum(str(item["status"]).startswith("F0_RAW_COMPLETE") for item in results)
    return {
        "program_id": PROGRAM_ID,
        "stage": "acquire-development-market",
        "dry_run": False,
        "provider_execution_authorized": True,
        "planned_partitions": EXPECTED_PARTITION_TASKS,
        "completed_partitions": completed,
        "workers": workers,
        "plan_sha256": plan["plan_sha256"],
        "status": "F0_RAW_COMPLETE"
        if completed == EXPECTED_PARTITION_TASKS
        else "F0_RAW_INCOMPLETE",
    }


def _certify_pair_month(
    authorizations: AuthorizationBundle,
    instrument: str,
    year: int,
    month: int,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, Any]:
    require_storage_reserve(authorizations.read.clean_room_root, usage_probe)
    bid_partition = MarketPartition(
        instrument, "bid", date(year, month, 1), _month_end(year, month)
    )
    ask_partition = MarketPartition(
        instrument, "ask", date(year, month, 1), _month_end(year, month)
    )
    bid_payload = safe_read_bytes(authorizations.read, bid_partition, F0_RAW_M1)
    ask_payload = safe_read_bytes(authorizations.read, ask_partition, F0_RAW_M1)
    source_hashes = {
        "ask": hashlib.sha256(ask_payload).hexdigest(),
        "bid": hashlib.sha256(bid_payload).hexdigest(),
    }
    runs = [
        canonicalize_pair_month(bid_payload, ask_payload, bid_partition, ask_partition)
        for _ in range(3)
    ]
    run_hashes = [canonical_sha256(run) for run in runs]
    if len(set(run_hashes)) != 1:
        raise ValueError("Gate F.0 three-run canonicalization parity failed")
    canonical = runs[0]
    m1_hash = safe_atomic_write(
        authorizations.write,
        bid_partition,
        F0_CANONICAL_M1,
        canonical_json_bytes(canonical["m1"]),
    )
    m5_hash = safe_atomic_write(
        authorizations.write,
        bid_partition,
        F0_CANONICAL_M5,
        canonical_json_bytes(canonical["m5"]),
    )
    daily_fragment_hash = safe_atomic_write(
        authorizations.write,
        bid_partition,
        F0_DAILY_FRAGMENTS,
        canonical_json_bytes(canonical["daily_fragments"]),
    )
    m5_incomplete = canonical["m5_certification"]["incomplete_buckets"]
    certification = {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "pair_month": f"{instrument}:{year:04d}-{month:02d}",
        "source_sha256": source_hashes,
        "rows": {name: len(canonical[name]) for name in ("m1", "m5", "daily_fragments")},
        "canonical_sha256": {
            "m1": m1_hash,
            "m5": m5_hash,
            "daily_fragments": daily_fragment_hash,
        },
        "three_run_semantic_sha256": run_hashes[0],
        "three_run_semantic_parity": True,
        "m5_bucket_certification": {
            "incomplete_bucket_count": len(m5_incomplete),
            "incomplete_buckets": m5_incomplete,
            "no_fill": True,
            "status": canonical["m5_certification"]["status"],
        },
        "daily_close": "17:00 America/New_York",
        "daily_scope": "PAIR_MONTH_FRAGMENTS_ONLY_NOT_DAILY_COMPLETENESS_CLAIM",
        "daily_source": "CERTIFIED_M5_ONLY",
        "forward_fill": False,
        "status": "F0_PAIR_MONTH_M5_CERTIFIED_DAILY_FRAGMENTS_ONLY",
    }
    safe_atomic_write(
        authorizations.write,
        bid_partition,
        F0_CERTIFICATION,
        canonical_json_bytes(certification),
    )
    return certification


def _assemble_instrument_daily(
    authorizations: AuthorizationBundle,
    instrument: str,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, Any]:
    """Assemble all development months before writing complete daily subsets."""
    require_storage_reserve(authorizations.read.clean_room_root, usage_probe)
    fragments: list[dict[str, Any]] = []
    for year in DEVELOPMENT_YEARS:
        for month in MONTHS:
            partition = MarketPartition(
                instrument, "bid", date(year, month, 1), _month_end(year, month)
            )
            m5 = json.loads(safe_read_bytes(authorizations.read, partition, F0_CANONICAL_M5))
            if not isinstance(m5, list):
                raise ValueError("F0 canonical M5 payload must be a row list")
            fragments.extend(daily_fragments_from_certified_m5(m5))

    assembled = assemble_daily_from_m5_fragments(fragments)
    daily = assembled["certified_daily_bars"]
    by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in daily:
        close_day = date.fromisoformat(str(row["fx_close_date"]))
        by_month.setdefault((close_day.year, close_day.month), []).append(row)

    monthly_hashes: dict[str, str] = {}
    for year in DEVELOPMENT_YEARS:
        for month in MONTHS:
            partition = MarketPartition(
                instrument, "bid", date(year, month, 1), _month_end(year, month)
            )
            key = f"{year:04d}-{month:02d}"
            monthly_hashes[key] = safe_atomic_write(
                authorizations.write,
                partition,
                F0_CANONICAL_DAILY,
                canonical_json_bytes(by_month.get((year, month), [])),
            )

    certification = {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "instrument": instrument,
        "source": "ALL_DEVELOPMENT_PAIR_MONTH_CERTIFIED_M5",
        "strict_timestamp_deduplication": True,
        "daily_close": "EXACT_FINAL_M5_PRECEDING_17:00_AMERICA_NEW_YORK",
        "certified_daily_rows": len(daily),
        "incomplete_days": assembled["incomplete_days"],
        "monthly_daily_sha256": monthly_hashes,
        "forward_fill": False,
        "status": assembled["status"],
    }
    first_partition = MarketPartition(
        instrument, "bid", date(DEVELOPMENT_YEARS[0], 1, 1), date(2010, 1, 31)
    )
    safe_atomic_write(
        authorizations.write,
        first_partition,
        F0_DAILY_ASSEMBLY_CERTIFICATION,
        canonical_json_bytes(certification),
    )
    return certification


def certify_development_market(
    root: Path,
    repository_root: Path,
    *,
    workers: int = MAXIMUM_WORKERS,
    execute_local: bool = False,
    usage_probe: DiskUsageProbe = _disk_usage,
) -> dict[str, Any]:
    """Certify only explicit F0 files; default mode performs no local I/O."""
    _validate_workers(workers)
    if not execute_local:
        return {
            "program_id": PROGRAM_ID,
            "stage": "certify-development-market",
            "dry_run": True,
            "planned_pair_months": EXPECTED_PAIR_MONTHS,
            "workers": workers,
            "status": "DRY_RUN_NO_LOCAL_IO",
        }
    authorizations = development_authorizations(root, repository_root)
    require_storage_reserve(authorizations.read.clean_room_root, usage_probe)
    pair_months = tuple(
        (instrument, year, month)
        for instrument in INSTRUMENT_ORDER
        for year in DEVELOPMENT_YEARS
        for month in MONTHS
    )
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="f0-certify")
    try:
        futures = {
            pool.submit(
                _certify_pair_month,
                authorizations,
                instrument,
                year,
                month,
                usage_probe,
            ): (instrument, year, month)
            for instrument, year, month in pair_months
        }
        results = _collect_futures_fail_fast(futures)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    certified = sum(
        item["status"] == "F0_PAIR_MONTH_M5_CERTIFIED_DAILY_FRAGMENTS_ONLY" for item in results
    )
    daily_results = [
        _assemble_instrument_daily(authorizations, instrument, usage_probe)
        for instrument in INSTRUMENT_ORDER
    ]
    return {
        "program_id": PROGRAM_ID,
        "stage": "certify-development-market",
        "dry_run": False,
        "planned_pair_months": EXPECTED_PAIR_MONTHS,
        "certified_pair_months": certified,
        "cross_month_daily_instruments": len(daily_results),
        "incomplete_daily_days": sum(len(item["incomplete_days"]) for item in daily_results),
        "workers": workers,
        "status": (
            "F0_DEVELOPMENT_MARKET_CERTIFIED"
            if certified == EXPECTED_PAIR_MONTHS
            else "F0_DEVELOPMENT_MARKET_INCOMPLETE"
        ),
    }


def static_status() -> dict[str, Any]:
    """Return protocol status without touching the clean-room filesystem."""
    return {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "development_interval": "2010-01-01..2016-12-31",
        "partition_tasks": EXPECTED_PARTITION_TASKS,
        "pair_months": EXPECTED_PAIR_MONTHS,
        "maximum_workers": MAXIMUM_WORKERS,
        "default_mode": "DRY_RUN",
        "provider_execution_flag": "--execute-provider",
        "local_certification_flag": "--execute-local",
        "provider_requests_sent": 0,
        "filesystem_inspected": False,
        "status": "READY_FOR_EXPLICIT_STAGE",
    }


assert frozenset(INSTRUMENT_ORDER) == FROZEN_INSTRUMENTS
