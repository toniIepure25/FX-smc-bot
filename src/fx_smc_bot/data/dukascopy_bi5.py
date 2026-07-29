"""Native Dukascopy BI5 candle transport for data-quality repair.

This module mirrors the pinned ``dukascopy-node`` M1 candle semantics for
operational data recovery. It intentionally contains no event, outcome,
matching, inference, or strategy logic.
"""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import struct
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USDJPY_INTEGER_SCALE = 1000
DUKASCOPY_ROOT = "https://datafeed.dukascopy.com/datafeed"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class NativeFetchResult:
    """Raw provider response for one day/side unit."""

    url: str
    status: str
    http_status: int | None
    content_length: int
    elapsed_seconds: float
    attempts: int
    error: str = ""
    raw_path: str = ""
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "content_length": self.content_length,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "attempts": self.attempts,
            "error": self.error,
            "raw_path": self.raw_path,
            "checksum": self.checksum,
        }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dukascopy_candle_url(
    pair: str,
    day: date,
    side: str,
) -> str:
    """Return the pinned dukascopy-node M1 candle BI5 URL.

    Dukascopy datafeed paths use zero-based month folders.
    """
    side_upper = side.upper()
    if side_upper not in {"BID", "ASK"}:
        raise ValueError(f"Unsupported side: {side}")
    return (
        f"{DUKASCOPY_ROOT}/{pair.upper()}/{day.year}/"
        f"{day.month - 1:02d}/{day.day:02d}/{side_upper}_candles_min_1.bi5"
    )


def fetch_bi5_day(
    url: str,
    out_file: Path,
    *,
    retries: int = 3,
    backoff_seconds: float = 1.0,
    user_agent: str = BROWSER_USER_AGENT,
    timeout_seconds: int = 30,
) -> NativeFetchResult:
    """Fetch one BI5 day with browser UA and atomic write."""
    started = time.monotonic()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    http_status: int | None = None

    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": user_agent})
            with urlopen(req, timeout=timeout_seconds) as response:
                http_status = getattr(response, "status", None)
                body = response.read()
            if http_status != 200:
                last_error = f"HTTP {http_status}"
            elif not body:
                last_error = "empty provider response"
            else:
                tmp = out_file.with_suffix(out_file.suffix + ".tmp")
                tmp.write_bytes(body)
                os.replace(str(tmp), str(out_file))
                return NativeFetchResult(
                    url=url,
                    status="PASS",
                    http_status=http_status,
                    content_length=len(body),
                    elapsed_seconds=time.monotonic() - started,
                    attempts=attempt,
                    raw_path=str(out_file),
                    checksum=sha256_bytes(body),
                )
        except HTTPError as exc:
            http_status = exc.code
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                body = ""
            last_error = f"HTTP {exc.code}: {body[:200]}"
        except (URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < retries:
            time.sleep(backoff_seconds * attempt)

    return NativeFetchResult(
        url=url,
        status="FAIL",
        http_status=http_status,
        content_length=0,
        elapsed_seconds=time.monotonic() - started,
        attempts=retries,
        error=last_error,
    )


def parse_bi5_m1_candles(
    payload: bytes,
    day: date,
    *,
    integer_scale: int = USDJPY_INTEGER_SCALE,
    ignore_flats: bool = True,
) -> list[dict[str, Any]]:
    """Parse M1 candle BI5 bytes using dukascopy-node's field semantics."""
    decompressed = lzma.decompress(payload, format=lzma.FORMAT_AUTO)
    if len(decompressed) % 24 != 0:
        raise ValueError(
            f"Decompressed candle payload length is not divisible by 24: "
            f"{len(decompressed)}"
        )

    start_ms = int(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        .timestamp() * 1000
    )
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(decompressed), 24):
        sec, open_raw, close_raw, low_raw, high_raw, volume = struct.unpack(
            ">iiiii f",
            decompressed[offset: offset + 24],
        )
        if ignore_flats and volume == 0:
            continue
        rows.append({
            "timestamp": start_ms + sec * 1000,
            "open": open_raw / integer_scale,
            "high": high_raw / integer_scale,
            "low": low_raw / integer_scale,
            "close": close_raw / integer_scale,
            "volume": float(volume),
            "open_raw": open_raw,
            "high_raw": high_raw,
            "low_raw": low_raw,
            "close_raw": close_raw,
        })
    return rows


def validate_m1_rows(rows: list[dict[str, Any]], day: date) -> dict[str, Any]:
    start_ms = int(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        .timestamp() * 1000
    )
    end_ms = start_ms + int(timedelta(days=1).total_seconds() * 1000)
    timestamps = [int(r["timestamp"]) for r in rows]
    monotonic = timestamps == sorted(timestamps)
    in_range = all(start_ms <= ts < end_ms for ts in timestamps)
    ohlc_valid = all(
        r["high_raw"] >= max(r["open_raw"], r["close_raw"])
        and r["low_raw"] <= min(r["open_raw"], r["close_raw"])
        for r in rows
    )
    return {
        "row_count": len(rows),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "monotonic_timestamps": monotonic,
        "timestamps_in_requested_day": in_range,
        "ohlc_valid": ohlc_valid,
    }


def rows_checksum(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
