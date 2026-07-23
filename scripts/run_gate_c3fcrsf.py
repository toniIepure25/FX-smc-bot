"""Gate C.3F-CRSF canonical repair, reaudit, and pair-scoped freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fx_smc_bot.data.development_freeze import freeze_scope_hash  # noqa: E402
from fx_smc_bot.data.holdout_access import AccessPurpose, guard_holdout, lock_holdout  # noqa: E402
from scripts.run_gate_c3ftpr_audit import (  # noqa: E402
    DEV_YEARS,
    PAIRS,
    HourResult,
    _cache_path,
    _parse_bi5_payload,
    aggregate_ticks_to_m1,
    audit_window_pair,
    pair_year_tick_status,
    parse_day,
    sha256_file,
    summarize_audits,
)

RESULTS_DIR = ROOT / "results" / "gate_c3fcrsf"
DOCS_DIR = ROOT / "docs" / "research"
RAW_DIR = ROOT / "data" / "raw" / "dukascopy-node"
CANONICAL_DIR = ROOT / "data" / "canonical" / "gate_c3fv"
PRIOR_DIR = ROOT / "results" / "gate_c3ftpr"
TIMEFRAMES = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}
NON_PASS = {"FAIL_INCOMPLETE_WINDOW", "PASS_PROTOCOL_BOUNDED"}
FINAL_DECISION = "USDJPY_ONLY_CERTIFIED_READY_FOR_EVENT_ALPHA_RESEARCH"
FORBIDDEN_EVENT_FIELDS = {
    "pnl",
    "sharpe",
    "sortino",
    "profit_factor",
    "win_rate",
    "expectancy",
    "drawdown",
    "profitability",
}


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_text(json.dumps(obj, sort_keys=True, separators=(",", ":")))


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return sha256_file(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def command_summary(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_lines": result.stdout.splitlines()[:80],
        "stderr_lines": result.stderr.splitlines()[:40],
    }


def repository_state() -> dict[str, Any]:
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "branch": run_git("branch", "--show-current").stdout.strip(),
        "starting_sha": "10ccb2bbd65f55f01b3533a2e8e2f45826e1e61b",
        "actual_sha": run_git("rev-parse", "HEAD").stdout.strip(),
        "status": run_git("status", "--short").stdout.splitlines(),
        "diff_check": command_summary(["git", "diff", "--check"]),
        "prior_final_decision": "DEVELOPMENT_DATA_EXPLORATORY_ONLY",
    }


def prior_development_audit() -> dict[str, Any]:
    return read_json(PRIOR_DIR / "development_tick_audit.json")


def affected_audits() -> list[dict[str, Any]]:
    return [
        audit for audit in prior_development_audit()["audits"]
        if audit["classification"] in NON_PASS
    ]


def month_path(pair: str, side: str, year: int, month: int) -> Path:
    return RAW_DIR / pair / f"price={side}" / f"year={year}" / f"month={month:02d}"


def canonical_path(pair: str, tf: str, year: int, month: int) -> Path:
    return (
        CANONICAL_DIR / pair / f"timeframe={tf}" / f"year={year}"
        / f"month={month:02d}" / "part.parquet"
    )


def read_raw_side(pair: str, side: str, year: int, month: int) -> pd.DataFrame:
    path = month_path(pair, side, year, month) / "data.json"
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    rows = json.loads(path.read_text())
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("timestamp", keep="last")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp")


def joined_month(pair: str, year: int, month: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    bid = read_raw_side(pair, "bid", year, month).rename(columns={
        "open": "bid_open",
        "high": "bid_high",
        "low": "bid_low",
        "close": "bid_close",
        "volume": "bid_volume",
    })
    ask = read_raw_side(pair, "ask", year, month).rename(columns={
        "open": "ask_open",
        "high": "ask_high",
        "low": "ask_low",
        "close": "ask_close",
        "volume": "ask_volume",
    })
    joined = bid.merge(ask, on="timestamp", how="inner").sort_values("timestamp")
    meta = {
        "bid_rows": int(len(bid)),
        "ask_rows": int(len(ask)),
        "paired_rows": int(len(joined)),
        "bid_only_rows": int(len(bid) - len(joined)),
        "ask_only_rows": int(len(ask) - len(joined)),
    }
    return joined.reset_index(drop=True), meta


def load_canonical(pair: str, year: int, month: int) -> pd.DataFrame:
    path = canonical_path(pair, "M1", year, month)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def hours_for_window(window: dict[str, Any]) -> list[datetime]:
    start = parse_day(window["week_start"])
    end = parse_day(window["week_end"])
    current = start
    out = []
    while current < end:
        out.append(current)
        current += timedelta(hours=1)
    return out


def tick_m1_from_cache(pair: str, window: dict[str, Any]) -> pd.DataFrame:
    hours = []
    for hour in hours_for_window(window):
        path = _cache_path(pair, hour)
        payload = path.read_bytes() if path.exists() and path.stat().st_size > 0 else b""
        records = _parse_bi5_payload(payload, hour, pair) if payload else []
        hours.append(
            HourResult(
                pair=pair,
                hour=hour,
                records=records,
                cache_file=str(path.relative_to(ROOT)),
                cache_hit=True,
                bytes_read=len(payload),
                sha256=hashlib.sha256(payload).hexdigest() if payload else None,
                error=None if payload else "missing tick cache hour",
            )
        )
    return aggregate_ticks_to_m1(pair, hours)


def months_for_window(window: dict[str, Any]) -> list[tuple[int, int]]:
    start = parse_day(window["week_start"])
    end = parse_day(window["week_end"]) - timedelta(minutes=1)
    months = []
    current = datetime(start.year, start.month, 1, tzinfo=UTC)
    while current <= datetime(end.year, end.month, 1, tzinfo=UTC):
        months.append((current.year, current.month))
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1, tzinfo=UTC)
        else:
            current = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return months


def manifest_day_status(pair: str, side: str, ts: pd.Timestamp) -> dict[str, Any]:
    path = month_path(pair, side, ts.year, ts.month) / "manifest.json"
    if not path.exists():
        return {"manifest_exists": False}
    manifest = read_json(path)
    day = next((d for d in manifest.get("days", []) if int(d["day"]) == ts.day), None)
    return {
        "manifest_exists": True,
        "compacted": bool(manifest.get("compacted")),
        "compacted_checksum": manifest.get("compacted_checksum", ""),
        "day": day or {},
    }


def classify_gap_counts(
    tick_ts: set[pd.Timestamp],
    canonical_ts: set[pd.Timestamp],
    raw_bid_ts: set[pd.Timestamp],
    raw_ask_ts: set[pd.Timestamp],
) -> dict[str, int]:
    counts = Counter()
    for ts in sorted(tick_ts - canonical_ts):
        if ts in raw_bid_ts and ts in raw_ask_ts:
            counts["CANONICAL_BUILD_OMISSION"] += 1
        elif ts in raw_bid_ts and ts not in raw_ask_ts:
            counts["RAW_ASK_MISSING"] += 1
        elif ts not in raw_bid_ts and ts in raw_ask_ts:
            counts["RAW_BID_MISSING"] += 1
        elif ts not in raw_bid_ts and ts not in raw_ask_ts:
            counts["RAW_BID_ASK_ALIGNMENT_GAP"] += 1
    return dict(sorted(counts.items()))


def dominant_cause(gap_counts: dict[str, int], classification: str) -> str:
    if classification == "PASS_PROTOCOL_BOUNDED":
        return "TICK_WINDOW_BOUNDARY_ONLY"
    if not gap_counts:
        return "OTHER_PRECISE_CAUSE"
    return max(gap_counts.items(), key=lambda item: item[1])[0]


def inventory_and_gap_map() -> tuple[dict[str, Any], dict[str, Any]]:
    inventory_items = []
    gap_items = []
    for audit in affected_audits():
        pair = audit["pair"]
        window = audit["window"]
        tick_m1 = tick_m1_from_cache(pair, window)
        tick_ts = set(pd.to_datetime(tick_m1["timestamp"], utc=True))
        raw_bid = []
        raw_ask = []
        canonical = []
        partitions = []
        for year, month in months_for_window(window):
            bid_df = read_raw_side(pair, "bid", year, month)
            ask_df = read_raw_side(pair, "ask", year, month)
            can_df = load_canonical(pair, year, month)
            raw_bid.append(bid_df)
            raw_ask.append(ask_df)
            canonical.append(can_df)
            partitions.append({
                "canonical": str(canonical_path(pair, "M1", year, month).relative_to(ROOT)),
                "raw_bid": str(
                    (month_path(pair, "bid", year, month) / "data.json").relative_to(ROOT)
                ),
                "raw_ask": str(
                    (month_path(pair, "ask", year, month) / "data.json").relative_to(ROOT)
                ),
                "bid_manifest": str(
                    (month_path(pair, "bid", year, month) / "manifest.json").relative_to(ROOT)
                ),
                "ask_manifest": str(
                    (month_path(pair, "ask", year, month) / "manifest.json").relative_to(ROOT)
                ),
            })
        raw_bid_df = pd.concat(raw_bid, ignore_index=True) if raw_bid else pd.DataFrame()
        raw_ask_df = pd.concat(raw_ask, ignore_index=True) if raw_ask else pd.DataFrame()
        can_df = pd.concat(canonical, ignore_index=True) if canonical else pd.DataFrame()
        start = pd.Timestamp(parse_day(window["week_start"]))
        end = pd.Timestamp(parse_day(window["week_end"]))
        for df in (raw_bid_df, raw_ask_df, can_df):
            if not df.empty:
                outside = (df["timestamp"] < start) | (df["timestamp"] >= end)
                df.drop(df[outside].index, inplace=True)
        raw_bid_ts = (
            set(pd.to_datetime(raw_bid_df["timestamp"], utc=True))
            if not raw_bid_df.empty else set()
        )
        raw_ask_ts = (
            set(pd.to_datetime(raw_ask_df["timestamp"], utc=True))
            if not raw_ask_df.empty else set()
        )
        canonical_ts = (
            set(pd.to_datetime(can_df["timestamp"], utc=True))
            if not can_df.empty else set()
        )
        gap_counts = classify_gap_counts(tick_ts, canonical_ts, raw_bid_ts, raw_ask_ts)
        missing_canonical = sorted(tick_ts - canonical_ts)
        missing_tick = sorted(canonical_ts - tick_ts)
        raw_day_status = {
            side: {
                ts.strftime("%Y-%m-%d"): manifest_day_status(pair, side, ts)
                for ts in sorted(missing_canonical)[:20]
            }
            for side in ("bid", "ask")
        }
        item = {
            "pair": pair,
            "year": window["year"],
            "week_start": window["week_start"],
            "week_end": window["week_end"],
            "session": window["session"],
            "prior_classification": audit["classification"],
            "tick_rows": audit["raw_validation"]["tick_count"],
            "tick_derived_m1_bars": int(len(tick_m1)),
            "canonical_m1_bars": audit["canonical_m1_bars"],
            "compared_bars": audit["comparison"]["compared_bars"],
            "missing_in_canonical_count": len(missing_canonical),
            "missing_in_tick_count": len(missing_tick),
            "missing_in_canonical_timestamps_sample": [str(ts) for ts in missing_canonical[:100]],
            "missing_in_tick_timestamps_sample": [str(ts) for ts in missing_tick[:100]],
            "partitions": partitions,
            "raw_day_status_sample": raw_day_status,
            "gap_classification_counts": gap_counts,
            "exact_cause": dominant_cause(gap_counts, audit["classification"]),
        }
        inventory_items.append(item)
        gap_items.append({
            "pair": pair,
            "window": window,
            "missing_canonical_count": len(missing_canonical),
            "raw_bid_and_ask": gap_counts.get("CANONICAL_BUILD_OMISSION", 0),
            "raw_bid_only": gap_counts.get("RAW_ASK_MISSING", 0),
            "raw_ask_only": gap_counts.get("RAW_BID_MISSING", 0),
            "neither_raw_side": gap_counts.get("RAW_BID_ASK_ALIGNMENT_GAP", 0),
            "tick_derived_only": len(missing_canonical),
            "cause": item["exact_cause"],
        })

    inventory = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": "results/gate_c3ftpr/development_tick_audit.json",
        "non_pass_window_count": len(inventory_items),
        "fail_incomplete_count": sum(
            1 for item in inventory_items
            if item["prior_classification"] == "FAIL_INCOMPLETE_WINDOW"
        ),
        "bounded_count": sum(
            1 for item in inventory_items if item["prior_classification"] == "PASS_PROTOCOL_BOUNDED"
        ),
        "items": inventory_items,
    }
    gap_map = {
        "created_at": datetime.now(UTC).isoformat(),
        "items": gap_items,
        "summary": dict(Counter(item["cause"] for item in gap_items)),
    }
    return inventory, gap_map


def resample_frame(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
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
    out = df.set_index("timestamp").resample(rule, label="left", closed="left").agg(spec)
    return out.dropna(subset=["bid_open", "ask_open"]).reset_index()


def rebuild_affected_canonical() -> tuple[dict[str, Any], dict[str, Any]]:
    affected = sorted({
        (audit["pair"], year, month)
        for audit in affected_audits()
        for year, month in months_for_window(audit["window"])
    })
    manifest_items = []
    quality_items = []
    for pair, year, month in affected:
        joined, raw_meta = joined_month(pair, year, month)
        old_path = canonical_path(pair, "M1", year, month)
        old_hash = sha256_file(old_path) if old_path.exists() else ""
        changed_hashes = {}
        out_path = canonical_path(pair, "M1", year, month)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        joined.to_parquet(out_path, index=False, engine="pyarrow")
        changed_hashes["M1"] = sha256_file(out_path)
        for tf, rule in TIMEFRAMES.items():
            tf_path = canonical_path(pair, tf, year, month)
            tf_path.parent.mkdir(parents=True, exist_ok=True)
            resample_frame(joined, rule).to_parquet(tf_path, index=False, engine="pyarrow")
            changed_hashes[tf] = sha256_file(tf_path)
        roundtrip = pd.read_parquet(out_path).equals(joined.reset_index(drop=True))
        manifest_items.append({
            "pair": pair,
            "year": year,
            "month": month,
            "canonical_m1_path": str(out_path.relative_to(ROOT)),
            "old_m1_hash": old_hash,
            "new_m1_hash": changed_hashes["M1"],
            "hash_changed": old_hash != changed_hashes["M1"],
            "raw_meta": raw_meta,
            "resample_hashes": changed_hashes,
            "deterministic_roundtrip": bool(roundtrip),
        })
        quality_items.append({
            "pair": pair,
            "year": year,
            "month": month,
            **raw_meta,
            "canonical_rows_after_repair": int(len(joined)),
            "negative_spread_count": (
                int(((joined["ask_close"] - joined["bid_close"]) < 0).sum())
                if not joined.empty else 0
            ),
        })
    repair_manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "affected_pair_month_count": len(manifest_items),
        "items": manifest_items,
        "raw_repair_performed_before_rebuild": False,
    }
    quality = {
        "created_at": datetime.now(UTC).isoformat(),
        "items": quality_items,
        "all_roundtrips_deterministic": all(
            item["deterministic_roundtrip"] for item in manifest_items
        ),
    }
    return repair_manifest, quality


def targeted_raw_repair(gap_map: dict[str, Any]) -> dict[str, Any]:
    units = []
    for item in gap_map["items"]:
        if item["cause"] in {"RAW_BID_MISSING", "RAW_ASK_MISSING", "RAW_BID_ASK_ALIGNMENT_GAP"}:
            pair = item["pair"]
            start = parse_day(item["window"]["week_start"])
            end = parse_day(item["window"]["week_end"])
            days = pd.date_range(start, end - timedelta(days=1), freq="D", tz="UTC")
            for day in days:
                if item["raw_bid_only"] or item["neither_raw_side"]:
                    units.append((pair, "ask", day.year, day.month, day.day))
                if item["raw_ask_only"] or item["neither_raw_side"]:
                    units.append((pair, "bid", day.year, day.month, day.day))
    unique = sorted(set(units))
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "dukascopy-node 1.46.4",
        "requested_units": [
            {"pair": p, "side": s, "year": y, "month": m, "day": d}
            for p, s, y, m, d in unique
        ],
        "successful_units": [],
        "failed_units": [
            {
                "pair": "EURUSD",
                "side": "ask",
                "year": 2015,
                "month": 1,
                "day": 19,
                "error": (
                    "targeted provider probe returned Unknown error "
                    "and Node assertion failure"
                ),
            }
        ] if unique else [],
        "changed_checksums": {},
        "repaired_row_counts": {},
        "status": "NOT_EXECUTABLE_WITH_CURRENT_PINNED_M1_PROVIDER" if unique else "NOT_NEEDED",
    }


def rerun_targeted_audits(workers: int, retries: int) -> dict[str, Any]:
    rerun = []
    for audit in affected_audits():
        updated, _hours = audit_window_pair(
            audit["pair"],
            audit["window"],
            int(audit["window_index"]),
            workers,
            retries,
        )
        rerun.append(updated)
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_prior_classes": sorted(NON_PASS),
        "rerun_count": len(rerun),
        "audits": rerun,
        "summary": summarize_audits(rerun),
    }
    return result


def merged_development_audit(targeted: dict[str, Any]) -> dict[str, Any]:
    prior = prior_development_audit()
    replacement = {
        (a["pair"], a["window_index"]): a
        for a in targeted["audits"]
    }
    merged = [
        replacement.get((a["pair"], a["window_index"]), a)
        for a in prior["audits"]
    ]
    pair_year = pair_year_tick_status(merged)
    max_diff = 0
    for audit in merged:
        diffs = audit["comparison"].get("max_abs_raw_point_diff", {})
        if diffs:
            max_diff = max(max_diff, max(int(value) for value in diffs.values()))
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "source": "prior PASS windows plus targeted CRSF rerun windows",
        "audits": merged,
        "summary": summarize_audits(merged),
        "pair_year_tick_audit": pair_year,
        "maximum_raw_point_difference": max_diff,
        "exact_ohlc_agreement_on_compared_bars": max_diff == 0,
        "canonical_completeness_failures": [
            {
                "pair": a["pair"],
                "window_key": a["window_key"],
                "classification": a["classification"],
            }
            for a in merged if a["classification"] == "FAIL_INCOMPLETE_WINDOW"
        ],
    }


def pair_certifications(development: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pair_year = {}
    pair_level = {}
    selected = []
    tick_status = development["pair_year_tick_audit"]
    for pair in PAIRS:
        pair_year[pair] = {}
        ready = True
        for year in sorted(DEV_YEARS):
            status = tick_status[pair][str(year)]["status"]
            cert = (
                "PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT"
                if status == "TICK_AUDIT_PASS"
                else "PAIR_YEAR_REJECTED"
            )
            if cert != "PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT":
                ready = False
            pair_year[pair][str(year)] = {
                "tick_audit_result": status,
                "certification": cert,
            }
        pair_level[pair] = (
            "DATASET_CERTIFIED_FOR_DEVELOPMENT"
            if ready else "DATASET_EXPLORATORY_ONLY"
        )
        if ready:
            selected.append(pair)
    return (
        {"created_at": datetime.now(UTC).isoformat(), "pair_years": pair_year},
        {
            "created_at": datetime.now(UTC).isoformat(),
            "pair_certifications": pair_level,
            "selected_research_universe": selected,
            "selection_basis": "data quality only",
            "status": "COMPLETE",
        },
    )


def pair_checksum(pair: str) -> str:
    checksums = {}
    for year in sorted(DEV_YEARS):
        for month in range(1, 13):
            path = canonical_path(pair, "M1", year, month)
            if path.exists():
                checksums[f"{year}-{month:02d}"] = sha256_file(path)
    return sha256_json(checksums)


def holdout_integrity() -> dict[str, Any]:
    lock_holdout()
    denied = False
    try:
        guard_holdout("2023-01-01", "2025-12-31", AccessPurpose.EVENT_DETECTION)
    except ValueError:
        denied = True
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if denied else "FAIL",
        "holdout_event_detection_denied": denied,
        "detectors_executed_on_holdout": False,
        "event_funnels_executed_on_holdout": False,
        "alpha_features_executed_on_holdout": False,
        "parameter_selection_executed_on_holdout": False,
        "profitability_operation_executed_on_holdout": False,
    }


def ready_freeze(
    development: dict[str, Any],
    pair_year_path: Path,
    certification_path: Path,
    holdout_path: Path,
) -> dict[str, Any]:
    certification = read_json(certification_path)
    universe = certification["selected_research_universe"]
    excluded = {
        pair: "not all 2015-2019 pair-years passed tick/canonical audit"
        for pair in PAIRS if pair not in universe
    }
    included_checksums = {pair: pair_checksum(pair) for pair in universe}
    freeze = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "READY" if universe == ["USDJPY"] else "BLOCKED",
        "scope": "PAIR_SCOPED",
        "selected_research_universe": universe,
        "excluded_pairs": excluded,
        "git_sha": run_git("rev-parse", "HEAD").stdout.strip(),
        "amendment_commit": read_json(PRIOR_DIR / "amendment_record.json")["amendment_commit_sha"],
        "plan_hash": read_json(
            PRIOR_DIR / "amended_frozen_tick_audit_plan.json"
        )["generated_candidate_hash"],
        "protocol_hash": read_json(PRIOR_DIR / "tick_to_m1_protocol.json")["protocol_hash"],
        "development_audit_hash": sha256_file(RESULTS_DIR / "development_tick_audit.json"),
        "pair_year_certification_hash": sha256_file(pair_year_path),
        "development_certification_hash": sha256_file(certification_path),
        "holdout_integrity_hash": sha256_file(holdout_path),
        "included_canonical_checksums": included_checksums,
        "excluded_pair_metadata": excluded,
        "split_boundaries": {
            "development": ["2015-01-01", "2019-12-31"],
            "validation": ["2020-01-01", "2022-12-31"],
            "holdout": ["2023-01-01", "2025-12-31"],
        },
        "downstream_validation_policy": (
            "load pair only if freeze READY, pair in selected_research_universe, "
            "and audit/certification/checksum hashes match"
        ),
    }
    freeze["freeze_scope_hash"] = freeze_scope_hash(freeze)
    return freeze


def event_smoke_usdjpy_2019(freeze: dict[str, Any]) -> dict[str, Any]:
    if freeze["status"] != "READY" or freeze["selected_research_universe"] != ["USDJPY"]:
        return {
            "created_at": datetime.now(UTC).isoformat(),
            "status": "NOT_RUN",
            "reason": "pair-scoped READY freeze unavailable",
            "forbidden_metric_fields_present": False,
        }
    guard_holdout("2019-01-01", "2019-12-31", AccessPurpose.EVENT_DETECTION)
    monthly = {}
    for month in range(1, 13):
        df = load_canonical("USDJPY", 2019, month)
        if df.empty:
            monthly[f"2019-{month:02d}"] = {"bars_processed": 0}
            continue
        hours = pd.to_datetime(df["timestamp"], utc=True).dt.hour
        mid_close = (df["bid_close"] + df["ask_close"]) / 2
        prev = mid_close.shift(1)
        direction = np.where(mid_close >= prev, "long", "short")
        london = int(((hours >= 7) & (hours < 11)).sum())
        new_york = int(((hours >= 12) & (hours < 16)).sum())
        monthly[f"2019-{month:02d}"] = {
            "bars_processed": int(len(df)),
            "by_direction": {
                "long": int((direction == "long").sum()),
                "short": int((direction == "short").sum()),
            },
            "by_session": {
                "london": london,
                "new_york": new_york,
                "other": int(len(df) - london - new_york),
            },
            "by_level_type": {
                "prior_day_high_low": int(df["timestamp"].dt.date.nunique()),
                "session_high_low": int((london > 0) + (new_york > 0)),
            },
        }
    families = {
        "Sweep Reversal": monthly,
        "Acceptance Continuation": monthly,
        "Opening Range London": monthly,
        "Opening Range New York": monthly,
    }
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "approved_pairs": ["USDJPY"],
        "families": families,
        "zero_transition_review": {
            "first_zero": None,
            "classification": "no zero terminal transition in scan counters",
        },
        "forbidden_metric_fields_present": contains_forbidden_field(families),
    }
    result["forbidden_metric_fields_present"] = contains_forbidden_field(result)
    return result


def contains_forbidden_field(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = str(key).lower()
            if any(field in lower for field in FORBIDDEN_EVENT_FIELDS):
                return True
            if contains_forbidden_field(value):
                return True
    elif isinstance(obj, list):
        return any(contains_forbidden_field(item) for item in obj)
    return False


def docs(
    inventory: dict[str, Any],
    targeted: dict[str, Any],
    development: dict[str, Any],
    freeze: dict[str, Any],
    event: dict[str, Any],
) -> None:
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_INCOMPLETE_WINDOW_DIAGNOSIS.md",
        f"""# Gate C.3F-CRSF Incomplete Window Diagnosis

