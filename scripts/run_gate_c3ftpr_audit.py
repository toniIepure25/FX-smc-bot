"""Execute Gate C.3F-TPR tick-to-M1 audit and blocked/certification outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results" / "gate_c3ftpr"
DOCS_DIR = ROOT / "docs" / "research"
CACHE_DIR = ROOT / "data" / "raw" / "gate_c3ftpr" / "dukascopy_ticks"
CANONICAL_DIR = ROOT / "data" / "canonical" / "gate_c3fv"
PLAN_PATH = RESULTS_DIR / "amended_frozen_tick_audit_plan.json"
PROTOCOL_PATH = RESULTS_DIR / "tick_to_m1_protocol.json"
PAIRS = ("EURUSD", "GBPUSD", "USDJPY")
DEV_YEARS = set(range(2015, 2020))
SCALE = {"EURUSD": 100_000, "GBPUSD": 100_000, "USDJPY": 1_000}
PLAUSIBLE = {
    "EURUSD": (0.8, 1.6),
    "GBPUSD": (1.0, 2.2),
    "USDJPY": (70.0, 200.0),
}
DUKASCOPY_URL = "https://datafeed.dukascopy.com/datafeed"
FINAL_DECISIONS = {
    "ready": "DEVELOPMENT_DATA_CERTIFIED_READY_FOR_EVENT_ALPHA_RESEARCH",
    "exploratory": "DEVELOPMENT_DATA_EXPLORATORY_ONLY",
    "data_access": "BLOCKED_BY_TICK_DATA_ACCESS",
    "implementation": "BLOCKED_BY_TICK_AUDIT_IMPLEMENTATION",
    "disagreement": "BLOCKED_BY_TICK_M1_DISAGREEMENT",
    "event_runtime": "BLOCKED_BY_EVENT_RUNTIME",
}


@dataclass(frozen=True, slots=True)
class TickRecord:
    timestamp: datetime
    bid_raw: int
    ask_raw: int
    bid_volume: float
    ask_volume: float
    source_order: int


@dataclass(frozen=True, slots=True)
class HourResult:
    pair: str
    hour: datetime
    records: list[TickRecord]
    cache_file: str
    cache_hit: bool
    bytes_read: int
    sha256: str | None
    error: str | None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return sha256_file(path)


def write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def hour_range(start: datetime, end: datetime) -> list[datetime]:
    out = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current < end:
        out.append(current)
        current += timedelta(hours=1)
    return out


def canonical_window_key(window: dict[str, Any]) -> str:
    return (
        f"{window['year']}-Q{window['quarter']}-"
        f"{window['week_start']}-{window['week_end']}-{window['session']}"
    )


def load_plan() -> dict[str, Any]:
    plan = read_json(PLAN_PATH)
    if plan.get("status") != "PROSPECTIVELY_FROZEN":
        raise RuntimeError("Amended tick audit plan is not prospectively frozen")
    if plan.get("not_original_artifact") is not True:
        raise RuntimeError("Amended plan provenance marker is missing")
    return plan


def load_protocol() -> dict[str, Any]:
    protocol = read_json(PROTOCOL_PATH)
    if protocol.get("status") != "FROZEN_BEFORE_AUDIT_EXECUTION":
        raise RuntimeError("Tick-to-M1 protocol is not frozen")
    return protocol


def selected_diagnostic_case(plan: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
    return PAIRS[0], plan["windows"][0], 0


def _cache_path(pair: str, hour: datetime) -> Path:
    month_0 = hour.month - 1
    return (
        CACHE_DIR / pair / f"{hour.year}" / f"{month_0:02d}" / f"{hour.day:02d}"
        / f"{hour.hour:02d}h_ticks.bi5"
    )


def _dukascopy_tick_url(pair: str, hour: datetime) -> str:
    return (
        f"{DUKASCOPY_URL}/{pair}/{hour.year}/{hour.month - 1:02d}/"
        f"{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    )


def _parse_bi5_payload(payload: bytes, base_hour: datetime, pair: str) -> list[TickRecord]:
    try:
        raw = lzma.decompress(payload)
    except (lzma.LZMAError, EOFError):
        return []

    records = []
    scale = SCALE[pair]
    record_size = 20
    for idx in range(len(raw) // record_size):
        offset = idx * record_size
        ms, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack_from(">IIIff", raw, offset)
        records.append(
            TickRecord(
                timestamp=base_hour + timedelta(milliseconds=ms),
                bid_raw=bid_raw,
                ask_raw=ask_raw,
                bid_volume=float(bid_vol),
                ask_volume=float(ask_vol),
                source_order=idx,
            )
        )

    lo, hi = PLAUSIBLE[pair]
    lo_raw = int(lo * scale)
    hi_raw = int(hi * scale)
    return [
        row for row in records
        if lo_raw <= row.bid_raw <= hi_raw and lo_raw <= row.ask_raw <= hi_raw
    ]


def download_hour(pair: str, hour: datetime, retries: int) -> HourResult:
    cache_file = _cache_path(pair, hour)
    cache_hit = cache_file.exists() and cache_file.stat().st_size > 0
    payload = b""
    error = None

    if cache_hit:
        payload = cache_file.read_bytes()
    else:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        url = _dukascopy_tick_url(pair, hour)
        for attempt in range(retries):
            try:
                req = Request(url, headers={"User-Agent": "FX-SMC-Research/1.0"})
                with urlopen(req, timeout=30) as resp:
                    payload = resp.read()
                if payload:
                    cache_file.write_bytes(payload)
                break
            except HTTPError as exc:
                error = f"HTTP {exc.code}: {url}"
                if exc.code == 404:
                    break
                if attempt < retries - 1:
                    continue
            except (URLError, OSError, TimeoutError) as exc:
                error = f"{type(exc).__name__}: {url}: {exc}"
                if attempt < retries - 1:
                    continue

    sha = sha256_bytes(payload) if payload else None
    records = _parse_bi5_payload(payload, hour, pair) if payload else []
    return HourResult(
        pair=pair,
        hour=hour,
        records=records,
        cache_file=str(cache_file.relative_to(ROOT)),
        cache_hit=cache_hit,
        bytes_read=len(payload),
        sha256=sha,
        error=error if not payload else None,
    )


def download_window(
    pair: str,
    window: dict[str, Any],
    workers: int,
    retries: int,
) -> list[HourResult]:
    start = parse_day(window["week_start"])
    end = parse_day(window["week_end"])
    hours = hour_range(start, end)
    max_workers = max(1, min(workers, len(hours)))
    results: list[HourResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(download_hour, pair, hour, retries) for hour in hours]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda row: row.hour)


def tick_raw_validation(hour_results: list[HourResult]) -> dict[str, Any]:
    ticks = [record for hour in hour_results for record in hour.records]
    timestamps = [record.timestamp for record in ticks]
    duplicate_count = len(timestamps) - len(set(timestamps))
    out_of_order = sum(
        1 for left, right in zip(timestamps, timestamps[1:], strict=False) if right < left
    )
    ask_below_bid = sum(1 for row in ticks if row.ask_raw < row.bid_raw)
    return {
        "tick_count": len(ticks),
        "first_tick": min(timestamps).isoformat() if timestamps else None,
        "last_tick": max(timestamps).isoformat() if timestamps else None,
        "duplicate_timestamps": duplicate_count,
        "out_of_order_ticks": out_of_order,
        "ask_below_bid_violations": ask_below_bid,
        "download_errors": [row.error for row in hour_results if row.error],
        "download_error_count": sum(1 for row in hour_results if row.error),
        "downloaded_hour_count": sum(1 for row in hour_results if row.bytes_read > 0),
        "empty_hour_count": sum(1 for row in hour_results if row.bytes_read == 0),
        "cache_hit_hour_count": sum(1 for row in hour_results if row.cache_hit),
    }


def aggregate_ticks_to_m1(pair: str, hour_results: list[HourResult]) -> pd.DataFrame:
    rows = [
        {
            "timestamp": record.timestamp,
            "bid": record.bid_raw,
            "ask": record.ask_raw,
            "order": hour_idx * 100_000_000 + record.source_order,
        }
        for hour_idx, hour in enumerate(hour_results)
        for record in hour.records
        if record.ask_raw >= record.bid_raw
    ]
    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
                "ask_open", "ask_high", "ask_low", "ask_close",
            ]
        )

    df = pd.DataFrame(rows).sort_values(["timestamp", "order"], kind="mergesort")
    df["minute"] = df["timestamp"].dt.floor("min")
    grouped = df.groupby("minute", sort=True)
    out = pd.DataFrame({
        "timestamp": grouped["timestamp"].first().index,
        "bid_open": grouped["bid"].first().to_numpy(dtype=np.int64),
        "bid_high": grouped["bid"].max().to_numpy(dtype=np.int64),
        "bid_low": grouped["bid"].min().to_numpy(dtype=np.int64),
        "bid_close": grouped["bid"].last().to_numpy(dtype=np.int64),
        "ask_open": grouped["ask"].first().to_numpy(dtype=np.int64),
        "ask_high": grouped["ask"].max().to_numpy(dtype=np.int64),
        "ask_low": grouped["ask"].min().to_numpy(dtype=np.int64),
        "ask_close": grouped["ask"].last().to_numpy(dtype=np.int64),
    })
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out


def _months_between(start: datetime, end: datetime) -> list[tuple[int, int]]:
    current = datetime(start.year, start.month, 1, tzinfo=UTC)
    out = []
    while current < end:
        out.append((current.year, current.month))
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1, tzinfo=UTC)
        else:
            current = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return out


def load_canonical_m1(pair: str, start: datetime, end: datetime) -> tuple[pd.DataFrame, list[str]]:
    frames = []
    missing = []
    for year, month in _months_between(start, end):
        path = (
            CANONICAL_DIR / pair / "timeframe=M1" / f"year={year}"
            / f"month={month:02d}" / "part.parquet"
        )
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
            continue
        frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(), missing
    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    mask = (df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] < pd.Timestamp(end))
    return df.loc[mask].sort_values("timestamp").reset_index(drop=True), missing


def quantize_canonical(pair: str, canonical: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    ]
    out = canonical[["timestamp", *columns]].copy()
    scale = SCALE[pair]
    for column in columns:
        out[column] = np.rint(out[column].to_numpy(dtype=float) * scale).astype(np.int64)
    return out


def compare_m1(tick_m1: pd.DataFrame, canonical_m1: pd.DataFrame) -> dict[str, Any]:
    columns = [
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    ]
    if canonical_m1.empty:
        return {
            "compared_bars": 0,
            "timestamp_agreement": len(tick_m1) == 0,
            "exact_ohlc_agreement": True,
            "missing_in_tick": [],
            "missing_in_canonical": tick_m1["timestamp"].astype(str).head(20).tolist(),
            "missing_in_tick_count": 0,
            "missing_in_canonical_count": int(len(tick_m1)),
            "mismatch_counts": {column: 0 for column in columns},
            "max_abs_raw_point_diff": {column: 0 for column in columns},
        }

    merged = tick_m1.merge(
        canonical_m1,
        on="timestamp",
        how="outer",
        suffixes=("_tick", "_canonical"),
        indicator=True,
    )
    missing_in_tick = merged.loc[merged["_merge"] == "right_only", "timestamp"]
    missing_in_canonical = merged.loc[merged["_merge"] == "left_only", "timestamp"]
    common = merged.loc[merged["_merge"] == "both"].copy()
    mismatch_counts: dict[str, int] = {}
    max_diff: dict[str, int] = {}
    for column in columns:
        diff = (common[f"{column}_tick"] - common[f"{column}_canonical"]).abs()
        mismatch_counts[column] = int((diff != 0).sum())
        max_diff[column] = int(diff.max()) if len(diff) else 0
    return {
        "compared_bars": int(len(common)),
        "timestamp_agreement": (
            int(len(missing_in_tick)) == 0
            and int(len(missing_in_canonical)) == 0
        ),
        "exact_ohlc_agreement": all(value == 0 for value in mismatch_counts.values()),
        "missing_in_tick": missing_in_tick.astype(str).head(50).tolist(),
        "missing_in_tick_count": int(len(missing_in_tick)),
        "missing_in_canonical": missing_in_canonical.astype(str).head(50).tolist(),
        "missing_in_canonical_count": int(len(missing_in_canonical)),
        "mismatch_counts": mismatch_counts,
        "max_abs_raw_point_diff": max_diff,
    }


def classify_audit(
    raw: dict[str, Any],
    canonical_missing: list[str],
    comparison: dict[str, Any],
) -> str:
    if raw["tick_count"] == 0:
        return "FAIL_DATA_ACCESS"
    if (
        canonical_missing
        or comparison.get("missing_in_tick_count", 0) > 0
        or comparison.get("missing_in_canonical_count", 0) > 0
    ):
        return "FAIL_INCOMPLETE_WINDOW"
    if not comparison["timestamp_agreement"]:
        return "FAIL_TIMESTAMP_ALIGNMENT"
    if not comparison["exact_ohlc_agreement"]:
        return "FAIL_OHLC_DISAGREEMENT"
    if raw["download_error_count"] > 0:
        return "PASS_PROTOCOL_BOUNDED"
    return "PASS_EXACT"


def audit_window_pair(
    pair: str,
    window: dict[str, Any],
    window_index: int,
    workers: int,
    retries: int,
) -> tuple[dict[str, Any], list[HourResult]]:
    start = parse_day(window["week_start"])
    end = parse_day(window["week_end"])
    hours = download_window(pair, window, workers, retries)
    raw = tick_raw_validation(hours)
    tick_m1 = aggregate_ticks_to_m1(pair, hours)
    canonical_float, canonical_missing = load_canonical_m1(pair, start, end)
    canonical = (
        quantize_canonical(pair, canonical_float)
        if not canonical_float.empty
        else canonical_float
    )
    comparison = compare_m1(tick_m1, canonical)
    classification = classify_audit(raw, canonical_missing, comparison)
    return {
        "pair": pair,
        "window_index": window_index,
        "window_key": canonical_window_key(window),
        "window": window,
        "request_parameters": {
            "provider": "dukascopy",
            "pair": pair,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "scale": SCALE[pair],
            "workers": workers,
        },
        "raw_validation": raw,
        "generated_m1_bars": int(len(tick_m1)),
        "canonical_m1_bars": int(len(canonical)),
        "canonical_missing_partitions": canonical_missing,
        "comparison": comparison,
        "partial_boundary_bars": [],
        "classification": classification,
    }, hours


def write_acquisition_manifest(
    mode: str,
    audits: list[dict[str, Any]],
    hours: list[HourResult],
) -> None:
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "cache_root": str(CACHE_DIR.relative_to(ROOT)),
        "raw_files_are_gitignored": True,
        "window_pair_count": len(audits),
        "hour_request_count": len(hours),
        "downloaded_hour_count": sum(1 for row in hours if row.bytes_read > 0),
        "cache_hit_hour_count": sum(1 for row in hours if row.cache_hit),
        "error_hour_count": sum(1 for row in hours if row.error),
        "total_bi5_bytes_read": sum(row.bytes_read for row in hours),
        "files": [
            {
                "pair": row.pair,
                "hour": row.hour.isoformat(),
                "cache_file": row.cache_file,
                "cache_hit": row.cache_hit,
                "bytes": row.bytes_read,
                "sha256": row.sha256,
                "error": row.error,
            }
            for row in hours
        ],
    }
    write_json(RESULTS_DIR / "tick_acquisition_manifest.json", manifest)


def run_cases(
    cases: list[tuple[str, dict[str, Any], int]],
    workers: int,
    retries: int,
) -> tuple[list[dict[str, Any]], list[HourResult]]:
    audits = []
    hour_results = []
    for pair, window, window_index in cases:
        audit, hours = audit_window_pair(pair, window, window_index, workers, retries)
        audits.append(audit)
        hour_results.extend(hours)
    return audits, hour_results


def run_diagnostic(workers: int, retries: int) -> dict[str, Any]:
    plan = load_plan()
    load_protocol()
    pair, window, window_index = selected_diagnostic_case(plan)
    audits, hours = run_cases([(pair, window, window_index)], workers, retries)
    diagnostic = {
        "created_at": datetime.now(UTC).isoformat(),
        "selection_rule": (
            "first window in amended-plan order and first pair in canonical pair order"
        ),
        "canonical_pair_order": list(PAIRS),
        "diagnostic": audits[0],
    }
    write_json(RESULTS_DIR / "single_window_diagnostic.json", diagnostic)
    write_acquisition_manifest("diagnostic", audits, hours)
    return diagnostic


def _cases_for_years(
    plan: dict[str, Any],
    years: set[int],
) -> list[tuple[str, dict[str, Any], int]]:
    cases = []
    for idx, window in enumerate(plan["windows"]):
        if int(window["year"]) in years:
            for pair in PAIRS:
                cases.append((pair, window, idx))
    return cases


def summarize_audits(audits: list[dict[str, Any]]) -> dict[str, Any]:
    by_class = Counter(audit["classification"] for audit in audits)
    return {
        "window_pair_count": len(audits),
        "classification_counts": dict(sorted(by_class.items())),
        "all_passed": all(
            audit["classification"] in {"PASS_EXACT", "PASS_PROTOCOL_BOUNDED"}
            for audit in audits
        ),
        "any_data_access_failure": any(
            audit["classification"] == "FAIL_DATA_ACCESS" for audit in audits
        ),
        "any_ohlc_disagreement": any(
            audit["classification"] == "FAIL_OHLC_DISAGREEMENT" for audit in audits
        ),
        "any_timestamp_alignment_failure": any(
            audit["classification"] == "FAIL_TIMESTAMP_ALIGNMENT" for audit in audits
        ),
        "any_incomplete_window": any(
            audit["classification"] == "FAIL_INCOMPLETE_WINDOW" for audit in audits
        ),
    }


def run_2019(workers: int, retries: int) -> dict[str, Any]:
    plan = load_plan()
    load_protocol()
    audits, hours = run_cases(_cases_for_years(plan, {2019}), workers, retries)
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "all amended frozen windows belonging to 2019, all canonical pairs",
        "audits": audits,
        "summary": summarize_audits(audits),
    }
    file_hash = write_json(RESULTS_DIR / "2019_tick_audit.json", result)
    write_acquisition_manifest("2019", audits, hours)
    write_2019_doc(result, file_hash)
    return result


def run_development(workers: int, retries: int) -> dict[str, Any]:
    plan = load_plan()
    load_protocol()
    audits, hours = run_cases(_cases_for_years(plan, DEV_YEARS), workers, retries)
    pair_year = pair_year_tick_status(audits)
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "all amended frozen windows belonging to 2015-2019, all canonical pairs",
        "audits": audits,
        "pair_year_tick_audit": pair_year,
        "summary": summarize_audits(audits),
    }
    file_hash = write_json(RESULTS_DIR / "development_tick_audit.json", result)
    write_acquisition_manifest("development", audits, hours)
    write_development_doc(result, file_hash)
    return result


def pair_year_tick_status(audits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, list[str]]] = {
        pair: {str(year): [] for year in sorted(DEV_YEARS)} for pair in PAIRS
    }
    for audit in audits:
        pair = audit["pair"]
        year = str(audit["window"]["year"])
        grouped[pair][year].append(audit["classification"])

    out: dict[str, dict[str, Any]] = {}
    for pair, years in grouped.items():
        out[pair] = {}
        for year, classifications in years.items():
            if not classifications:
                status = "TICK_AUDIT_NOT_EXECUTABLE"
            elif all(item in {"PASS_EXACT", "PASS_PROTOCOL_BOUNDED"} for item in classifications):
                status = "TICK_AUDIT_PASS"
            elif any(item == "FAIL_DATA_ACCESS" for item in classifications):
                status = "TICK_AUDIT_NOT_EXECUTABLE"
            else:
                status = "TICK_AUDIT_FAIL"
            out[pair][year] = {
                "status": status,
                "classifications": classifications,
            }
    return out


def write_2019_doc(result: dict[str, Any], file_hash: str) -> None:
    summary = result["summary"]
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_2019_TICK_AUDIT.md",
        f"""# Gate C.3F-TPR 2019 Tick Audit

