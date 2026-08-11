"""Native Dukascopy BI5 candle transport for data-quality repair.

This module mirrors the pinned ``dukascopy-node`` M1 candle semantics for
operational data recovery. It intentionally contains no event, outcome,
matching, inference, or strategy logic.
"""
from __future__ import annotations

import hashlib
import json
import lzma
import math
import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PARSER_VERSION = "DUKASCOPY_NATIVE_BI5_V1"
HTTP_TRANSPORT_V1_ID = "DUKASCOPY_NATIVE_BI5_V1"
HTTP_TRANSPORT_V2_ID = "DUKASCOPY_NATIVE_BI5_HTTP_TRANSPORT_V2"
HTTP_TRANSPORT_V2_VERSION = "urllib-primary-curl-fallback-v1"
RECORD_SIZE_BYTES = 24
UTC_TIMEZONE = "UTC"
DUKASCOPY_ROOT = "https://datafeed.dukascopy.com/datafeed"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
RUNTIME_BUDGET_EXHAUSTED = "RUNTIME_BUDGET_EXHAUSTED"
RUNNER_DEADLINE_RESERVE_SECONDS = 8.0
MIN_DEADLINE_OPERATION_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class Bi5InstrumentMetadata:
    """Frozen structural contract for one authorized Dukascopy instrument."""

    pair: str
    instrument_code: str
    integer_scale: int
    decimal_precision: int
    timezone: str = UTC_TIMEZONE
    candle_record_size: int = RECORD_SIZE_BYTES
    endianness: str = "big"
    volume_interpretation: str = "provider_float_volume"
    flat_row_handling: str = "exclude_zero_volume"


def _metadata(pair: str, integer_scale: int, decimal_precision: int) -> Bi5InstrumentMetadata:
    return Bi5InstrumentMetadata(
        pair=pair,
        instrument_code=pair,
        integer_scale=integer_scale,
        decimal_precision=decimal_precision,
    )


BI5_INSTRUMENTS: dict[str, Bi5InstrumentMetadata] = {
    "EURUSD": _metadata("EURUSD", 100_000, 5),
    "GBPUSD": _metadata("GBPUSD", 100_000, 5),
    "AUDUSD": _metadata("AUDUSD", 100_000, 5),
    "USDJPY": _metadata("USDJPY", 1_000, 3),
    "USDCAD": _metadata("USDCAD", 100_000, 5),
    "USDCHF": _metadata("USDCHF", 100_000, 5),
    "EURJPY": _metadata("EURJPY", 1_000, 3),
    "GBPJPY": _metadata("GBPJPY", 1_000, 3),
    "AUDJPY": _metadata("AUDJPY", 1_000, 3),
}
# Kept for older repair-gate imports; A0R2 callers use ``instrument_metadata``.
USDJPY_INTEGER_SCALE = BI5_INSTRUMENTS["USDJPY"].integer_scale


def instrument_metadata(pair: str) -> Bi5InstrumentMetadata:
    """Return frozen metadata without inferring a scale from market values."""
    try:
        return BI5_INSTRUMENTS[pair.upper()]
    except KeyError as exc:
        raise ValueError(f"A0R2_UNAUTHORIZED_NATIVE_BI5_INSTRUMENT:{pair}") from exc


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
    client_id: str = "python_urllib"
    primary_status: str = ""
    failure_category: str = ""

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
            "client_id": self.client_id,
            "primary_status": self.primary_status,
            "failure_category": self.failure_category,
        }


@dataclass(frozen=True, slots=True)
class Bi5Aggregate:
    """Aggregate-only BI5 identity for cross-language transport certification."""

    raw_sha256: str
    row_count: int
    ordered_timestamp_sha256: str
    integer_ohlc_sha256: str
    volume_bits_sha256: str
    first_timestamp: int | None
    last_timestamp: int | None
    duplicate_count: int
    out_of_range_count: int
    zero_volume_excluded_count: int
    negative_zero_excluded_count: int
    timestamps_monotonic: bool
    ohlc_invariants_pass: bool
    decompression_status: str
    record_length_status: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_bytes_atomically(out_file: Path, body: bytes) -> None:
    tmp = out_file.with_suffix(out_file.suffix + ".tmp")
    tmp.write_bytes(body)
    os.replace(str(tmp), str(out_file))


