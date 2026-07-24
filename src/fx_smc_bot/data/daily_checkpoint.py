"""Durable daily acquisition checkpoints.

Each day is downloaded, validated, and persisted atomically.
Monthly compaction only occurs after all expected trading days reach
terminal status. Completed days are never re-downloaded unless their
checksum is invalid.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fx_smc_bot.data.dukascopy_node_provider import (
    PAIR_TO_INSTRUMENT,
    _compute_checksum,
    _download_month_bulk,
    _download_single_day,
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

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "side": self.side,
            "year": self.year,
            "month": self.month,
            "compacted": self.compacted,
            "compacted_checksum": self.compacted_checksum,
            "compacted_rows": self.compacted_rows,
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
        data, err = _download_single_day(
            instrument, date_str, next_str, side,
            timeframe, batch_size, retries,
            pause_between_batches_ms=pause_between_batches_ms,
        )
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
            return status

        if not err and not data:
            cat = classify_failure("", year, month, day, 0)
            status.failure_category = cat.value
            if cat in (
                FailureCategory.MARKET_CLOSED_WEEKEND,
                FailureCategory.MARKET_CLOSED_HOLIDAY,
            ):
                status.status = "market_closed"
                return status
            status.status = "failed"
            status.error = "No provider data returned for open-market business day"
            return status

        cat = classify_failure(err, year, month, day, 0)
        status.failure_category = cat.value
        status.error = err

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
    if existing and existing.compacted:
        logger.info(f"  {pair}/{side}/{year}-{month:02d}: already compacted")
        return existing

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

    bulk_data, err = _download_month_bulk(
        instrument, year, month, side, timeframe,
        batch_size, retries, pause_between_batches_ms,
    )

    manifest = existing or MonthManifest(
        pair=pair, side=side, year=year, month=month,
    )
    existing_days = {d.day: d for d in manifest.days}

    if err:
        logger.warning(
            f"  {pair}/{side}/{year}-{month:02d} bulk download failed: {err}, "
            f"falling back to day-by-day"
        )
        return acquire_month_daily(
            pair, side, year, month, raw_dir,
            timeframe=timeframe, batch_size=batch_size, retries=retries,
            pause_between_batches_ms=pause_between_batches_ms,
        )

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
                status.status = "complete"
                status.rows = 0
                day_d = _day_dir(raw_dir, pair, side, year, month, day_num)
                day_d.mkdir(parents=True, exist_ok=True)
                day_file = day_d / "data.json"
                day_file.write_text("[]")
                status.checksum = _compute_checksum(day_file)
                status.file_size = day_file.stat().st_size

        if day_num in existing_days:
            idx = next(
                i for i, d in enumerate(manifest.days) if d.day == day_num
            )
            manifest.days[idx] = status
        else:
            manifest.days.append(status)

    save_month_manifest(raw_dir, manifest)

    total_rows = sum(len(v) for v in rows_by_day.values())
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