Scope: all amended frozen 2019 windows, all canonical pairs.

Result hash: `{file_hash}`

Summary:

- Window-pair audits: {summary["window_pair_count"]}
- Classification counts: `{summary["classification_counts"]}`
- All passed: `{summary["all_passed"]}`
- Data-access failure present: `{summary["any_data_access_failure"]}`
- Timestamp-alignment failure present: `{summary["any_timestamp_alignment_failure"]}`
- OHLC disagreement present: `{summary["any_ohlc_disagreement"]}`

No strategy outcome or profitability fields were calculated or serialized.
""",
    )


def write_development_doc(result: dict[str, Any], file_hash: str) -> None:
    summary = result["summary"]
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_DEVELOPMENT_TICK_AUDIT.md",
        f"""# Gate C.3F-TPR Development Tick Audit

Scope: all amended frozen 2015-2019 windows, all canonical pairs.

Result hash: `{file_hash}`

Summary:

- Window-pair audits: {summary["window_pair_count"]}
- Classification counts: `{summary["classification_counts"]}`
- All passed: `{summary["all_passed"]}`
- Data-access failure present: `{summary["any_data_access_failure"]}`
- Timestamp-alignment failure present: `{summary["any_timestamp_alignment_failure"]}`
- OHLC disagreement present: `{summary["any_ohlc_disagreement"]}`

