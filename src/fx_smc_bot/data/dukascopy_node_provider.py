"""Python orchestration bridge for the pinned dukascopy-node acquisition tool.

Invokes the Node.js acquire.mjs script, captures structured JSON output,
handles resumability, builds manifests, and converts results to Parquet.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parents[3] / "tools" / "dukascopy-node"

PAIR_TO_INSTRUMENT = {
    TradingPair.EURUSD: "eurusd",
    TradingPair.GBPUSD: "gbpusd",
    TradingPair.USDJPY: "usdjpy",
}

INSTRUMENT_TO_PAIR = {v: k for k, v in PAIR_TO_INSTRUMENT.items()}


@dataclass(slots=True)
class PartitionStatus:
    """Status of a single pair/year/month/side partition."""
    pair: str
    year: int
    month: int
    side: str  # "bid" or "ask"
    status: str  # "pending", "downloading", "complete", "failed", "skipped"
    rows: int = 0
    checksum: str = ""
    file_path: str = ""
    file_size: int = 0
    attempts: int = 0
    error: str = ""
    first_ts: str = ""
    last_ts: str = ""
    node_version: str = ""
    package_version: str = ""


@dataclass(slots=True)
class AcquisitionManifest:
    """Full acquisition manifest across all partitions."""
    pairs: list[str]
    start: str
    end: str
    timeframe: str
    created_at: str = ""
    partitions: list[PartitionStatus] = field(default_factory=list)
    node_version: str = ""
    package_version: str = "1.46.4"

    def to_dict(self) -> dict:
        return {
            "pairs": self.pairs,
            "start": self.start,
            "end": self.end,
            "timeframe": self.timeframe,
            "created_at": self.created_at,
            "node_version": self.node_version,
            "package_version": self.package_version,
            "partition_count": len(self.partitions),
            "complete_count": sum(
                1 for p in self.partitions if p.status == "complete"
            ),
            "failed_count": sum(
                1 for p in self.partitions if p.status == "failed"
            ),
            "total_rows": sum(p.rows for p in self.partitions),
            "partitions": [
                {
                    "pair": p.pair,
                    "year": p.year,
                    "month": p.month,
                    "side": p.side,
                    "status": p.status,
                    "rows": p.rows,
                    "checksum": p.checksum,
                    "file_path": p.file_path,
                    "file_size": p.file_size,
                    "attempts": p.attempts,
                    "error": p.error,
                    "first_ts": p.first_ts,
                    "last_ts": p.last_ts,
                    "node_version": p.node_version,
                    "package_version": p.package_version,
                }
                for p in self.partitions
            ],
        }


def _compute_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _month_range(start_year: int, start_month: int,
                 end_year: int, end_month: int):
    """Yield (year, month) tuples inclusive."""
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _download_single_day(
    instrument: str,
    date_str: str,
    next_date_str: str,
    side: str,
    timeframe: str = "m1",
    batch_size: int = 10,
    retries: int = 5,
    pause_between_batches_ms: int = 200,
    worker_id: int | None = None,
) -> tuple[list[dict], str]:
    """Download one day of data. Returns (rows_list, error_string)."""
    suffix = f"_{worker_id}" if worker_id is not None else f"_{threading.current_thread().ident}"
    tmp_out = TOOL_DIR / f"_tmp_download{suffix}"
    cmd = [
        "node", str(TOOL_DIR / "acquire.mjs"),
        "--instrument", instrument,
        "--from", date_str,
        "--to", next_date_str,
        "--timeframe", timeframe,
        "--priceType", side,
        "--format", "json",
        "--outDir", str(tmp_out),
        "--batchSize", str(batch_size),
        "--retries", str(retries),
        "--pauseBetweenBatchesMs", str(pause_between_batches_ms),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(TOOL_DIR),
        )

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if record.get("type") == "acquisition_complete":
                out_path_str = record.get("outFile", "")
                src_file = Path(out_path_str)
                if not src_file.is_absolute():
                    src_file = TOOL_DIR / src_file
                if src_file.exists():
                    data = json.loads(src_file.read_text())
                    src_file.unlink(missing_ok=True)
                    return data, ""
                return [], ""

            if record.get("type") == "acquisition_error":
                return [], record.get("error", "unknown")

        if result.returncode != 0:
            err = result.stderr[:300] if result.stderr else ""
            return [], err or f"exit code {result.returncode}"

        return [], ""

    except subprocess.TimeoutExpired:
        return [], "timeout"
    except Exception as exc:
        return [], str(exc)[:300]


def _download_month_bulk(
    instrument: str,
    year: int,
    month: int,
    side: str,
    timeframe: str = "m1",
    batch_size: int = 30,
    retries: int = 5,
    pause_between_batches_ms: int = 200,
) -> tuple[list[dict], str]:
    """Download an entire month in ONE Node.js call. Much faster than per-day.

    Returns (rows_list, error_string). The rows contain timestamps that span
    the full month; the caller splits them into daily checkpoints.
    """
    import calendar

    days_in_month = calendar.monthrange(year, month)[1]
    date_from = f"{year}-{month:02d}-01"
    if month == 12:
        date_to = f"{year + 1}-01-01"
    else:
        date_to = f"{year}-{month + 1:02d}-01"

    suffix = f"_{threading.current_thread().ident}"
    tmp_out = TOOL_DIR / f"_tmp_download{suffix}"
    cmd = [
        "node", str(TOOL_DIR / "acquire.mjs"),
        "--instrument", instrument,
        "--from", date_from,
        "--to", date_to,
        "--timeframe", timeframe,
        "--priceType", side,
        "--format", "json",
        "--outDir", str(tmp_out),
        "--batchSize", str(batch_size),
        "--retries", str(retries),
        "--pauseBetweenBatchesMs", str(pause_between_batches_ms),
    ]

    timeout = max(600, days_in_month * 30)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(TOOL_DIR),
        )

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if record.get("type") == "acquisition_complete":
                out_path_str = record.get("outFile", "")
                src_file = Path(out_path_str)
                if not src_file.is_absolute():
                    src_file = TOOL_DIR / src_file
                if src_file.exists():
                    data = json.loads(src_file.read_text())
                    src_file.unlink(missing_ok=True)
                    return data, ""
                return [], ""

            if record.get("type") == "acquisition_error":
                return [], record.get("error", "unknown")

        if result.returncode != 0:
            err = result.stderr[:300] if result.stderr else ""
            return [], err or f"exit code {result.returncode}"

        return [], ""

    except subprocess.TimeoutExpired:
        return [], "timeout"
    except Exception as exc:
        return [], str(exc)[:300]


def download_partition(
    pair: TradingPair,
    year: int,
    month: int,
    side: str,
    raw_dir: Path,
    timeframe: str = "m1",
    batch_size: int = 5,
    retries: int = 5,
) -> PartitionStatus:
    """Download one month of M1 data for one pair/side.

    Downloads day-by-day to avoid network failures on large ranges,
    then aggregates into a single monthly partition file.
    """
    import calendar
    instrument = PAIR_TO_INSTRUMENT[pair]

    sym = instrument.upper()
    part_dir = (
        raw_dir / sym / f"price={side}"
        / f"year={year}" / f"month={month:02d}"
    )
    part_dir.mkdir(parents=True, exist_ok=True)
    out_file = part_dir / "data.json"

    status = PartitionStatus(
        pair=pair.value, year=year, month=month, side=side,
        status="downloading",
    )

    if out_file.exists() and out_file.stat().st_size > 0:
        checksum = _compute_checksum(out_file)
        data = json.loads(out_file.read_text())
        status.status = "complete"
        status.rows = len(data)
        status.checksum = checksum
        status.file_path = str(out_file)
        status.file_size = out_file.stat().st_size
        if data:
            status.first_ts = str(data[0].get("timestamp", ""))
            status.last_ts = str(data[-1].get("timestamp", ""))
        logger.info(
            f"  Skipping {pair.value}/{side}/{year}-{month:02d}"
            f" (cached, {len(data)} rows)"
        )
        return status

    days_in_month = calendar.monthrange(year, month)[1]
    all_rows: list[dict] = []
    day_errors: list[str] = []

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        if day < days_in_month:
            next_str = f"{year}-{month:02d}-{day + 1:02d}"
        elif month == 12:
            next_str = f"{year + 1}-01-01"
        else:
            next_str = f"{year}-{month + 1:02d}-01"

        day_data, err = _download_single_day(
            instrument, date_str, next_str, side,
            timeframe, batch_size, retries,
        )
        status.attempts += 1

        if err:
            logger.warning(
                f"  Day {date_str} failed: {err}"
            )
            day_errors.append(f"{date_str}: {err}")
            for retry_i in range(2):
                logger.info(f"  Retry {retry_i + 1} for {date_str}")
                day_data, err = _download_single_day(
                    instrument, date_str, next_str, side,
                    timeframe, batch_size, retries,
                )
                status.attempts += 1
                if not err:
                    break
            if err:
                continue

        all_rows.extend(day_data)
        if day_data:
            logger.info(
                f"  Day {date_str}: {len(day_data)} rows"
            )

    if not all_rows:
        status.status = "failed"
        status.error = "; ".join(day_errors[:5])
        return status

    all_rows.sort(key=lambda r: r.get("timestamp", 0))

    import os
    tmp = out_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_rows))
    os.replace(str(tmp), str(out_file))

    status.status = "complete"
    status.rows = len(all_rows)
    status.file_path = str(out_file)
    status.file_size = out_file.stat().st_size
    status.checksum = _compute_checksum(out_file)
    if all_rows:
        status.first_ts = str(all_rows[0].get("timestamp", ""))
        status.last_ts = str(all_rows[-1].get("timestamp", ""))
    if day_errors:
        status.error = f"{len(day_errors)} day(s) failed"

    return status


def acquire_pair(
    pair: TradingPair,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    raw_dir: Path,
    timeframe: str = "m1",
    batch_size: int = 5,
    retries: int = 5,
) -> list[PartitionStatus]:
    """Acquire all monthly partitions for one pair, both bid and ask."""
    results = []
    for year, month in _month_range(start_year, start_month, end_year, end_month):
        for side in ("bid", "ask"):
            logger.info(f"Acquiring {pair.value}/{side}/{year}-{month:02d}")
            ps = download_partition(
                pair, year, month, side, raw_dir, timeframe,
                batch_size, retries,
            )
            results.append(ps)
            logger.info(f"  -> {ps.status}: {ps.rows} rows")
    return results


def align_bid_ask_month(
    pair: TradingPair,
    year: int,
    month: int,
    raw_dir: Path,
) -> dict[str, Any]:
    """Join bid and ask M1 data for one month by exact UTC timestamp."""
    instrument = PAIR_TO_INSTRUMENT[pair].upper()
    bid_file = raw_dir / instrument / f"price=bid/year={year}/month={month:02d}/data.json"
    ask_file = raw_dir / instrument / f"price=ask/year={year}/month={month:02d}/data.json"

    report: dict[str, Any] = {
        "pair": pair.value, "year": year, "month": month,
    }

    if not bid_file.exists():
        report["error"] = "bid file missing"
        return report
    if not ask_file.exists():
        report["error"] = "ask file missing"
        return report

    bid_data = json.loads(bid_file.read_text())
    ask_data = json.loads(ask_file.read_text())

    report["bid_rows"] = len(bid_data)
    report["ask_rows"] = len(ask_data)

    bid_by_ts = {}
    for r in bid_data:
        ts = r["timestamp"]
        if ts in bid_by_ts:
            report.setdefault("duplicate_bid", 0)
            report["duplicate_bid"] += 1
        bid_by_ts[ts] = r

    ask_by_ts = {}
    for r in ask_data:
        ts = r["timestamp"]
        if ts in ask_by_ts:
            report.setdefault("duplicate_ask", 0)
            report["duplicate_ask"] += 1
        ask_by_ts[ts] = r

    all_ts = sorted(set(bid_by_ts.keys()) | set(ask_by_ts.keys()))
    both = 0
    bid_only = 0
    ask_only = 0
    neg_spread = 0
    joined_rows = []

    for ts in all_ts:
        b = bid_by_ts.get(ts)
        a = ask_by_ts.get(ts)
        if b and a:
            both += 1
            if a["open"] < b["open"] or a["close"] < b["close"]:
                neg_spread += 1
            joined_rows.append({
                "timestamp": ts,
                "bid_open": b["open"], "bid_high": b["high"],
                "bid_low": b["low"], "bid_close": b["close"],
                "ask_open": a["open"], "ask_high": a["high"],
                "ask_low": a["low"], "ask_close": a["close"],
                "bid_volume": b.get("volume", 0),
                "ask_volume": a.get("volume", 0),
            })
        elif b:
            bid_only += 1
        else:
            ask_only += 1

    report["joined_rows"] = len(joined_rows)
    report["both_present"] = both
    report["bid_only"] = bid_only
    report["ask_only"] = ask_only
    report["negative_spread_count"] = neg_spread

    if joined_rows:
        spreads = [
            r["ask_close"] - r["bid_close"] for r in joined_rows
        ]
        report["median_spread"] = float(np.median(spreads))
        report["spread_p90"] = float(np.percentile(spreads, 90))
        report["spread_p95"] = float(np.percentile(spreads, 95))
        report["spread_p99"] = float(np.percentile(spreads, 99))
        report["max_spread"] = float(max(spreads))

    report["joined_data"] = joined_rows
    return report


def joined_to_parquet(
    joined: list[dict],
    pair: TradingPair,
    year: int,
    month: int,
    canonical_dir: Path,
    timeframe: str = "M1",
) -> Path | None:
    """Write joined bid/ask data to a Parquet partition."""
    if not joined:
        return None

    instrument = PAIR_TO_INSTRUMENT[pair].upper()
    out_dir = (
        canonical_dir / instrument / f"timeframe={timeframe}"
        / f"year={year}" / f"month={month:02d}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "part.parquet"

    df = pd.DataFrame(joined)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    import os
    tmp = out_file.with_suffix(".tmp")
    df.to_parquet(str(tmp), index=False, engine="pyarrow")
    os.replace(str(tmp), str(out_file))
    return out_file


def parquet_to_bidask_series(
    path: Path,
    pair: TradingPair,
    timeframe: Timeframe = Timeframe.M1,
) -> BidAskBarSeries:
    """Load a Parquet partition into a BidAskBarSeries."""
    df = pd.read_parquet(str(path))
    ts = df["timestamp"].values.astype("datetime64[ns]")
    return BidAskBarSeries(
        pair=pair,
        timeframe=timeframe,
        timestamps=ts,
        bid_open=df["bid_open"].values.astype(np.float64),
        bid_high=df["bid_high"].values.astype(np.float64),
        bid_low=df["bid_low"].values.astype(np.float64),
        bid_close=df["bid_close"].values.astype(np.float64),
        ask_open=df["ask_open"].values.astype(np.float64),
        ask_high=df["ask_high"].values.astype(np.float64),
        ask_low=df["ask_low"].values.astype(np.float64),
        ask_close=df["ask_close"].values.astype(np.float64),
    )


def plan_acquisition(
    pairs: list[TradingPair],
    start: str,
    end: str,
    raw_dir: Path,
) -> dict[str, Any]:
    """Generate an acquisition plan with partition counts and estimates."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    partitions = []
    for pair in pairs:
        for year, month in _month_range(
            start_dt.year, start_dt.month,
            end_dt.year, end_dt.month,
        ):
            for side in ("bid", "ask"):
                instrument = PAIR_TO_INSTRUMENT[pair].upper()
                part_path = (
                    raw_dir / instrument / f"price={side}"
                    / f"year={year}" / f"month={month:02d}"
                    / "data.json"
                )
                exists = part_path.exists() and part_path.stat().st_size > 0
                partitions.append({
                    "pair": pair.value,
                    "year": year,
                    "month": month,
                    "side": side,
                    "exists": exists,
                })

    total = len(partitions)
    existing = sum(1 for p in partitions if p["exists"])

    return {
        "pairs": [p.value for p in pairs],
        "start": start,
        "end": end,
        "total_partitions": total,
        "existing_verified": existing,
        "missing_partitions": total - existing,
        "estimated_raw_mb_per_partition": "1-5",
        "estimated_total_raw_mb": f"{(total - existing) * 2}-{(total - existing) * 5}",
        "plan_hash": hashlib.md5(
            json.dumps(partitions, sort_keys=True).encode()
        ).hexdigest()[:12],
    }