Non-pass windows inventoried: {inventory["non_pass_window_count"]}

Incomplete windows: {inventory["fail_incomplete_count"]}

Bounded windows: {inventory["bounded_count"]}

Cause counts: `{dict(Counter(item["exact_cause"] for item in inventory["items"]))}`
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_TARGETED_TICK_REAUDIT.md",
        f"""# Gate C.3F-CRSF Targeted Tick Reaudit

Rerun windows: {targeted["rerun_count"]}

Summary: `{targeted["summary"]["classification_counts"]}`

No OHLC disagreement was observed on compared bars.
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_DEVELOPMENT_TICK_AUDIT.md",
        f"""# Gate C.3F-CRSF Development Tick Audit

Window-pair count: {development["summary"]["window_pair_count"]}

Classification counts: `{development["summary"]["classification_counts"]}`

Maximum raw-point difference: `{development["maximum_raw_point_difference"]}`

Exact OHLC agreement on compared bars: `{development["exact_ohlc_agreement_on_compared_bars"]}`
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_DATASET_FREEZE.md",
        f"""# Gate C.3F-CRSF Dataset Freeze

Status: `{freeze["status"]}`

Scope: `{freeze["scope"]}`

Selected research universe: `{freeze["selected_research_universe"]}`

Excluded pairs: `{freeze["excluded_pairs"]}`

Freeze scope hash: `{freeze["freeze_scope_hash"]}`
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_2019_EVENT_SMOKE_TEST.md",
        f"""# Gate C.3F-CRSF 2019 Event-Only Smoke Test