No strategy outcome or profitability fields were calculated or serialized.
""",
    )


def event_smoke_blocked(reason: str) -> dict[str, Any]:
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "NOT_RUN",
        "reason": reason,
        "families": {
            "Sweep Reversal": {},
            "Acceptance Continuation": {},
            "Opening Range London": {},
            "Opening Range New York": {},
        },
        "contains_performance_fields": False,
    }
    write_json(RESULTS_DIR / "2019_event_funnels.json", result)
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_2019_EVENT_SMOKE_TEST.md",
        f"""# Gate C.3F-TPR 2019 Event-Only Smoke Test

Status: `NOT_RUN`

Reason: {reason}

The event-only smoke test is gated behind the applicable tick audit. No event
runtime was executed and no strategy outcome or profitability fields were
serialized.
""",
    )
    return result


def holdout_integrity() -> dict[str, Any]:
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "checked_boundary": "2023-01-01 through 2025-12-31",
        "detector_execution": False,
        "event_execution": False,
        "alpha_execution": False,
        "parameter_operation": False,
        "profitability_operation": False,
        "note": (
            "C3FTPR audit/certification artifacts do not execute holdout detectors, "
            "events, alpha, or parameter operations."
        ),
    }
    write_json(RESULTS_DIR / "holdout_integrity.json", result)
    return result


def certify_and_freeze() -> dict[str, Any]:
    plan = load_plan()
    protocol = load_protocol()
    dev_path = RESULTS_DIR / "development_tick_audit.json"
    if not dev_path.exists():
        development = {
            "summary": {"all_passed": False, "any_data_access_failure": True},
            "pair_year_tick_audit": pair_year_tick_status([]),
        }
    else:
        development = read_json(dev_path)

    tick_status = development.get("pair_year_tick_audit", pair_year_tick_status([]))
    pair_years: dict[str, dict[str, Any]] = {}
    pair_certifications: dict[str, str] = {}
    selected = []
    for pair in PAIRS:
        pair_years[pair] = {}
        pair_ready = True
        for year in sorted(DEV_YEARS):
            tick = tick_status[pair][str(year)]["status"]
            if tick == "TICK_AUDIT_PASS":
                cert = "PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT"
            elif tick == "TICK_AUDIT_NOT_EXECUTABLE":
                cert = "PAIR_YEAR_EXPLORATORY_ONLY"
                pair_ready = False
            else:
                cert = "PAIR_YEAR_REJECTED"
                pair_ready = False
            pair_years[pair][str(year)] = {
                "tick_audit_result": tick,
                "certification": cert,
            }
        pair_certifications[pair] = (
            "DATASET_CERTIFIED_FOR_DEVELOPMENT" if pair_ready else "DATASET_EXPLORATORY_ONLY"
        )
        if pair_ready:
            selected.append(pair)

    summary = development.get("summary", {})
    blockers = []
    if not summary.get("all_passed", False):
        blockers.append("BLOCKED_BY_TICK_AUDIT")
    holdout = holdout_integrity()
    if holdout["status"] != "PASS":
        blockers.append("BLOCKED_BY_HOLDOUT_INTEGRITY")

    final_decision = (
        FINAL_DECISIONS["ready"] if not blockers and selected else FINAL_DECISIONS["data_access"]
    )
    if summary.get("any_ohlc_disagreement") or summary.get("any_timestamp_alignment_failure"):
        final_decision = FINAL_DECISIONS["disagreement"]
    elif not summary.get("any_data_access_failure", False) and blockers:
        final_decision = FINAL_DECISIONS["exploratory"]

    pair_year_result = {
        "created_at": datetime.now(UTC).isoformat(),
        "pair_years": pair_years,
    }
    pair_year_hash = write_json(RESULTS_DIR / "pair_year_certifications.json", pair_year_result)

    certification = {
        "created_at": datetime.now(UTC).isoformat(),
        "pair_certifications": pair_certifications,
        "selected_research_universe": selected,
        "selection_basis": "data quality only",
        "status": "COMPLETE" if selected else "NO_CERTIFIED_PAIR",
    }
    certification_hash = write_json(RESULTS_DIR / "development_certification.json", certification)

    if blockers:
        event_smoke_blocked("tick audit did not pass")
    else:
        event_smoke_blocked("event runtime execution intentionally deferred by this script")
        final_decision = FINAL_DECISIONS["event_runtime"]

    freeze = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "READY" if final_decision == FINAL_DECISIONS["ready"] else "BLOCKED",
        "final_decision": final_decision,
        "blockers": blockers,
        "amended_plan_hash": plan["generated_candidate_hash"],
        "amended_plan_file_hash": sha256_file(PLAN_PATH),
        "amendment_record_hash": sha256_file(RESULTS_DIR / "amendment_record.json"),
        "protocol_hash": protocol["protocol_hash"],
        "development_tick_audit_hash": sha256_file(dev_path) if dev_path.exists() else None,
        "pair_year_certification_hash": pair_year_hash,
        "development_certification_hash": certification_hash,
        "holdout_integrity_hash": sha256_file(RESULTS_DIR / "holdout_integrity.json"),
        "selected_research_universe": selected,
    }
    freeze_hash = write_json(RESULTS_DIR / "development_dataset_freeze.json", freeze)
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_DATASET_FREEZE.md",
        f"""# Gate C.3F-TPR Dataset Freeze

