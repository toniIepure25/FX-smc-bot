"""Durable daily acquisition checkpoints.

Each day is downloaded, validated, and persisted atomically.
Monthly compaction only occurs after all expected trading days reach
terminal status. Completed days are never re-downloaded unless their
checksum is invalid.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import logging
import lzma
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from fx_smc_bot.data.dukascopy_bi5 import (
    HTTP_TRANSPORT_V2_ID,
    HTTP_TRANSPORT_V2_VERSION,
    dukascopy_candle_url,
    fetch_bi5_day_http_v2,
    parse_bi5_m1_candles,
    raw_ohlc_checksum,
    timestamp_checksum,
    validate_m1_rows,
)
from fx_smc_bot.data.dukascopy_node_provider import (
    PAIR_TO_INSTRUMENT,
    _compute_checksum,
    _download_month_bulk_result,
    _download_single_day,
    _download_single_day_result,
)
from fx_smc_bot.data.failure_categories import (
    FailureCategory,
    classify_failure,
    is_retryable,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DayStatus:
    """Status of a single day download."""
    pair: str
    side: str
    year: int
    month: int
    day: int
    status: str  # "complete", "failed", "market_closed", "pending"
    rows: int = 0
    checksum: str = ""
    file_size: int = 0
    failure_category: str = ""
    error: str = ""
    attempts: int = 0
    completed_at: str = ""
    provider_call_outcome: str = ""
    source_id: str = "DUKASCOPY_DATAFEED_M1_CANDLES_V1"
    transport_id: str = "DUKASCOPY_NODE_1_46_4"
    transport_version: str = "1.46.4"
    effective_http_client: str = ""
    native_http_status: int | None = None
    native_content_length: int = 0
    native_http_attempts: int = 0
    native_primary_status: str = ""
    raw_hash: str = ""
    parsed_row_hash: str = ""
    timestamp_set_hash: str = ""
    raw_ohlc_hash: str = ""
    volume_hash: str = ""


@dataclass(frozen=True, slots=True)
class DailyMarketUnit:
    """Transport-neutral, daily market-data provenance contract."""

    pair: str
    side: str
    date: str
    source_id: str
    transport_id: str
    transport_version: str
    effective_http_client: str
    native_http_status: int | None
    native_content_length: int
    raw_hash: str
    parsed_row_hash: str
    row_count: int
    first_timestamp: int | None
    last_timestamp: int | None
    timestamp_set_hash: str
    raw_ohlc_hash: str
    volume_hash: str
    market_calendar_status: str
    certification_status: str


@dataclass(slots=True)
class MonthManifest:
    """Manifest for one pair/side/year/month."""
    pair: str
    side: str
    year: int
    month: int
    days: list[DayStatus] = field(default_factory=list)
    compacted: bool = False
    compacted_checksum: str = ""
    compacted_rows: int = 0
    provider_call_count: int = 0
    partition_cycle_count: int = 0
    partial_successful_calls: int = 0
    last_provider_call_outcome: str = ""
    last_provider_error: str = ""

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "side": self.side,
            "year": self.year,
            "month": self.month,
            "compacted": self.compacted,
            "compacted_checksum": self.compacted_checksum,
            "compacted_rows": self.compacted_rows,
            "provider_call_count": self.provider_call_count,
            "partition_cycle_count": self.partition_cycle_count,
            "partial_successful_calls": self.partial_successful_calls,
            "last_provider_call_outcome": self.last_provider_call_outcome,
            "last_provider_error": self.last_provider_error,
            "days": [asdict(d) for d in self.days],
        }

    @classmethod
    def from_dict(cls, d: dict) -> MonthManifest:
        manifest = cls(
            pair=d["pair"], side=d["side"],
            year=d["year"], month=d["month"],
            compacted=d.get("compacted", False),
            compacted_checksum=d.get("compacted_checksum", ""),
            compacted_rows=d.get("compacted_rows", 0),
            provider_call_count=d.get("provider_call_count", 0),
            partition_cycle_count=d.get("partition_cycle_count", 0),
            partial_successful_calls=d.get("partial_successful_calls", 0),
            last_provider_call_outcome=d.get("last_provider_call_outcome", ""),
            last_provider_error=d.get("last_provider_error", ""),
        )
        for day_d in d.get("days", []):
            manifest.days.append(DayStatus(**day_d))
        return manifest


def _day_dir(raw_dir: Path, pair: str, side: str,
             year: int, month: int, day: int) -> Path:
    return (
        raw_dir / pair / f"price={side}"
        / f"year={year}" / f"month={month:02d}" / f"day={day:02d}"
    )


def _month_dir(raw_dir: Path, pair: str, side: str,
               year: int, month: int) -> Path:
    return (
        raw_dir / pair / f"price={side}"
        / f"year={year}" / f"month={month:02d}"
    )


def _manifest_path(raw_dir: Path, pair: str, side: str,
                    year: int, month: int) -> Path:
    return _month_dir(raw_dir, pair, side, year, month) / "manifest.json"


def load_month_manifest(
    raw_dir: Path, pair: str, side: str, year: int, month: int,
) -> MonthManifest | None:
    path = _manifest_path(raw_dir, pair, side, year, month)
    if path.exists():
        return MonthManifest.from_dict(json.loads(path.read_text()))
    return None


def save_month_manifest(
    raw_dir: Path, manifest: MonthManifest,
) -> None:
    path = _manifest_path(
        raw_dir, manifest.pair, manifest.side,
        manifest.year, manifest.month,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest.to_dict(), indent=2))
    os.replace(str(tmp), str(path))


def download_day_with_checkpoint(
    pair: str,
    side: str,
    year: int,
    month: int,
    day: int,
    raw_dir: Path,
    instrument: str | None = None,
    timeframe: str = "m1",
    batch_size: int = 10,
    retries: int = 5,
    max_retries: int = 3,
    pause_between_batches_ms: int = 200,
    scratch_root: Path | None = None,
    cache_root: Path | None = None,
    worker_id: int | None = None,
) -> DayStatus:
    """Download one day, validate, and persist atomically."""
    from fx_smc_bot.config import TradingPair
    if instrument is None:
        instrument = PAIR_TO_INSTRUMENT.get(
            TradingPair(pair), pair.lower(),
        )

    day_d = _day_dir(raw_dir, pair, side, year, month, day)
    day_file = day_d / "data.json"

    status = DayStatus(
        pair=pair, side=side, year=year, month=month, day=day,
        status="pending",
    )

    if day_file.exists() and day_file.stat().st_size > 2:
        data = json.loads(day_file.read_text())
        status.status = "complete"
        status.rows = len(data)
        status.checksum = _compute_checksum(day_file)
        status.file_size = day_file.stat().st_size
        return status

    days_in_month = calendar.monthrange(year, month)[1]
    date_str = f"{year}-{month:02d}-{day:02d}"
    if day < days_in_month:
        next_str = f"{year}-{month:02d}-{day + 1:02d}"
    elif month == 12:
        next_str = f"{year + 1}-01-01"
    else:
        next_str = f"{year}-{month + 1:02d}-01"

    last_err = ""
    for attempt in range(max_retries):
        status.attempts += 1
        if scratch_root is None and cache_root is None and worker_id is None:
            # Preserve the legacy seam used by existing checkpoint consumers.
            data, err = _download_single_day(
                instrument, date_str, next_str, side,
                timeframe, batch_size, retries,
                pause_between_batches_ms=pause_between_batches_ms,
            )
        else:
            call = _download_single_day_result(
                instrument, date_str, next_str, side,
                timeframe, batch_size, retries,
                pause_between_batches_ms=pause_between_batches_ms,
                scratch_root=scratch_root,
                cache_root=cache_root,
                worker_id=worker_id,
            )
            data, err = call.rows, call.legacy_error()
        last_err = err

        if not err and data:
            day_d.mkdir(parents=True, exist_ok=True)
            tmp = day_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(str(tmp), str(day_file))

            status.status = "complete"
            status.rows = len(data)
            status.checksum = _compute_checksum(day_file)
            status.file_size = day_file.stat().st_size
            status.completed_at = datetime.now(timezone.utc).isoformat()
            status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_COMPLETE"
            return status

        if not err and not data:
            cat = classify_failure("", year, month, day, 0)
            status.failure_category = cat.value
            if cat in (
                FailureCategory.MARKET_CLOSED_WEEKEND,
                FailureCategory.MARKET_CLOSED_HOLIDAY,
            ):
                status.status = "market_closed"
                status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_EMPTY_MARKET_CLOSED"
                return status
            status.status = "failed"
            status.error = "No provider data returned for open-market business day"
            status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_EMPTY_OPEN_MARKET"
            return status

        cat = classify_failure(err, year, month, day, 0)
        status.failure_category = cat.value
        status.error = err
        status.provider_call_outcome = "PROVIDER_CALL_TRANSPORT_FAILURE"

        if not is_retryable(cat):
            break

        backoff = min(5 * (attempt + 1), 15)
        logger.info(
            f"  Retry {attempt + 1} for {date_str}: {cat.value} "
            f"(backoff {backoff}s)"
        )
        time.sleep(backoff)

    status.status = "failed"
    status.error = last_err
    return status


def download_native_day_with_checkpoint(
    pair: str,
    side: str,
    year: int,
    month: int,
    day: int,
    raw_dir: Path,
    native_raw_dir: Path,
    *,
    max_retries: int = 3,
) -> DayStatus:
    """Fetch a missing daily unit from native BI5 without replacing valid data."""
    existing = _day_dir(raw_dir, pair, side, year, month, day) / "data.json"
    if existing.exists() and existing.stat().st_size > 2:
        rows = json.loads(existing.read_text())
        status = DayStatus(
            pair=pair, side=side, year=year, month=month, day=day,
            status="complete", rows=len(rows), checksum=_compute_checksum(existing),
            file_size=existing.stat().st_size,
        )
        return status
    requested_day = date(year, month, day)
    raw_path = (
        native_raw_dir / pair / f"price={side}" / f"year={year}"
        / f"month={month:02d}" / f"day={day:02d}" / "candles.bi5"
    )
    fetch = fetch_bi5_day_http_v2(
        dukascopy_candle_url(pair, requested_day, side), raw_path, retries=max_retries
    )
    status = DayStatus(
        pair=pair, side=side, year=year, month=month, day=day,
        status="failed", attempts=1,
        source_id="DUKASCOPY_DATAFEED_M1_CANDLES_V1",
        transport_id=HTTP_TRANSPORT_V2_ID,
        transport_version=HTTP_TRANSPORT_V2_VERSION,
        effective_http_client=fetch.client_id,
        native_http_status=fetch.http_status,
        native_content_length=fetch.content_length,
        native_http_attempts=fetch.attempts,
        native_primary_status=fetch.primary_status,
    )
    if fetch.status != "PASS":
        status.failure_category = "NATIVE_BI5_TRANSPORT_FAILURE"
        status.error = fetch.error[:500]
        status.provider_call_outcome = "PROVIDER_CALL_TRANSPORT_FAILURE"
        return status
    try:
        rows = parse_bi5_m1_candles(raw_path.read_bytes(), requested_day, pair=pair)
        checks = validate_m1_rows(rows, requested_day)
    except (OSError, ValueError, lzma.LZMAError) as exc:
        status.failure_category = "NATIVE_BI5_SCHEMA_FAILURE"
        status.error = str(exc)[:500]
        status.provider_call_outcome = "PROVIDER_CALL_SCHEMA_FAILURE"
        return status
    if not (
        checks["monotonic_timestamps"]
        and checks["timestamps_in_requested_day"]
        and checks["ohlc_valid"]
    ):
        status.failure_category = "NATIVE_BI5_SCHEMA_FAILURE"
        status.error = "native BI5 structural validation failed"
        status.provider_call_outcome = "PROVIDER_CALL_SCHEMA_FAILURE"
        return status
    calendar_category = classify_failure("", year, month, day, 0)
    if not rows:
        if calendar_category in (
            FailureCategory.MARKET_CLOSED_WEEKEND,
            FailureCategory.MARKET_CLOSED_HOLIDAY,
        ):
            status.status = "market_closed"
            status.failure_category = calendar_category.value
            status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_EMPTY_MARKET_CLOSED"
            status.raw_hash = fetch.checksum
            return status
        status.failure_category = FailureCategory.NO_PROVIDER_DATA.value
        status.error = "No native BI5 rows on open-market day"
        status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_EMPTY_OPEN_MARKET"
        return status
    day_dir = _day_dir(raw_dir, pair, side, year, month, day)
    day_dir.mkdir(parents=True, exist_ok=True)
    output = day_dir / "data.json"
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows))
    os.replace(str(tmp), str(output))
    status.status = "complete"
    status.rows = len(rows)
    status.checksum = _compute_checksum(output)
    status.file_size = output.stat().st_size
    status.completed_at = datetime.now(timezone.utc).isoformat()
    status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_COMPLETE"
    status.raw_hash = fetch.checksum
    status.parsed_row_hash = _compute_checksum(output)
    status.timestamp_set_hash = timestamp_checksum(rows)
    status.raw_ohlc_hash = raw_ohlc_checksum(rows)
    status.volume_hash = hashlib.sha256(
        json.dumps([row["volume"] for row in rows], separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return status


def repair_missing_days(
    pair: str,
    side: str,
    year: int,
    month: int,
    raw_dir: Path,
    missing_days: list[int],
    *,
    max_day_requests: int | None,
    scratch_root: Path | None = None,
    cache_root: Path | None = None,
    worker_id: int | None = None,
) -> MonthManifest:
    """Repair only missing open-market days; never re-request a positive month."""
    manifest = load_month_manifest(raw_dir, pair, side, year, month) or MonthManifest(
        pair=pair, side=side, year=year, month=month,
    )
    manifest = normalize_month_manifest_for_repair(raw_dir, manifest)
    existing = {item.day: item for item in manifest.days}
    requested = 0
    for day in missing_days:
        if max_day_requests is not None and requested >= max_day_requests:
            break
        current = existing.get(day)
        if current is not None and current.status in ("complete", "market_closed"):
            continue
        replacement = download_day_with_checkpoint(
            pair, side, year, month, day, raw_dir,
            scratch_root=scratch_root, cache_root=cache_root, worker_id=worker_id,
        )
        replacement.attempts += current.attempts if current else 0
        if current is None:
            manifest.days.append(replacement)
        else:
            manifest.days[manifest.days.index(current)] = replacement
        existing[day] = replacement
        manifest.provider_call_count += 1
        requested += 1
        save_month_manifest(raw_dir, manifest)
    compact_month(raw_dir, manifest)
    save_month_manifest(raw_dir, manifest)
    return manifest


def _is_complete_nonfailed_month(manifest: MonthManifest) -> bool:
    days_in_month = calendar.monthrange(manifest.year, manifest.month)[1]
    if len({d.day for d in manifest.days}) != days_in_month:
        return False
    return all(d.status in ("complete", "market_closed") for d in manifest.days)


def _is_valid_compacted_month(manifest: MonthManifest) -> bool:
    return (
        manifest.compacted
        and manifest.compacted_rows > 0
        and _is_complete_nonfailed_month(manifest)
    )


def _is_empty_business_day(ds: DayStatus) -> bool:
    if ds.status != "complete" or ds.rows != 0:
        return False
    cat = (
        FailureCategory(ds.failure_category)
        if ds.failure_category else classify_failure(
            "", ds.year, ds.month, ds.day, 0,
        )
    )
    return cat == FailureCategory.NO_PROVIDER_DATA


def _repair_needed(ds: DayStatus | None) -> bool:
    if ds is None:
        return True
    if ds.status in ("pending", "failed"):
        return True
    if _is_empty_business_day(ds):
        return True
    if ds.status in ("complete", "market_closed"):
        return False
    return True


def normalize_month_manifest_for_repair(
    raw_dir: Path,
    manifest: MonthManifest,
) -> MonthManifest:
    """Mark invalid zero-row business days and compacted months repairable."""
    changed = False
    for ds in manifest.days:
        if _is_empty_business_day(ds):
            ds.status = "failed"
            ds.failure_category = FailureCategory.NO_PROVIDER_DATA.value
            ds.error = "No provider data returned for open-market business day"
            ds.checksum = ""
            ds.file_size = 0
            day_file = (
                _day_dir(
                    raw_dir, ds.pair, ds.side,
                    ds.year, ds.month, ds.day,
                ) / "data.json"
            )
            if day_file.exists() and day_file.stat().st_size <= 2:
                day_file.unlink()
            changed = True

    if manifest.compacted and not _is_valid_compacted_month(manifest):
        manifest.compacted = False
        manifest.compacted_checksum = ""
        manifest.compacted_rows = 0
        changed = True

    if changed:
        save_month_manifest(raw_dir, manifest)
    return manifest


def acquire_month_daily(
    pair: str,
    side: str,
    year: int,
    month: int,
    raw_dir: Path,
    timeframe: str = "m1",
    batch_size: int = 10,
    retries: int = 5,
    pause_between_batches_ms: int = 200,
) -> MonthManifest:
    """Acquire one month day-by-day with durable checkpoints."""
    from fx_smc_bot.config import TradingPair
    instrument = PAIR_TO_INSTRUMENT.get(TradingPair(pair), pair.lower())
    days_in_month = calendar.monthrange(year, month)[1]

    existing = load_month_manifest(raw_dir, pair, side, year, month)
    if existing:
        existing = normalize_month_manifest_for_repair(raw_dir, existing)
    if existing and _is_valid_compacted_month(existing):
        logger.info(f"  {pair}/{side}/{year}-{month:02d}: already compacted")
        return existing

    manifest = existing or MonthManifest(
        pair=pair, side=side, year=year, month=month,
    )
    existing_days = {d.day: d for d in manifest.days}

    for day_num in range(1, days_in_month + 1):
        if day_num in existing_days:
            ds = existing_days[day_num]
            if ds.status in ("complete", "market_closed"):
                continue

        ds = download_day_with_checkpoint(
            pair, side, year, month, day_num, raw_dir,
            instrument=instrument, timeframe=timeframe,
            batch_size=batch_size, retries=retries,
            pause_between_batches_ms=pause_between_batches_ms,
        )

        if day_num in existing_days:
            idx = next(
                i for i, d in enumerate(manifest.days)
                if d.day == day_num
            )
            manifest.days[idx] = ds
        else:
            manifest.days.append(ds)

        save_month_manifest(raw_dir, manifest)

        if ds.rows > 0:
            logger.info(
                f"  {pair}/{side}/{year}-{month:02d}-{day_num:02d}: "
                f"{ds.rows} rows"
            )

    compact_month(raw_dir, manifest)
    save_month_manifest(raw_dir, manifest)
    return manifest


def compact_month(raw_dir: Path, manifest: MonthManifest) -> None:
    """Compact daily files into a single monthly file."""
    if manifest.compacted:
        return

    if not _is_complete_nonfailed_month(manifest):
        return

    all_rows: list[dict] = []
    for ds in sorted(manifest.days, key=lambda d: d.day):
        if ds.status != "complete" or ds.rows == 0:
            continue
        day_file = (
            _day_dir(
                raw_dir, manifest.pair, manifest.side,
                manifest.year, manifest.month, ds.day,
            ) / "data.json"
        )
        if day_file.exists():
            data = json.loads(day_file.read_text())
            all_rows.extend(data)

    if not all_rows:
        return

    all_rows.sort(key=lambda r: r.get("timestamp", 0))

    month_dir = _month_dir(
        raw_dir, manifest.pair, manifest.side,
        manifest.year, manifest.month,
    )
    month_dir.mkdir(parents=True, exist_ok=True)
    out_file = month_dir / "data.json"
    tmp = out_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_rows))
    os.replace(str(tmp), str(out_file))

    manifest.compacted = True
    manifest.compacted_rows = len(all_rows)
    manifest.compacted_checksum = _compute_checksum(out_file)


def find_missing_days(
    raw_dir: Path, pair: str, side: str, year: int, month: int,
) -> list[int]:
    """Find days that need downloading or repair."""
    days_in_month = calendar.monthrange(year, month)[1]
    manifest = load_month_manifest(raw_dir, pair, side, year, month)
    if manifest:
        manifest = normalize_month_manifest_for_repair(raw_dir, manifest)
    existing_days = {d.day: d for d in manifest.days} if manifest else {}

    missing = []
    for day_num in range(1, days_in_month + 1):
        ds = existing_days.get(day_num)
        if _repair_needed(ds):
            missing.append(day_num)
    return missing


def acquire_month_bulk(
    pair: str,
    side: str,
    year: int,
    month: int,
    raw_dir: Path,
    timeframe: str = "m1",
    batch_size: int = 30,
    retries: int = 5,
    pause_between_batches_ms: int = 200,
    scratch_root: Path | None = None,
    cache_root: Path | None = None,
    worker_id: int | None = None,
    max_day_requests: int | None = None,
) -> MonthManifest:
    """Acquire one month in a SINGLE Node.js call, then split into daily checkpoints.

    This is 5-10x faster than acquire_month_daily because it avoids spawning
    31 separate Node.js processes and leverages dukascopy-node's internal
    batching across the full month range.
    """
    from fx_smc_bot.config import TradingPair
    instrument = PAIR_TO_INSTRUMENT.get(TradingPair(pair), pair.lower())
    days_in_month = calendar.monthrange(year, month)[1]

    existing = load_month_manifest(raw_dir, pair, side, year, month)
    if existing:
        existing = normalize_month_manifest_for_repair(raw_dir, existing)
    if existing and existing.compacted:
        logger.info(f"  {pair}/{side}/{year}-{month:02d}: already compacted")
        return existing

    if existing and existing.days:
        return repair_missing_days(
            pair, side, year, month, raw_dir,
            find_missing_days(raw_dir, pair, side, year, month),
            max_day_requests=max_day_requests,
            scratch_root=scratch_root,
            cache_root=cache_root,
            worker_id=worker_id,
        )

    all_days_done = True
    if existing:
        existing_days = {d.day: d for d in existing.days}
        for day_num in range(1, days_in_month + 1):
            ds = existing_days.get(day_num)
            if ds is None or ds.status not in ("complete", "market_closed"):
                if ds and ds.status == "failed" and not is_retryable(
                    FailureCategory(ds.failure_category)
                    if ds.failure_category else FailureCategory.UNKNOWN_ERROR
                ):
                    continue
                all_days_done = False
                break
        if all_days_done:
            manifest = existing
            compact_month(raw_dir, manifest)
            save_month_manifest(raw_dir, manifest)
            return manifest

    bulk_data: list[dict] = []
    err = ""
    for bulk_attempt in range(3):
        call = _download_month_bulk_result(
            instrument, year, month, side, timeframe,
            batch_size, retries, pause_between_batches_ms,
            scratch_root=scratch_root,
            cache_root=cache_root,
            worker_id=worker_id,
        )
        bulk_data, err = call.rows, call.legacy_error()
        if not err:
            break
        if bulk_attempt < 2:
            backoff_seconds = 2 * (bulk_attempt + 1)
            logger.warning(
                "%s/%s/%04d-%02d monthly attempt %d failed: %s; retrying in %ds",
                pair,
                side,
                year,
                month,
                bulk_attempt + 1,
                err,
                backoff_seconds,
            )
            time.sleep(backoff_seconds)

    manifest = existing or MonthManifest(
        pair=pair, side=side, year=year, month=month,
    )
    existing_days = {d.day: d for d in manifest.days}

    manifest.provider_call_count += 1
    manifest.partition_cycle_count += 1
    if err:
        manifest.last_provider_call_outcome = "PROVIDER_CALL_TRANSPORT_FAILURE"
        manifest.last_provider_error = err
        save_month_manifest(raw_dir, manifest)
        logger.warning(
            f"  {pair}/{side}/{year}-{month:02d} bulk download failed: {err}"
        )
        return manifest

    rows_by_day: dict[int, list[dict]] = {}
    for row in bulk_data:
        ts_ms = row.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        day_num = dt.day
        if dt.month == month and dt.year == year:
            rows_by_day.setdefault(day_num, []).append(row)

    for day_num in range(1, days_in_month + 1):
        if day_num in existing_days:
            ds = existing_days[day_num]
            if ds.status in ("complete", "market_closed"):
                continue

        day_rows = rows_by_day.get(day_num, [])
        status = DayStatus(
            pair=pair, side=side, year=year, month=month, day=day_num,
            status="pending", attempts=1,
        )

        if day_rows:
            day_d = _day_dir(raw_dir, pair, side, year, month, day_num)
            day_d.mkdir(parents=True, exist_ok=True)
            day_file = day_d / "data.json"
            tmp = day_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(day_rows))
            os.replace(str(tmp), str(day_file))

            status.status = "complete"
            status.rows = len(day_rows)
            status.checksum = _compute_checksum(day_file)
            status.file_size = day_file.stat().st_size
            status.completed_at = datetime.now(timezone.utc).isoformat()
        else:
            cat = classify_failure("", year, month, day_num, 0)
            status.failure_category = cat.value
            if cat in (
                FailureCategory.MARKET_CLOSED_WEEKEND,
                FailureCategory.MARKET_CLOSED_HOLIDAY,
            ):
                status.status = "market_closed"
            else:
                status.status = "failed"
                status.failure_category = FailureCategory.NO_PROVIDER_DATA.value
                status.error = "Missing open-market day in successful bulk response"
                status.provider_call_outcome = "PROVIDER_CALL_SUCCESS_PARTIAL"
                manifest.partial_successful_calls += 1

        if day_num in existing_days:
            idx = next(
                i for i, d in enumerate(manifest.days) if d.day == day_num
            )
            manifest.days[idx] = status
        else:
            manifest.days.append(status)

    save_month_manifest(raw_dir, manifest)

    total_rows = sum(len(v) for v in rows_by_day.values())
    if manifest.partial_successful_calls:
        manifest.last_provider_call_outcome = "PROVIDER_CALL_SUCCESS_PARTIAL"
    else:
        manifest.last_provider_call_outcome = "PROVIDER_CALL_SUCCESS_COMPLETE"
    manifest.last_provider_error = ""
    logger.info(f"  {pair}/{side}/{year}-{month:02d}: {total_rows} rows (bulk)")

    compact_month(raw_dir, manifest)
    save_month_manifest(raw_dir, manifest)
    return manifest


def repair_month(
    pair: str, side: str, year: int, month: int, raw_dir: Path,
    timeframe: str = "m1",
    batch_size: int = 5,
    retries: int = 5,
) -> dict:
    """Repair missing/failed days in a month partition."""
    before = load_month_manifest(raw_dir, pair, side, year, month)
    before_complete = sum(
        1 for d in (before.days if before else [])
        if d.status in ("complete", "market_closed")
    )

    missing = find_missing_days(raw_dir, pair, side, year, month)
    result = acquire_month_daily(
        pair, side, year, month, raw_dir,
        timeframe=timeframe, batch_size=batch_size, retries=retries,
    )

    after_complete = sum(
        1 for d in result.days
        if d.status in ("complete", "market_closed")
    )

    return {
        "pair": pair,
        "side": side,
        "year": year,
        "month": month,
        "missing_before": len(missing),
        "complete_before": before_complete,
        "complete_after": after_complete,
        "repaired": after_complete - before_complete,
        "remaining_failed": sum(
            1 for d in result.days if d.status == "failed"
        ),
    }