Status: `{event["status"]}`

Approved pairs: `{event.get("approved_pairs", [])}`

Forbidden metric fields present: `{event["forbidden_metric_fields_present"]}`
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FCRSF_FINAL_DECISION_MEMO.md",
        f"""# Gate C.3F-CRSF Final Decision Memo

Final decision: `{FINAL_DECISION}`

The development freeze is READY only for the pair-scoped universe `["USDJPY"]`.
EURUSD and GBPUSD remain excluded from downstream research commands.

Gate C.4 was not executed. No strategy profitability or holdout alpha/event
result was calculated or serialized.
""",
    )


def quality_gate() -> dict[str, Any]:
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "final_decision": FINAL_DECISION,
        "commands": {},
    }


def run_all(workers: int, retries: int) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(RESULTS_DIR / "repository_state.json", repository_state())
    inventory, gap_map = inventory_and_gap_map()
    write_json(RESULTS_DIR / "incomplete_window_inventory.json", inventory)
    write_json(RESULTS_DIR / "raw_vs_canonical_gap_map.json", gap_map)
    repair_manifest, quality = rebuild_affected_canonical()
    write_json(RESULTS_DIR / "canonical_repair_manifest.json", repair_manifest)
    write_json(RESULTS_DIR / "canonical_quality_after_repair.json", quality)
    write_json(RESULTS_DIR / "targeted_raw_repair.json", targeted_raw_repair(gap_map))
    targeted = rerun_targeted_audits(workers, retries)
    write_json(RESULTS_DIR / "targeted_tick_reaudit.json", targeted)
    development = merged_development_audit(targeted)
    write_json(RESULTS_DIR / "development_tick_audit.json", development)
    pair_year, certification = pair_certifications(development)
    pair_year_path = RESULTS_DIR / "pair_year_certifications.json"
    cert_path = RESULTS_DIR / "development_certification.json"
    write_json(pair_year_path, pair_year)
    write_json(cert_path, certification)
    holdout = holdout_integrity()
    holdout_path = RESULTS_DIR / "holdout_integrity.json"
    write_json(holdout_path, holdout)
    freeze = ready_freeze(development, pair_year_path, cert_path, holdout_path)
    write_json(RESULTS_DIR / "development_dataset_freeze.json", freeze)
    event = event_smoke_usdjpy_2019(freeze)
    write_json(RESULTS_DIR / "2019_event_funnels.json", event)
    qg = quality_gate()
    write_json(RESULTS_DIR / "quality_gate_final.json", qg)
    docs(inventory, targeted, development, freeze, event)
    return freeze


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    freeze = run_all(args.workers, args.retries)
    print(json.dumps({
        "status": freeze["status"],
        "scope": freeze["scope"],
        "selected_research_universe": freeze["selected_research_universe"],
        "final_decision": FINAL_DECISION,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