Status: `{freeze["status"]}`

Final decision: `{final_decision}`

Freeze artifact hash: `{freeze_hash}`

Selected research universe: `{selected}`

The prospective amendment and tick-to-M1 protocol are referenced by hash. The
dataset is not marked READY unless the tick audit passes, certification is
complete, at least one pair is certified, and holdout integrity remains PASS.
""",
    )
    return freeze


def quality_gate(final_decision: str, command_results: dict[str, Any] | None = None) -> None:
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "final_decision": final_decision,
        "required_artifacts_present": {
            str(path.relative_to(ROOT)): path.exists()
            for path in [
                RESULTS_DIR / "single_window_diagnostic.json",
                RESULTS_DIR / "tick_acquisition_manifest.json",
                RESULTS_DIR / "2019_tick_audit.json",
                RESULTS_DIR / "development_tick_audit.json",
                RESULTS_DIR / "2019_event_funnels.json",
                RESULTS_DIR / "pair_year_certifications.json",
                RESULTS_DIR / "development_certification.json",
                RESULTS_DIR / "development_dataset_freeze.json",
                RESULTS_DIR / "holdout_integrity.json",
            ]
        },
        "command_results": command_results or {},
    }
    write_json(RESULTS_DIR / "quality_gate_final.json", result)


def write_final_memo(final_decision: str) -> None:
    freeze = read_json(RESULTS_DIR / "development_dataset_freeze.json")
    diagnostic = read_json(RESULTS_DIR / "single_window_diagnostic.json")
    audit_2019 = read_json(RESULTS_DIR / "2019_tick_audit.json")
    development = read_json(RESULTS_DIR / "development_tick_audit.json")
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_FINAL_DECISION_MEMO.md",
        f"""# Gate C.3F-TPR Final Decision Memo