def _remaining_usable_budget(
    runner_deadline_monotonic: float | None,
    *,
    reserve_seconds: float = RUNNER_DEADLINE_RESERVE_SECONDS,
) -> float | None:
    if runner_deadline_monotonic is None:
        return None
    return runner_deadline_monotonic - time.monotonic() - reserve_seconds


def _bounded_operation_timeout(
    requested_timeout_seconds: float,
    runner_deadline_monotonic: float | None,
) -> float | None:
    usable = _remaining_usable_budget(runner_deadline_monotonic)
    if usable is None:
        return float(requested_timeout_seconds)
    if usable < MIN_DEADLINE_OPERATION_SECONDS:
        return None
    return min(float(requested_timeout_seconds), usable)


def _sleep_with_deadline(delay_seconds: float, runner_deadline_monotonic: float | None) -> bool:
    usable = _remaining_usable_budget(runner_deadline_monotonic)
    if usable is not None and usable < delay_seconds:
        return False
    time.sleep(delay_seconds)
    return True


def _runtime_budget_result(
    url: str,
    *,
    started: float,
    attempts: int,
    client_id: str,
    primary_status: str = "",
    error: str = RUNTIME_BUDGET_EXHAUSTED,
) -> NativeFetchResult:
    return NativeFetchResult(
        url=url,
        status="FAIL",
        http_status=None,
        content_length=0,
        elapsed_seconds=time.monotonic() - started,
        attempts=attempts,
        error=error,
        client_id=client_id,
        primary_status=primary_status,
        failure_category=RUNTIME_BUDGET_EXHAUSTED,
    )


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
    metadata = instrument_metadata(pair)
    return (
        f"{DUKASCOPY_ROOT}/{metadata.instrument_code}/{day.year}/"
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
    runner_deadline_monotonic: float | None = None,
) -> NativeFetchResult:
    """Fetch one BI5 day with browser UA and atomic write."""
    started = time.monotonic()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    http_status: int | None = None

    for attempt in range(1, retries + 1):
        attempt_timeout = _bounded_operation_timeout(
            timeout_seconds, runner_deadline_monotonic
        )
        if attempt_timeout is None:
            return _runtime_budget_result(
                url,
                started=started,
                attempts=attempt - 1,
                client_id="python_urllib",
            )
        try:
            req = Request(url, headers={"User-Agent": user_agent})
            with urlopen(req, timeout=attempt_timeout) as response:
                http_status = getattr(response, "status", None)
                body = response.read()
            if http_status != 200:
                last_error = f"HTTP {http_status}"
            elif not body:
                last_error = "empty provider response"
            else:
                _write_bytes_atomically(out_file, body)
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
            if not _sleep_with_deadline(backoff_seconds * attempt, runner_deadline_monotonic):
                return _runtime_budget_result(
                    url,
                    started=started,
                    attempts=attempt,
                    client_id="python_urllib",
                )

    return NativeFetchResult(
        url=url,
        status="FAIL",
        http_status=http_status,
        content_length=0,
        elapsed_seconds=time.monotonic() - started,
        attempts=retries,
        error=last_error,
    )


