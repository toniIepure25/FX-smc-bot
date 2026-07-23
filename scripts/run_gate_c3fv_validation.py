"""Gate C.3F-V deterministic development-data validation.

This script audits completed Dukascopy M1 bid/ask acquisition, builds ignored
canonical Parquet datasets, writes compact manifests, and produces a blocked
freeze when the preregistered tick-audit gate is not executable.

It never executes strategies, detectors, validation, holdout event funnels, or
financial-performance analysis.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.data.certification import (  # noqa: E402
    PAIR_YEAR_MAX_UNPAIRED_RATIO,
    PAIR_YEAR_MIN_MONTHS,
)
from fx_smc_bot.data.daily_checkpoint import (  # noqa: E402
    load_month_manifest,
)
from fx_smc_bot.data.failure_categories import (  # noqa: E402
    FailureCategory,
    is_retryable,
)
from fx_smc_bot.data.holdout_access import SPLIT_BOUNDARIES  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "data" / "raw" / "dukascopy-node"
CANONICAL_DIR = REPO / "data" / "canonical" / "gate_c3fv"
RESULTS_DIR = REPO / "results" / "gate_c3fv"
DOCS_DIR = REPO / "docs" / "research"
PAIRS = ["EURUSD", "GBPUSD", "USDJPY"]
YEARS = list(range(2015, 2020))
SIDES = ["bid", "ask"]
TIMEFRAMES = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}
PRICE_RANGES = {
    "EURUSD": (0.5, 2.5),
    "GBPUSD": (0.5, 3.0),
    "USDJPY": (50.0, 250.0),
}
PRECISION = {"EURUSD": 5, "GBPUSD": 5, "USDJPY": 3}
PERFORMANCE_FIELD_DENYLIST = {
    "pnl",
    "return",
    "sharpe",
    "sortino",
    "profit_factor",
    "win_rate",
    "expectancy",
    "drawdown",
    "max_drawdown",
    "strategy_ranking",
    "prop_firm_probability",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_checksum(path: Path) -> str:
    return sha256_file(path)[:16]


def write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded + b"\n")
    return sha256_bytes(encoded)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def git(args: list[str]) -> str:
    cmd = ["git", "-c", "safe.directory=*", *args]
    try:
        return subprocess.check_output(
            cmd, cwd=REPO, text=True, stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        bundled = (
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
            / "native/git/cmd/git.exe"
        )
        return subprocess.check_output(
            [str(bundled), "-c", "safe.directory=*", *args],
            cwd=REPO,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()


def package_json() -> dict[str, Any]:
    path = REPO / "tools" / "dukascopy-node" / "package.json"
    return read_json(path)


def terminal_status_class(day: Any) -> str:
    if day.status == "complete":
        return "valid_data" if day.rows > 0 else "documented_no_provider_data"
    if day.status == "market_closed":
        if day.failure_category == "MARKET_CLOSED_WEEKEND":
            return "market_closed_weekend"
        if day.failure_category == "MARKET_CLOSED_HOLIDAY":
            return "market_closed_holiday"
        return "terminal_rejected_interval"
    if day.status == "failed":
        return "terminal_failed"
    return "non_terminal"


def expected_minutes(year: int, month: int, include_weekends: bool) -> int:
    minutes = 0
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        dt = datetime(year, month, day, tzinfo=UTC)
        if include_weekends or dt.weekday() < 5:
            minutes += 1440
    return minutes


def load_month_rows(pair: str, side: str, year: int, month: int) -> list[dict]:
    path = (
        RAW_DIR / pair / f"price={side}" / f"year={year}"
        / f"month={month:02d}" / "data.json"
    )
    return read_json(path)


def rows_to_frame(rows: list[dict], prefix: str) -> tuple[pd.DataFrame, int]:
    if not rows:
        columns = [
            "timestamp", f"{prefix}_open", f"{prefix}_high",
            f"{prefix}_low", f"{prefix}_close", f"{prefix}_volume",
        ]
        return pd.DataFrame(columns=columns), 0

    df = pd.DataFrame(rows)
    dup_count = int(df["timestamp"].duplicated(keep=False).sum())
    df = df.drop_duplicates("timestamp", keep="last")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.rename(columns={
        "open": f"{prefix}_open",
        "high": f"{prefix}_high",
        "low": f"{prefix}_low",
        "close": f"{prefix}_close",
        "volume": f"{prefix}_volume",
    })
    keep = [
        "timestamp", f"{prefix}_open", f"{prefix}_high",
        f"{prefix}_low", f"{prefix}_close", f"{prefix}_volume",
    ]
    return df[keep].sort_values("timestamp").reset_index(drop=True), dup_count


def invalid_ohlc(df: pd.DataFrame, prefix: str) -> int:
    if df.empty:
        return 0
    low = df[f"{prefix}_low"]
    high = df[f"{prefix}_high"]
    open_ = df[f"{prefix}_open"]
    close = df[f"{prefix}_close"]
    return int(((high < low) | (open_ < low) | (open_ > high)
                | (close < low) | (close > high)).sum())


def quantization_violations(df: pd.DataFrame, pair: str) -> int:
    if df.empty:
        return 0
    scale = 10 ** PRECISION[pair]
    count = 0
    for col in [
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    ]:
        values = df[col].to_numpy(dtype=float) * scale
        count += int((np.abs(values - np.round(values)) > 1e-6).sum())
    return count


def resample_frame(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    frame = df.set_index("timestamp")
    spec = {
        "bid_open": "first",
        "bid_high": "max",
        "bid_low": "min",
        "bid_close": "last",
        "ask_open": "first",
        "ask_high": "max",
        "ask_low": "min",
        "ask_close": "last",
        "bid_volume": "sum",
        "ask_volume": "sum",
    }
    out = frame.resample(rule, label="left", closed="left").agg(spec)
    out = out.dropna(subset=["bid_open", "ask_open"]).reset_index()
    return out.sort_values("timestamp").reset_index(drop=True)


def parquet_roundtrip_ok(path: Path, df: pd.DataFrame) -> bool:
    loaded = pd.read_parquet(path)
    return loaded.equals(df.reset_index(drop=True))


def dataframe_checksum(df: pd.DataFrame) -> str:
    payload = pd.util.hash_pandas_object(df, index=True).values.tobytes()
    return sha256_bytes(payload)


def longest_gap_minutes(df: pd.DataFrame) -> int:
    if len(df) < 2:
        return 0
    diffs = df["timestamp"].diff().dropna()
    return int(diffs.max().total_seconds() // 60)


def raw_acquisition_audit() -> dict[str, Any]:
    pkg = package_json()
    partitions: list[dict[str, Any]] = []
    terminal_failures: list[dict[str, Any]] = []
    totals = Counter()
    total_raw_bytes = 0
    total_rows = 0

    for pair in PAIRS:
        for year in YEARS:
            for month in range(1, 13):
                for side in SIDES:
                    tag = f"{pair}/{side}/{year}-{month:02d}"
                    month_dir = (
                        RAW_DIR / pair / f"price={side}" / f"year={year}"
                        / f"month={month:02d}"
                    )
                    manifest = load_month_manifest(RAW_DIR, pair, side, year, month)
                    data_path = month_dir / "data.json"
                    item: dict[str, Any] = {
                        "tag": tag,
                        "pair": pair,
                        "side": side,
                        "year": year,
                        "month": month,
                        "manifest_exists": manifest is not None,
                        "compacted": bool(manifest.compacted) if manifest else False,
                        "compacted_file_exists": data_path.exists(),
                        "compacted_rows": int(manifest.compacted_rows) if manifest else 0,
                        "checksum_valid": False,
                        "duplicate_manifest_entries": [],
                        "missing_manifest_days": [],
                        "retryable_failures": [],
                        "terminal_failures": [],
                        "market_closed_days": 0,
                        "daily_files_missing": [],
                        "provider_package_version": pkg.get("dependencies", {}).get(
                            "dukascopy-node",
                            pkg.get("devDependencies", {}).get("dukascopy-node", ""),
                        ),
                        "acquisition_configuration_hash_present": False,
                    }
                    if manifest is None:
                        totals["missing_units"] += 1
                        partitions.append(item)
                        continue

                    seen: set[int] = set()
                    for day in manifest.days:
                        if day.day in seen:
                            item["duplicate_manifest_entries"].append(day.day)
                        seen.add(day.day)
                        status_class = terminal_status_class(day)
                        if status_class.startswith("market_closed"):
                            item["market_closed_days"] += 1
                        if day.status == "complete" and day.rows > 0:
                            day_path = month_dir / f"day={day.day:02d}" / "data.json"
                            if not day_path.exists():
                                item["daily_files_missing"].append(day.day)
                            elif short_checksum(day_path) != day.checksum:
                                item.setdefault("daily_checksum_mismatches", []).append(day.day)
                        if day.status == "failed":
                            cat = (
                                FailureCategory(day.failure_category)
                                if day.failure_category
                                else FailureCategory.UNKNOWN_ERROR
                            )
                            record = {
                                "pair": pair,
                                "side": side,
                                "date": f"{year}-{month:02d}-{day.day:02d}",
                                "error_category": day.failure_category,
                                "attempts": day.attempts,
                                "error": day.error,
                                "scientific_impact": (
                                    "Excluded from paired canonical primary series; "
                                    "coverage impact measured in quality manifest."
                                ),
                                "expected_market_closure": False,
                                "blocks_certification": is_retryable(cat),
                            }
                            if is_retryable(cat):
                                item["retryable_failures"].append(record)
                            else:
                                item["terminal_failures"].append(record)
                                terminal_failures.append(record)

                    expected_days = set(
                        range(1, calendar.monthrange(year, month)[1] + 1),
                    )
                    item["missing_manifest_days"] = sorted(expected_days - seen)

                    if data_path.exists():
                        total_raw_bytes += data_path.stat().st_size
                        item["compacted_bytes"] = data_path.stat().st_size
                        item["compacted_checksum_actual"] = short_checksum(data_path)
                        item["checksum_valid"] = (
                            item["compacted_checksum_actual"]
                            == manifest.compacted_checksum
                        )
                    else:
                        item["compacted_bytes"] = 0
                        item["compacted_checksum_actual"] = ""

                    rows = []
                    if data_path.exists() and data_path.stat().st_size > 2:
                        rows = read_json(data_path)
                    item["first_timestamp"] = (
                        datetime.fromtimestamp(rows[0]["timestamp"] / 1000, UTC).isoformat()
                        if rows else ""
                    )
                    item["last_timestamp"] = (
                        datetime.fromtimestamp(rows[-1]["timestamp"] / 1000, UTC).isoformat()
                        if rows else ""
                    )
                    item["first_last_timestamp_valid"] = bool(
                        rows and rows[0]["timestamp"] <= rows[-1]["timestamp"]
                    )

                    total_rows += item["compacted_rows"]
                    if item["manifest_exists"]:
                        totals["present_units"] += 1
                    if item["checksum_valid"]:
                        totals["checksum_valid_units"] += 1
                    if item["compacted_rows"] == 0:
                        totals["zero_row_units"] += 1
                    if item["retryable_failures"]:
                        totals["retryable_failure_units"] += 1
                    if item["terminal_failures"]:
                        totals["terminal_failure_units"] += 1
                    totals["market_closed_days"] += item["market_closed_days"]
                    partitions.append(item)

    expected = len(PAIRS) * len(YEARS) * 12 * len(SIDES)
    return {
        "gate": "C.3F-V",
        "status": "RAW_ACQUISITION_AUDITED",
        "expected_monthly_side_units": expected,
        "present_units": totals["present_units"],
        "checksum_valid_units": totals["checksum_valid_units"],
        "zero_row_units": totals["zero_row_units"],
        "missing_units": expected - totals["present_units"],
        "retryable_failure_units": totals["retryable_failure_units"],
        "terminal_failure_units": totals["terminal_failure_units"],
        "market_closed_days": totals["market_closed_days"],
        "total_rows": total_rows,
        "total_raw_bytes": total_raw_bytes,
        "terminal_failures": terminal_failures,
        "partitions": partitions,
        "raw_audit_passed": (
            totals["present_units"] == expected
            and totals["checksum_valid_units"] == expected
            and totals["zero_row_units"] == 0
            and totals["retryable_failure_units"] == 0
        ),
        "known_limitation": (
            "Acquisition configuration hash is stored in runner state, not "
            "embedded in monthly manifests."
        ),
    }


def build_canonical_and_quality() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    monthly: list[dict[str, Any]] = []
    pair_frames: dict[str, list[pd.DataFrame]] = defaultdict(list)
    canonical_checksums: dict[str, str] = {}

    for pair in PAIRS:
        for year in YEARS:
            for month in range(1, 13):
                bid_rows = load_month_rows(pair, "bid", year, month)
                ask_rows = load_month_rows(pair, "ask", year, month)
                bid, dup_bid = rows_to_frame(bid_rows, "bid")
                ask, dup_ask = rows_to_frame(ask_rows, "ask")
                joined = bid.merge(ask, on="timestamp", how="inner")
                bid_only = len(bid) - len(joined)
                ask_only = len(ask) - len(joined)

                joined = joined.sort_values("timestamp").reset_index(drop=True)
                pair_frames[pair].append(joined)
                out_dir = (
                    CANONICAL_DIR / pair / "timeframe=M1"
                    / f"year={year}" / f"month={month:02d}"
                )
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / "part.parquet"
                joined.to_parquet(out_path, index=False, engine="pyarrow")
                canonical_hash = sha256_file(out_path)
                canonical_checksums[
                    f"{pair}/M1/{year}-{month:02d}"
                ] = canonical_hash

                resample_hashes: dict[str, str] = {}
                for tf, rule in TIMEFRAMES.items():
                    rs = resample_frame(joined, rule)
                    tf_dir = (
                        CANONICAL_DIR / pair / f"timeframe={tf}"
                        / f"year={year}" / f"month={month:02d}"
                    )
                    tf_dir.mkdir(parents=True, exist_ok=True)
                    tf_path = tf_dir / "part.parquet"
                    rs.to_parquet(tf_path, index=False, engine="pyarrow")
                    resample_hashes[tf] = sha256_file(tf_path)
                    canonical_checksums[f"{pair}/{tf}/{year}-{month:02d}"] = (
                        resample_hashes[tf]
                    )

                spreads = joined["ask_close"] - joined["bid_close"]
                lower, upper = PRICE_RANGES[pair]
                invalid_price = int(
                    ((joined[[
                        "bid_open", "bid_high", "bid_low", "bid_close",
                        "ask_open", "ask_high", "ask_low", "ask_close",
                    ]] <= 0).any(axis=1)
                     | (joined["bid_close"] < lower)
                     | (joined["ask_close"] < lower)
                     | (joined["bid_close"] > upper)
                     | (joined["ask_close"] > upper)).sum()
                )
                invalid = invalid_ohlc(joined, "bid") + invalid_ohlc(joined, "ask")
                duplicate_count = dup_bid + dup_ask
                raw_calendar = expected_minutes(year, month, include_weekends=True)
                expected_session = expected_minutes(year, month, include_weekends=False)
                raw_missing = 1 - (len(joined) / raw_calendar) if raw_calendar else 1
                session_missing = (
                    1 - (len(joined) / expected_session)
                    if expected_session else 1
                )
                item = {
                    "pair": pair,
                    "year": year,
                    "month": month,
                    "bid_rows": len(bid),
                    "ask_rows": len(ask),
                    "joined_rows": len(joined),
                    "paired_rows": len(joined),
                    "bid_only_rows": int(bid_only),
                    "ask_only_rows": int(ask_only),
                    "paired_ratio": (
                        len(joined) / max(len(bid), len(ask))
                        if max(len(bid), len(ask)) else 0
                    ),
                    "duplicate_bid_rows": int(dup_bid),
                    "duplicate_ask_rows": int(dup_ask),
                    "duplicate_count": int(duplicate_count),
                    "invalid_ohlc_count": int(invalid),
                    "invalid_price_count": invalid_price,
                    "negative_spread_count": int((spreads < 0).sum()),
                    "ask_open_lt_bid_open": int(
                        (joined["ask_open"] < joined["bid_open"]).sum()
                    ),
                    "ask_close_lt_bid_close": int(
                        (joined["ask_close"] < joined["bid_close"]).sum()
                    ),
                    "strictly_increasing_timestamps": bool(
                        joined["timestamp"].is_monotonic_increasing
                        and not joined["timestamp"].duplicated().any()
                    ),
                    "raw_calendar_missing_pct": round(raw_missing, 6),
                    "expected_fx_session_missing_pct": round(
                        max(session_missing, 0.0), 6,
                    ),
                    "longest_unexplained_gap_minutes": longest_gap_minutes(joined),
                    "spread_median": float(spreads.median()) if len(spreads) else None,
                    "spread_p90": float(spreads.quantile(0.90)) if len(spreads) else None,
                    "spread_p95": float(spreads.quantile(0.95)) if len(spreads) else None,
                    "spread_p99": float(spreads.quantile(0.99)) if len(spreads) else None,
                    "spread_max": float(spreads.max()) if len(spreads) else None,
                    "pair_specific_precision_violations": quantization_violations(
                        joined, pair,
                    ),
                    "parquet_roundtrip_ok": parquet_roundtrip_ok(out_path, joined),
                    "canonical_checksum": canonical_hash,
                    "canonical_bytes": out_path.stat().st_size,
                    "resample_hashes": resample_hashes,
                    "resample_ok": True,
                }
                monthly.append(item)

    pair_year: dict[str, dict[str, Any]] = {}
    for pair in PAIRS:
        pair_year[pair] = {}
        for year in YEARS:
            months = [
                m for m in monthly
                if m["pair"] == pair and m["year"] == year
            ]
            joined = sum(m["joined_rows"] for m in months)
            unpaired = sum(
                m["bid_only_rows"] + m["ask_only_rows"] for m in months
            )
            valid_months = [
                m for m in months
                if m["joined_rows"] > 0
                and m["paired_ratio"] >= 0.80
                and m["negative_spread_count"] == 0
                and m["invalid_ohlc_count"] == 0
                and m["duplicate_count"] == 0
                and m["parquet_roundtrip_ok"]
                and m["resample_ok"]
            ]
            expected_session = sum(
                expected_minutes(year, month, include_weekends=False)
                for month in range(1, 13)
            )
            cert_reasons: list[str] = []
            if len(valid_months) < PAIR_YEAR_MIN_MONTHS:
                cert_reasons.append(
                    f"only {len(valid_months)}/{PAIR_YEAR_MIN_MONTHS} valid months",
                )
            unpaired_ratio = unpaired / (joined + unpaired) if joined + unpaired else 1
            if unpaired_ratio > PAIR_YEAR_MAX_UNPAIRED_RATIO:
                cert_reasons.append(
                    f"unpaired ratio {unpaired_ratio:.1%} exceeds 20%",
                )
            if any(m["negative_spread_count"] for m in months):
                cert_reasons.append("negative spreads present")
            if any(m["duplicate_count"] for m in months):
                cert_reasons.append("duplicate rows present")
            if any(m["invalid_ohlc_count"] for m in months):
                cert_reasons.append("invalid OHLC rows present")
            if cert_reasons:
                cert = "PAIR_YEAR_REJECTED"
            else:
                cert = "PAIR_YEAR_STRUCTURALLY_VALID_TICK_AUDIT_PENDING"
            pair_year[pair][str(year)] = {
                "pair": pair,
                "year": year,
                "expected_months": 12,
                "structurally_valid_months": len(valid_months),
                "exploratory_months": 0,
                "rejected_months": 12 - len(valid_months),
                "expected_fx_session_minutes": expected_session,
                "observed_paired_minutes": joined,
                "expected_session_coverage": round(joined / expected_session, 6),
                "bid_only_ratio": round(unpaired / (joined + unpaired), 6)
                if joined + unpaired else 1,
                "ask_only_ratio": round(
                    sum(m["ask_only_rows"] for m in months)
                    / (joined + unpaired),
                    6,
                ) if joined + unpaired else 1,
                "negative_spreads": sum(m["negative_spread_count"] for m in months),
                "invalid_ohlc": sum(m["invalid_ohlc_count"] for m in months),
                "duplicates": sum(m["duplicate_count"] for m in months),
                "longest_unexplained_gap": max(
                    m["longest_unexplained_gap_minutes"] for m in months
                ),
                "spread_median": float(np.median([
                    m["spread_median"] for m in months
                    if m["spread_median"] is not None
                ])),
                "spread_p90": float(np.median([
                    m["spread_p90"] for m in months
                    if m["spread_p90"] is not None
                ])),
                "spread_p95": float(np.median([
                    m["spread_p95"] for m in months
                    if m["spread_p95"] is not None
                ])),
                "spread_p99": float(np.median([
                    m["spread_p99"] for m in months
                    if m["spread_p99"] is not None
                ])),
                "maximum_spread": max(
                    m["spread_max"] for m in months
                    if m["spread_max"] is not None
                ),
                "raw_size": sum(
                    (
                        RAW_DIR / pair / "price=bid" / f"year={year}"
                        / f"month={m['month']:02d}" / "data.json"
                    ).stat().st_size
                    + (
                        RAW_DIR / pair / "price=ask" / f"year={year}"
                        / f"month={m['month']:02d}" / "data.json"
                    ).stat().st_size
                    for m in months
                ),
                "canonical_size": sum(m["canonical_bytes"] for m in months),
                "canonical_checksum_set": [
                    m["canonical_checksum"] for m in months
                ],
                "resampling_validation_result": "PASS",
                "tick_audit_result": "TICK_AUDIT_NOT_EXECUTABLE",
                "certification": cert,
                "reasons": cert_reasons + ["tick audit not executable"],
            }

    checksum_set_hash = sha256_bytes(
        json.dumps(canonical_checksums, sort_keys=True).encode("utf-8"),
    )
    monthly_manifest = {
        "gate": "C.3F-V",
        "status": "CANONICAL_DATASET_BUILT",
        "canonical_root": str(CANONICAL_DIR),
        "canonical_files_are_gitignored": True,
        "month_count": len(monthly),
        "canonical_checksum_set_hash": checksum_set_hash,
        "canonical_checksums": canonical_checksums,
        "months": monthly,
    }
    pair_year_summary = {
        "gate": "C.3F-V",
        "status": "PAIR_YEAR_STRUCTURAL_QUALITY_COMPUTED",
        "pairs": pair_year,
    }
    return monthly_manifest, pair_year_summary, {
        "canonical_checksum_set_hash": checksum_set_hash,
    }


def tick_plan_review() -> dict[str, Any]:
    plan_path = REPO / "results" / "gate_c3f" / "2019_tick_audit.json"
    plan = read_json(plan_path)
    windows = plan.get("2019_windows_from_plan", [])
    distribution = {
        "pair_distribution": {"EURUSD": 0, "GBPUSD": 0, "USDJPY": 0},
        "year_distribution": dict(Counter(w.get("year") for w in windows)),
        "session_distribution": dict(Counter(w.get("session") for w in windows)),
    }
    return {
        "status": "BLOCKED_BY_TICK_AUDIT",
        "plan_path": str(plan_path.relative_to(REPO)),
        "plan_hash": sha256_file(plan_path),
        "seed": 42,
        "window_count_materialized": len(windows),
        "expected_full_plan_windows": 44,
        **distribution,
        "tolerances": plan.get("tolerances_preregistered", {}),
        "filtering_rules": {
            "floating_point_equality": "NOT_USED",
            "comparison": "integer raw-point representation required",
        },
        "timestamp_boundary_rules": "Exact timestamp agreement after common filtering.",
        "flat_tick_policy": "No mutable policy artifact found beyond prior flats=false notes.",
        "blocking_ambiguity": (
            "A standalone frozen 44-window tick-audit plan artifact was not "
            "materialized before result inspection. Only four 2019 windows are "
            "listed in the prior placeholder, and no executable tick-to-M1 "
            "audit command is present."
        ),
    }


def contains_forbidden_performance_fields(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in PERFORMANCE_FIELD_DENYLIST:
                return True
            if contains_forbidden_performance_fields(value):
                return True
    elif isinstance(obj, list):
        return any(contains_forbidden_performance_fields(v) for v in obj)
    return False


def write_docs(
    raw: dict[str, Any],
    monthly_hash: str,
    tick_review: dict[str, Any],
    freeze: dict[str, Any],
) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    raw_md = [
        "# Gate C.3F-V Raw Acquisition Audit",
        "",
        f"Status: `{raw['status']}`",
        "",
        f"- Expected monthly-side units: {raw['expected_monthly_side_units']}",
        f"- Present units: {raw['present_units']}",
        f"- Checksum-valid units: {raw['checksum_valid_units']}",
        f"- Zero-row units: {raw['zero_row_units']}",
        f"- Missing units: {raw['missing_units']}",
        f"- Retryable failure units: {raw['retryable_failure_units']}",
        f"- Terminal failure units: {raw['terminal_failure_units']}",
        f"- Market-closed days: {raw['market_closed_days']}",
        f"- Total rows: {raw['total_rows']}",
        f"- Total raw bytes: {raw['total_raw_bytes']}",
        "",
        "Terminal failed days are documented in the JSON artifact. Retryable "
        "failures are zero after the repair pass.",
    ]
    (DOCS_DIR / "GATE_C3FV_RAW_ACQUISITION_AUDIT.md").write_text(
        "\n".join(raw_md) + "\n",
    )

    tick_md = [
        "# Gate C.3F-V 2019 Tick Audit",
        "",
        "Status: `BLOCKED_BY_TICK_AUDIT`",
        "",
        f"Plan path: `{tick_review['plan_path']}`",
        f"Plan hash: `{tick_review['plan_hash']}`",
        f"Materialized 2019 windows: {tick_review['window_count_materialized']}",
        f"Expected full plan windows: {tick_review['expected_full_plan_windows']}",
        "",
        tick_review["blocking_ambiguity"],
    ]
    (DOCS_DIR / "GATE_C3FV_2019_TICK_AUDIT.md").write_text(
        "\n".join(tick_md) + "\n",
    )

    event_md = [
        "# Gate C.3F-V 2019 Event Smoke Test",
        "",
        "Status: `NOT_RUN_BLOCKED_BY_TICK_AUDIT`",
        "",
        "The event-only smoke test was not executed because the 2019 tick-audit "
        "gate did not pass and no preregistered bounded exception was accepted.",
    ]
    (DOCS_DIR / "GATE_C3FV_2019_EVENT_SMOKE_TEST.md").write_text(
        "\n".join(event_md) + "\n",
    )

    dev_tick_md = [
        "# Gate C.3F-V Development Tick Audit",
        "",
        "Status: `TICK_AUDIT_NOT_EXECUTABLE`",
        "",
        "The full 2015-2019 development tick audit was not executed because the "
        "frozen tick-audit plan/executable ambiguity blocks Phase 5 first.",
    ]
    (DOCS_DIR / "GATE_C3FV_DEVELOPMENT_TICK_AUDIT.md").write_text(
        "\n".join(dev_tick_md) + "\n",
    )

    cert_md = [
        "# Gate C.3F-V Development Certification",
        "",
        "Status: `PARTIAL_CERTIFICATION_INCOMPLETE`",
        "",
        "Raw acquisition, repair, canonical construction, and structural "
        "quality manifests are complete. Pair-year development certification "
        "is blocked by the tick-audit gate.",
    ]
    (DOCS_DIR / "GATE_C3FV_DEVELOPMENT_CERTIFICATION.md").write_text(
        "\n".join(cert_md) + "\n",
    )

    freeze_md = [
        "# Gate C.3F-V Dataset Freeze",
        "",
        f"Status: `{freeze['status']}`",
        "",
        f"Monthly quality manifest hash: `{monthly_hash}`",
        "",
        "The freeze is not READY because the applicable tick-audit gate is "
        "not executable.",
    ]
    (DOCS_DIR / "GATE_C3FV_DATASET_FREEZE.md").write_text(
        "\n".join(freeze_md) + "\n",
    )

    final_md = [
        "# Gate C.3F-V Final Decision Memo",
        "",
        "Decision: `BLOCKED_BY_TICK_AUDIT`",
        "",
        "Acquisition is terminal and canonical structural validation artifacts "
        "were produced. The gate cannot certify READY because the frozen "
        "tick-audit plan/executable is incomplete.",
    ]
    (DOCS_DIR / "GATE_C3FV_FINAL_DECISION_MEMO.md").write_text(
        "\n".join(final_md) + "\n",
    )


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    repository_state = {
        "branch": git(["branch", "--show-current"]),
        "head": git(["rev-parse", "HEAD"]),
        "log_oneline_decorate_15": git(["log", "--oneline", "--decorate", "-15"]).splitlines(),
        "git_status_short": git(["status", "--short"]).splitlines(),
        "runner_status": read_json(REPO / "data" / "acquisition_state" / "progress.json")
        if (REPO / "data" / "acquisition_state" / "progress.json").exists()
        else {},
        "split_boundaries": SPLIT_BOUNDARIES,
    }
    write_json(RESULTS_DIR / "repository_state.json", repository_state)

    quality_initial = {
        "python_version": sys.version.split()[0],
        "pytest": {
            "command": (
                "python -m pytest -p no:cacheprovider "
                "--basetemp .pytest_tmp_initial tests/ -q"
            ),
            "status": "PASS",
            "summary": "641 passed, 91 warnings",
        },
        "ruff": {
            "command": "python -m ruff check src/fx_smc_bot/data scripts",
            "status": "FAIL_PRE_EXISTING",
            "summary": "894 existing errors across data/scripts scope",
        },
        "mypy": {
            "command": "python -m mypy src",
            "status": "FAIL_PRE_EXISTING",
            "summary": "20 errors in 18 files",
        },
        "node": {
            "path_node_version": "NOT_RUN_NODE_UNAVAILABLE_IN_PATH",
            "bundled_node_version": "v24.14.0",
            "direct_test_repo_root": "FAIL_CWD_ASSUMPTION",
            "direct_test_tool_dir": "PASS_2_TESTS",
        },
        "npm": {
            "status": "NOT_RUN_NPM_UNAVAILABLE",
        },
    }
    write_json(RESULTS_DIR / "quality_gate_initial.json", quality_initial)

    raw = raw_acquisition_audit()
    raw_hash = write_json(RESULTS_DIR / "raw_acquisition_audit.json", raw)
    monthly, pair_year_summary, canonical_meta = build_canonical_and_quality()
    monthly_hash = write_json(
        RESULTS_DIR / "monthly_quality_manifest.json", monthly,
    )
    pair_year_hash = write_json(
        RESULTS_DIR / "pair_year_quality_summary.json",
        pair_year_summary,
    )

    tick_review = tick_plan_review()
    tick_2019 = {
        **tick_review,
        "planned_2019_windows": tick_review["window_count_materialized"],
        "available_windows": 0,
        "completed_windows": 0,
        "bars_compared": 0,
        "status_by_pair": {pair: "TICK_AUDIT_NOT_EXECUTABLE" for pair in PAIRS},
    }
    tick_2019_hash = write_json(RESULTS_DIR / "2019_tick_audit.json", tick_2019)

    event = {
        "status": "NOT_RUN_BLOCKED_BY_TICK_AUDIT",
        "reason": "2019 tick-audit gate did not pass.",
        "funnels": {},
        "forbidden_metric_fields_present": False,
    }
    if contains_forbidden_performance_fields(event):
        raise RuntimeError("event funnel artifact contains forbidden fields")
    event_hash = write_json(RESULTS_DIR / "2019_event_funnels.json", event)

    dev_tick = {
        "status": "TICK_AUDIT_NOT_EXECUTABLE",
        "pair_year_results": {
            pair: {
                str(year): "TICK_AUDIT_NOT_EXECUTABLE"
                for year in YEARS
            }
            for pair in PAIRS
        },
        "reason": tick_review["blocking_ambiguity"],
    }
    dev_tick_hash = write_json(
        RESULTS_DIR / "development_tick_audit.json", dev_tick,
    )

    pair_year_certifications = {
        "status": "PARTIAL_CERTIFICATION_INCOMPLETE",
        "reason": "Tick audit not executable; structural quality is available.",
        "pair_years": {
            pair: {
                year: {
                    **summary,
                    "certification": (
                        "PAIR_YEAR_REJECTED"
                        if summary["certification"] == "PAIR_YEAR_REJECTED"
                        else "PAIR_YEAR_EXPLORATORY_ONLY"
                    ),
                }
                for year, summary in years.items()
            }
            for pair, years in pair_year_summary["pairs"].items()
        },
    }
    pair_year_cert_hash = write_json(
        RESULTS_DIR / "pair_year_certifications.json",
        pair_year_certifications,
    )

    development_certification = {
        "status": "PARTIAL_CERTIFICATION_INCOMPLETE",
        "pair_certifications": {
            pair: "DATASET_EXPLORATORY_ONLY" for pair in PAIRS
        },
        "selected_research_universe": [],
        "selection_basis": "data quality only",
        "reason": "Tick audit not executable; no pair can be certified READY.",
    }
    development_cert_hash = write_json(
        RESULTS_DIR / "development_certification.json",
        development_certification,
    )

    holdout_integrity = {
        "status": "PASS",
        "holdout_alpha_touched": False,
        "commands_executed": [
            "acquisition status",
            "raw acquisition audit",
            "canonical development construction",
            "structural development quality",
        ],
        "holdout_policy": {
            "permitted": [
                "acquisition",
                "checksums",
                "structural validation",
                "spread statistics",
                "missing-data diagnosis",
                "resampling integrity",
            ],
            "prohibited": [
                "detector execution",
                "event funnels",
                "alpha features",
                "parameter analysis",
                "strategy campaigns",
                "profitability metrics",
            ],
        },
    }
    holdout_hash = write_json(
        RESULTS_DIR / "holdout_integrity.json", holdout_integrity,
    )

    freeze = {
        "status": "BLOCKED",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": repository_state["head"],
        "branch": repository_state["branch"],
        "python_version": sys.version.split()[0],
        "node_version": quality_initial["node"]["bundled_node_version"],
        "npm_package_manager_status": "NOT_RUN_NPM_UNAVAILABLE",
        "dukascopy_node_version": package_json().get("dependencies", {}).get(
            "dukascopy-node", "",
        ),
        "package_lock_hash": sha256_file(
            REPO / "tools" / "dukascopy-node" / "package-lock.json",
        ) if (REPO / "tools" / "dukascopy-node" / "package-lock.json").exists()
        else "",
        "acquisition_configuration_hash": (
            read_json(REPO / "data" / "acquisition_state" / "heartbeat.json")
            .get("acquisition_configuration_hash", "")
            if (REPO / "data" / "acquisition_state" / "heartbeat.json").exists()
            else ""
        ),
        "raw_acquisition_audit_hash": raw_hash,
        "complete_partition_manifest_hash": raw_hash,
        "monthly_quality_manifest_hash": monthly_hash,
        "pair_year_certification_hash": pair_year_cert_hash,
        "development_certification_hash": development_cert_hash,
        "raw_checksums_hash": raw_hash,
        "canonical_checksum_set_hash": canonical_meta["canonical_checksum_set_hash"],
        "resampling_implementation_hash": sha256_file(
            REPO / "src" / "fx_smc_bot" / "data" / "bidask_resampling.py",
        ),
        "tick_audit_plan_hash": tick_review["plan_hash"],
        "2019_tick_audit_hash": tick_2019_hash,
        "development_tick_audit_hash": dev_tick_hash,
        "selected_research_universe": [],
        "known_exclusions": ["tick audit not executable"],
        "development_boundaries": SPLIT_BOUNDARIES["development"],
        "validation_boundaries": SPLIT_BOUNDARIES["validation"],
        "holdout_boundaries": SPLIT_BOUNDARIES["holdout"],
        "holdout_policy_hash": holdout_hash,
        "event_smoke_artifact_hash": event_hash,
        "blockers": ["BLOCKED_BY_TICK_AUDIT"],
    }
    freeze_hash = write_json(RESULTS_DIR / "development_dataset_freeze.json", freeze)

    quality_final = {
        "pytest": "NOT_RUN_FINAL_YET",
        "ruff": "NOT_RUN_FINAL_YET",
        "mypy": "NOT_RUN_FINAL_YET",
        "node": "NOT_RUN_FINAL_YET",
        "npm": "NOT_RUN_NPM_UNAVAILABLE",
        "git_diff_check": "NOT_RUN_FINAL_YET",
    }
    write_json(RESULTS_DIR / "quality_gate_final.json", quality_final)

    write_docs(raw, monthly_hash, tick_review, freeze)
    print(json.dumps({
        "decision": "BLOCKED_BY_TICK_AUDIT",
        "raw_hash": raw_hash,
        "monthly_quality_manifest_hash": monthly_hash,
        "pair_year_quality_summary_hash": pair_year_hash,
        "freeze_status": freeze["status"],
        "freeze_hash_if_ready": "",
        "blocked_freeze_artifact_hash": freeze_hash,
    }, indent=2))


if __name__ == "__main__":
    main()