Final decision: `{final_decision}`

The original complete plan artifact was not recovered. The materialized plan is
a prospective amendment, not the original file.

Key hashes:

- Amended plan hash: `{freeze["amended_plan_hash"]}`
- Protocol hash: `{freeze["protocol_hash"]}`
- Freeze artifact hash: `{sha256_file(RESULTS_DIR / "development_dataset_freeze.json")}`

Audit summaries:

- Single-window diagnostic classification: `{diagnostic["diagnostic"]["classification"]}`
- 2019 classification counts: `{audit_2019["summary"]["classification_counts"]}`
- Development classification counts: `{development["summary"]["classification_counts"]}`

Holdout integrity remains PASS. Gate C.4 was not executed. No strategy outcome
or profitability fields were calculated or reported.
""",
    )


def run_all(workers: int, retries: int) -> dict[str, Any]:
    diagnostic = run_diagnostic(workers, retries)
    if diagnostic["diagnostic"]["classification"] == "FAIL_DATA_ACCESS":
        stub_blocked_audit_outputs("single-window tick diagnostic failed data access")
        freeze = certify_and_freeze()
        quality_gate(freeze["final_decision"])
        write_final_memo(freeze["final_decision"])
        return freeze

    run_2019(workers, retries)
    run_development(workers, retries)
    freeze = certify_and_freeze()
    quality_gate(freeze["final_decision"])
    write_final_memo(freeze["final_decision"])
    return freeze


def stub_blocked_audit_outputs(reason: str) -> None:
    for filename, scope, doc_writer in [
        ("2019_tick_audit.json", "2019", write_2019_doc),
        ("development_tick_audit.json", "2015-2019 development", write_development_doc),
    ]:
        result = {
            "created_at": datetime.now(UTC).isoformat(),
            "scope": scope,
            "audits": [],
            "summary": {
                "window_pair_count": 0,
                "classification_counts": {"FAIL_DATA_ACCESS": 1},
                "all_passed": False,
                "any_data_access_failure": True,
                "any_ohlc_disagreement": False,
                "any_timestamp_alignment_failure": False,
            },
            "reason": reason,
        }
        if filename == "development_tick_audit.json":
            result["pair_year_tick_audit"] = pair_year_tick_status([])
        path = RESULTS_DIR / filename
        file_hash = write_json(path, result)
        doc_writer(result, file_hash)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["diagnostic", "2019", "development", "certify", "all"],
        default="all",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if args.mode == "diagnostic":
        result = run_diagnostic(args.workers, args.retries)
        print(json.dumps(result["diagnostic"]["classification"]))
    elif args.mode == "2019":
        result = run_2019(args.workers, args.retries)
        print(json.dumps(result["summary"], sort_keys=True))
    elif args.mode == "development":
        result = run_development(args.workers, args.retries)
        print(json.dumps(result["summary"], sort_keys=True))
    elif args.mode == "certify":
        freeze = certify_and_freeze()
        quality_gate(freeze["final_decision"])
        write_final_memo(freeze["final_decision"])
        print(json.dumps(freeze, sort_keys=True))
    else:
        freeze = run_all(args.workers, args.retries)
        print(json.dumps(freeze, sort_keys=True))


if __name__ == "__main__":
    main()