def fetch_bi5_day_curl(
    url: str,
    out_file: Path,
    *,
    retries: int = 3,
    backoff_seconds: float = 1.0,
    user_agent: str = BROWSER_USER_AGENT,
    timeout_seconds: int = 45,
    runner_deadline_monotonic: float | None = None,
) -> NativeFetchResult:
    """Fetch one BI5 day through the OS curl client with atomic write."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    started = time.monotonic()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if not curl:
        return NativeFetchResult(
            url=url,
            status="FAIL",
            http_status=None,
            content_length=0,
            elapsed_seconds=time.monotonic() - started,
            attempts=0,
            error="CURL_NOT_FOUND",
            client_id="curl.exe",
        )

    last_error = ""
    http_status: int | None = None
    tmp = out_file.with_suffix(out_file.suffix + ".curl_tmp")
    for attempt in range(1, retries + 1):
        attempt_timeout = _bounded_operation_timeout(
            timeout_seconds, runner_deadline_monotonic
        )
        if attempt_timeout is None:
            return _runtime_budget_result(
                url,
                started=started,
                attempts=attempt - 1,
                client_id="curl.exe",
            )
        if tmp.exists():
            tmp.unlink()
        budget_limited = (
            runner_deadline_monotonic is not None
            and attempt_timeout < float(timeout_seconds)
        )
        try:
            completed = subprocess.run(
                [
                    curl,
                    "-sS",
                    "-L",
                    "--max-time",
                    f"{attempt_timeout:.3f}",
                    "-A",
                    user_agent,
                    "-o",
                    str(tmp),
                    "-w",
                    "%{http_code}",
                    url,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=attempt_timeout,
            )
        except subprocess.TimeoutExpired:
            if tmp.exists():
                tmp.unlink()
            if budget_limited:
                return _runtime_budget_result(
                    url,
                    started=started,
                    attempts=attempt,
                    client_id="curl.exe",
                )
            last_error = "curl subprocess timeout"
            http_status = None
            if attempt < retries:
                if not _sleep_with_deadline(
                    backoff_seconds * attempt, runner_deadline_monotonic
                ):
                    return _runtime_budget_result(
                        url,
                        started=started,
                        attempts=attempt,
                        client_id="curl.exe",
                    )
                continue
            break
        http_text = completed.stdout.strip()
        http_status = int(http_text) if http_text.isdigit() else 0
        body = tmp.read_bytes() if tmp.exists() else b""
        if completed.returncode == 0 and http_status == 200 and body:
            _write_bytes_atomically(out_file, body)
            if tmp.exists():
                tmp.unlink()
            return NativeFetchResult(
                url=url,
                status="PASS",
                http_status=http_status,
                content_length=len(body),
                elapsed_seconds=time.monotonic() - started,
                attempts=attempt,
                raw_path=str(out_file),
                checksum=sha256_bytes(body),
                client_id="curl.exe",
            )
        last_error = completed.stderr.strip() or f"HTTP {http_status}"
        if attempt < retries:
            if not _sleep_with_deadline(backoff_seconds * attempt, runner_deadline_monotonic):
                return _runtime_budget_result(
                    url,
                    started=started,
                    attempts=attempt,
                    client_id="curl.exe",
                )

    if tmp.exists():
        tmp.unlink()
    return NativeFetchResult(
        url=url,
        status="FAIL",
        http_status=http_status,
        content_length=0,
        elapsed_seconds=time.monotonic() - started,
        attempts=retries,
        error=last_error,
        client_id="curl.exe",
    )


def fetch_bi5_day_http_v2(
    url: str,
    out_file: Path,
    *,
    retries: int = 3,
    backoff_seconds: float = 1.0,
    user_agent: str = BROWSER_USER_AGENT,
    timeout_seconds: int = 30,
    curl_timeout_seconds: int = 45,
    runner_deadline_monotonic: float | None = None,
) -> NativeFetchResult:
    """Production HTTP V2: urllib primary, curl fallback, same URL and bytes."""
    primary = fetch_bi5_day(
        url,
        out_file,
        retries=retries,
        backoff_seconds=backoff_seconds,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        runner_deadline_monotonic=runner_deadline_monotonic,
    )
    primary.primary_status = primary.status
    if primary.status == "PASS":
        return primary
    if primary.failure_category == RUNTIME_BUDGET_EXHAUSTED:
        return primary

    if _bounded_operation_timeout(curl_timeout_seconds, runner_deadline_monotonic) is None:
        return _runtime_budget_result(
            url,
            started=time.monotonic(),
            attempts=primary.attempts,
            client_id="curl.exe",
            primary_status=primary.status,
            error=f"primary={primary.error[:240]} fallback={RUNTIME_BUDGET_EXHAUSTED}",
        )

    fallback = fetch_bi5_day_curl(
        url,
        out_file,
        retries=retries,
        backoff_seconds=backoff_seconds,
        user_agent=user_agent,
        timeout_seconds=curl_timeout_seconds,
        runner_deadline_monotonic=runner_deadline_monotonic,
    )
    fallback.attempts += primary.attempts
    fallback.primary_status = primary.status
    if fallback.status != "PASS":
        fallback.error = f"primary={primary.error[:240]} fallback={fallback.error[:240]}"
    return fallback


def parse_bi5_m1_candles(
    payload: bytes,
    day: date,
    *,
    integer_scale: int | None = None,
    pair: str | None = None,
    ignore_flats: bool = True,
) -> list[dict[str, Any]]:
    """Parse M1 candle BI5 bytes using dukascopy-node's field semantics."""
    if pair is not None:
        pair_scale = instrument_metadata(pair).integer_scale
        if integer_scale is not None and integer_scale != pair_scale:
            raise ValueError("A0R2_NATIVE_BI5_SCALE_CONTRACT_MISMATCH")
        integer_scale = pair_scale
    elif integer_scale is None:
        # Compatibility path for the pre-A0R2 USDJPY repair tests only.
        integer_scale = USDJPY_INTEGER_SCALE
    decompressed = lzma.decompress(payload, format=lzma.FORMAT_AUTO)
    if len(decompressed) % RECORD_SIZE_BYTES != 0:
        raise ValueError(
            f"Decompressed candle payload length is not divisible by 24: "
            f"{len(decompressed)}"
        )

    start_ms = int(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        .timestamp() * 1000
    )
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(decompressed), RECORD_SIZE_BYTES):
        sec, open_raw, close_raw, low_raw, high_raw, volume = struct.unpack(
            ">iiiii f",
            decompressed[offset: offset + RECORD_SIZE_BYTES],
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


def aggregate_bi5_payload(
    payload: bytes,
    *,
    pair: str,
    requested_date: date,
) -> Bi5Aggregate:
    """Hash a BI5 payload directly from its record bytes, without float formatting."""
    instrument_metadata(pair)
    decompressed = lzma.decompress(payload, format=lzma.FORMAT_AUTO)
    if len(decompressed) % RECORD_SIZE_BYTES != 0:
        raise ValueError("A0R2_BI5_INVALID_RECORD_LENGTH")
    start_ms = int(datetime(
        requested_date.year, requested_date.month, requested_date.day, tzinfo=timezone.utc
    ).timestamp() * 1000)
    end_ms = start_ms + 86_400_000
    timestamps: list[int] = []
    ohlc: list[list[int]] = []
    volume_bytes: list[bytes] = []
    zero_excluded = 0
    negative_zero_excluded = 0
    out_of_range = 0
    ohlc_valid = True
    for offset in range(0, len(decompressed), RECORD_SIZE_BYTES):
        second, open_raw, close_raw, low_raw, high_raw = struct.unpack(
            ">iiiii", decompressed[offset: offset + 20]
        )
        bits = decompressed[offset + 20: offset + 24]
        volume = struct.unpack(">f", bits)[0]
        if not math.isfinite(volume):
            raise ValueError("A0R2_BI5_NON_FINITE_VOLUME")
        if volume == 0.0:
            zero_excluded += 1
            negative_zero_excluded += int(bits == b"\x80\x00\x00\x00")
            continue
        timestamp = start_ms + second * 1000
        timestamps.append(timestamp)
        ohlc.append([timestamp, open_raw, high_raw, low_raw, close_raw])
        volume_bytes.append(bits)
        out_of_range += int(timestamp < start_ms or timestamp >= end_ms)
        ohlc_valid = ohlc_valid and (
            high_raw >= max(open_raw, close_raw) and low_raw <= min(open_raw, close_raw)
        )
    return Bi5Aggregate(
        raw_sha256=sha256_bytes(payload),
        row_count=len(timestamps),
        ordered_timestamp_sha256=sha256_bytes(
            json.dumps(timestamps, separators=(",", ":")).encode("utf-8")
        ),
        integer_ohlc_sha256=sha256_bytes(
            json.dumps(ohlc, separators=(",", ":")).encode("utf-8")
        ),
        volume_bits_sha256=sha256_bytes(b"".join(volume_bytes)),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        duplicate_count=len(timestamps) - len(set(timestamps)),
        out_of_range_count=out_of_range,
        zero_volume_excluded_count=zero_excluded,
        negative_zero_excluded_count=negative_zero_excluded,
        timestamps_monotonic=timestamps == sorted(timestamps),
        ohlc_invariants_pass=ohlc_valid,
        decompression_status="PASS",
        record_length_status="PASS",
    )


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


def raw_ohlc_checksum(rows: list[dict[str, Any]]) -> str:
    """Hash raw provider integer candles without depending on float formatting."""
    payload = [
        [
            int(row["timestamp"]),
            int(row["open_raw"]),
            int(row["high_raw"]),
            int(row["low_raw"]),
            int(row["close_raw"]),
        ]
        for row in rows
    ]
    return sha256_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def timestamp_checksum(rows: list[dict[str, Any]]) -> str:
    return sha256_bytes(
        json.dumps([int(row["timestamp"]) for row in rows], separators=(",", ":")).encode("utf-8")
    )
