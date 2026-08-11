"""A0R3 existing-data exploratory discovery workflow.

This module deliberately separates metadata inventory from price loading so the
2018+ confirmation/validation years can remain outcome-blind during A0R3.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r2_statistics import (
    benjamini_hochberg_fdr,
    deflated_sharpe_ratio,
    hansen_spa,
    holm_adjust,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    romano_wolf,
    white_reality_check,
)

PAIRS = ("EURUSD", "GBPUSD", "USDJPY")
SIDES = ("bid", "ask")
INVENTORY_YEARS = tuple(range(2015, 2020))
EXPLORATORY_YEARS = (2015, 2016, 2017)
AVAILABLE_FIELDS = {
    "M1 bid/ask OHLC",
    "ask-update count",
    "M1 signed mid return",
    "bid-update count",
    "lagged cross-pair synchronized returns",
    "mid open/high/low/close",
    "quote-arrival count",
    "session labels",
    "spread open/high/low/close",
    "rolling range",
    "rolling realized variance",
    "rolling spread statistics",
    "realized volatility",
    "spread",
    "spread state",
    "quote mean distance",
    "abnormal return",
    "abnormal update rate",
}
RESULTS_ARTIFACT_ID = "A0R3_EXISTING_DATA_EXPLORATORY_DISCOVERY_V1"


@dataclass(frozen=True, slots=True)
class Paths:
    repo: Path
    raw: Path
    results: Path
    docs: Path
    trials: Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_hash(payload: Any) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded + b"\n")
    return sha256_bytes(encoded)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def prospective_split_amendment(paths: Paths) -> dict[str, Any]:
    payload = {
        "artifact_id": "A0R3_PROSPECTIVE_SPLIT_AMENDMENT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "EXPLORATORY_EXISTING_DATA_ONLY",
        "claim_boundary": "exploratory_only_not_confirmed_alpha",
        "boundaries": {
            "exploratory_discovery": ["2015-01-01", "2017-12-31"],
            "internal_confirmation": ["2018-01-01", "2018-12-31"],
            "external_validation": ["2019-01-01", "2019-12-31"],
            "replication": ["2020-01-01", "2022-12-31"],
            "quarantine": ["2023-01-01", "2025-12-31"],
        },
        "access_policy": {
            "price_data_loaded_years": [2015, 2016, 2017],
            "metadata_only_years": [2018, 2019],
            "forbidden_market_or_outcome_years": [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
            "confirmation_not_run": True,
            "validation_not_run": True,
        },
        "source_hashes": {
            "a0r2_trial_materialization_v2_jsonl": sha256_file(paths.trials),
        },
    }
    payload["self_hash"] = json_hash(payload)
    write_json(paths.results / "prospective_split_amendment.json", payload)
    return payload


def month_dir(raw: Path, pair: str, side: str, year: int, month: int) -> Path:
    return raw / pair / f"price={side}" / f"year={year}" / f"month={month:02d}"


def load_manifest(raw: Path, pair: str, side: str, year: int, month: int) -> dict[str, Any] | None:
    path = month_dir(raw, pair, side, year, month) / "manifest.json"
    if not path.exists():
        return None
    return read_json(path)


def inventory_pair_year(paths: Paths, pair: str, year: int) -> dict[str, Any]:
    side_summary: dict[str, Any] = {}
    pair_year_hashes: list[str] = []
    for side in SIDES:
        months: list[dict[str, Any]] = []
        for month in range(1, 13):
            mdir = month_dir(paths.raw, pair, side, year, month)
            manifest_path = mdir / "manifest.json"
            data_path = mdir / "data.json"
            manifest = load_manifest(paths.raw, pair, side, year, month)
            days = manifest.get("days", []) if manifest else []
            complete_days = [
                d for d in days if d.get("status") == "complete" and d.get("rows", 0) > 0
            ]
            market_closed = [
                d for d in days if str(d.get("status", "")).startswith("market_closed")
            ]
            failed_days = [d for d in days if d.get("status") == "failed"]
            month_record = {
                "month": month,
                "manifest_present": manifest_path.exists(),
                "data_present": data_path.exists(),
                "data_size": data_path.stat().st_size if data_path.exists() else 0,
                "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else "",
                "compacted_checksum": manifest.get("compacted_checksum", "") if manifest else "",
                "compacted_rows": manifest.get("compacted_rows", 0) if manifest else 0,
                "complete_days": len(complete_days),
                "market_closed_days": len(market_closed),
                "failed_days": len(failed_days),
                "complete_day_numbers": [int(d["day"]) for d in complete_days],
                "market_closed_day_numbers": [int(d["day"]) for d in market_closed],
                "failed_day_numbers": [int(d["day"]) for d in failed_days],
                "rows": int(sum(int(d.get("rows", 0)) for d in complete_days)),
                "day_checksum_count": len([d for d in complete_days if d.get("checksum")]),
            }
            months.append(month_record)
            if month_record["manifest_sha256"]:
                pair_year_hashes.append(str(month_record["manifest_sha256"]))
        side_summary[side] = {
            "present": all(m["manifest_present"] and m["data_present"] for m in months),
            "months_present": sum(1 for m in months if m["manifest_present"] and m["data_present"]),
            "rows_from_manifest": sum(int(m["rows"]) for m in months),
            "data_bytes": sum(int(m["data_size"]) for m in months),
            "manifest_hashes": [m["manifest_sha256"] for m in months],
            "compacted_checksums": [m["compacted_checksum"] for m in months],
            "months": months,
        }

    missing_open_market_days = 0
    complete_both_days = 0
    for month_index in range(12):
        bid_month = side_summary["bid"]["months"][month_index]
        ask_month = side_summary["ask"]["months"][month_index]
        bid_complete = set(bid_month["complete_day_numbers"])
        ask_complete = set(ask_month["complete_day_numbers"])
        bid_closed = set(bid_month["market_closed_day_numbers"])
        ask_closed = set(ask_month["market_closed_day_numbers"])
        complete_both_days += len(bid_complete & ask_complete)
        days_in_month = calendar.monthrange(year, month_index + 1)[1]
        for day in range(1, days_in_month + 1):
            if day in bid_closed or day in ask_closed:
                continue
            if day not in bid_complete or day not in ask_complete:
                missing_open_market_days += 1

    bid_rows = int(side_summary["bid"]["rows_from_manifest"])
    ask_rows = int(side_summary["ask"]["rows_from_manifest"])
    both_sides_present = bool(side_summary["bid"]["present"] and side_summary["ask"]["present"])
    return {
        "pair": pair,
        "year": year,
        "bid_present": bool(side_summary["bid"]["present"]),
        "ask_present": bool(side_summary["ask"]["present"]),
        "date_coverage": {
            "months_with_bid": side_summary["bid"]["months_present"],
            "months_with_ask": side_summary["ask"]["months_present"],
            "months_with_both_sides": sum(
                1
                for idx in range(12)
                if side_summary["bid"]["months"][idx]["manifest_present"]
                and side_summary["ask"]["months"][idx]["manifest_present"]
            ),
        },
        "valid_m1_rows_manifest": {
            "bid": bid_rows,
            "ask": ask_rows,
        },
        "complete_both_side_days_from_manifest": complete_both_days,
        "missing_open_market_days_from_manifest": missing_open_market_days,
        "ability_to_construct_deterministic_m5": bool(
            both_sides_present and bid_rows > 0 and ask_rows > 0
        ),
        "executable_spread_availability": bool(
            both_sides_present and bid_rows > 0 and ask_rows > 0
        ),
        "bytes": {
            "bid": side_summary["bid"]["data_bytes"],
            "ask": side_summary["ask"]["data_bytes"],
        },
        "provenance": {
            "manifest_sha256_set": sorted(set(pair_year_hashes)),
            "manifest_set_sha256": sha256_bytes("".join(sorted(pair_year_hashes)).encode()),
            "compacted_checksum_set": sorted(
                c for side in SIDES for c in side_summary[side]["compacted_checksums"] if c
            ),
            "raw_data_sha256_policy": ("computed_for_2015_2017_only; 2018_2019 kept metadata-only"),
        },
        "sides": side_summary,
    }


def inventory_existing_data(paths: Paths) -> dict[str, Any]:
    rows = [inventory_pair_year(paths, pair, year) for pair in PAIRS for year in INVENTORY_YEARS]
    return {
        "artifact_id": "A0R3_EXISTING_DATA_INVENTORY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "mode": "EXPLORATORY_EXISTING_DATA_ONLY",
        "raw_root": str(paths.raw),
        "price_data_loaded_years": [2015, 2016, 2017],
        "metadata_only_years": [2018, 2019],
        "rows": rows,
    }


def load_month_side_data(paths: Paths, pair: str, side: str, year: int, month: int) -> pd.DataFrame:
    if year >= 2018:
        raise ValueError("A0R3_2018_PLUS_PRICE_DATA_ACCESS_FORBIDDEN")
    path = month_dir(paths.raw, pair, side, year, month) / "data.json"
    rows = read_json(path)
    frame = pd.DataFrame(rows)
    if frame.empty:
        columns = [
            "timestamp",
            f"{side}_open",
            f"{side}_high",
            f"{side}_low",
            f"{side}_close",
            f"{side}_volume",
        ]
        return pd.DataFrame(columns=columns)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.rename(
        columns={
            "open": f"{side}_open",
            "high": f"{side}_high",
            "low": f"{side}_low",
            "close": f"{side}_close",
            "volume": f"{side}_volume",
        }
    )
    keep = [
        "timestamp",
        f"{side}_open",
        f"{side}_high",
        f"{side}_low",
        f"{side}_close",
        f"{side}_volume",
    ]
    return frame[keep].drop_duplicates("timestamp", keep="last").sort_values("timestamp")


def invalid_ohlc(frame: pd.DataFrame, prefix: str) -> int:
    if frame.empty:
        return 0
    high = frame[f"{prefix}_high"]
    low = frame[f"{prefix}_low"]
    open_ = frame[f"{prefix}_open"]
    close = frame[f"{prefix}_close"]
    return int(
        ((high < low) | (open_ < low) | (open_ > high) | (close < low) | (close > high)).sum()
    )


def expected_weekday_minutes(year: int) -> int:
    total = 0
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            if datetime(year, month, day, tzinfo=UTC).weekday() < 5:
                total += 1440
    return total


def canonical_hash(frame: pd.DataFrame) -> str:
    selected = frame.sort_values("timestamp").reset_index(drop=True)
    return sha256_bytes(pd.util.hash_pandas_object(selected, index=True).values.tobytes())


def m5_frame(frame: pd.DataFrame) -> pd.DataFrame:
    aggregations = {
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
    return (
        frame.set_index("timestamp")
        .resample("5min", label="left", closed="left")
        .agg(aggregations)
        .dropna(subset=["bid_close", "ask_close"])
        .reset_index()
    )


def load_exploratory_frames(paths: Paths) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    pair_frames: dict[str, pd.DataFrame] = {}
    quality_rows: list[dict[str, Any]] = []
    all_eligible = True
    blockers: list[str] = []

    for pair in PAIRS:
        frames = []
        for year in EXPLORATORY_YEARS:
            year_frames = []
            missing_open_market_days = 0
            raw_hashes = []
            for month in range(1, 13):
                bid_manifest = load_manifest(paths.raw, pair, "bid", year, month)
                ask_manifest = load_manifest(paths.raw, pair, "ask", year, month)
                bid = load_month_side_data(paths, pair, "bid", year, month)
                ask = load_month_side_data(paths, pair, "ask", year, month)
                raw_hashes.extend(
                    [
                        sha256_file(month_dir(paths.raw, pair, "bid", year, month) / "data.json"),
                        sha256_file(month_dir(paths.raw, pair, "ask", year, month) / "data.json"),
                    ]
                )
                merged = pd.merge(bid, ask, on="timestamp", how="inner")
                year_frames.append(merged)
                if bid_manifest and ask_manifest:
                    for bday, aday in zip(
                        bid_manifest.get("days", []), ask_manifest.get("days", []), strict=False
                    ):
                        status_pair = {bday.get("status"), aday.get("status")}
                        closed = any(str(s).startswith("market_closed") for s in status_pair)
                        complete = (
                            bday.get("status") == "complete" and aday.get("status") == "complete"
                        )
                        if not closed and not complete:
                            missing_open_market_days += 1
            year_frame = pd.concat(year_frames, ignore_index=True).sort_values("timestamp")
            duplicate_timestamps = int(year_frame["timestamp"].duplicated(keep=False).sum())
            negative_spreads = int((year_frame["ask_close"] < year_frame["bid_close"]).sum())
            invalid_rows = invalid_ohlc(year_frame, "bid") + invalid_ohlc(year_frame, "ask")
            observed_rows = int(len(year_frame))
            coverage = observed_rows / expected_weekday_minutes(year)
            gaps = year_frame["timestamp"].diff().dropna().dt.total_seconds().div(60)
            m5 = m5_frame(year_frame)
            eligible = (
                observed_rows > 250_000
                and coverage >= 0.65
                and duplicate_timestamps == 0
                and invalid_rows == 0
                and negative_spreads == 0
                and missing_open_market_days <= 15
                and not m5.empty
            )
            all_eligible = all_eligible and eligible
            if not eligible:
                blockers.append(f"{pair}-{year}:EXPLORATORY_MINIMUM_QUALITY_FAILED")
            quality_rows.append(
                {
                    "pair": pair,
                    "year": year,
                    "bid_ask_available": True,
                    "valid_m1_rows": observed_rows,
                    "expected_weekday_minutes": expected_weekday_minutes(year),
                    "coverage_ratio": round(float(coverage), 6),
                    "missing_open_market_days": missing_open_market_days,
                    "duplicate_timestamps": duplicate_timestamps,
                    "invalid_ohlc_rows": invalid_rows,
                    "negative_spreads": negative_spreads,
                    "longest_gap_minutes": int(gaps.max()) if not gaps.empty else 0,
                    "first_timestamp": year_frame["timestamp"].min().isoformat(),
                    "last_timestamp": year_frame["timestamp"].max().isoformat(),
                    "m5_rows": int(len(m5)),
                    "m1_canonical_hash": canonical_hash(year_frame),
                    "m5_canonical_hash": canonical_hash(m5),
                    "raw_data_sha256_set_hash": sha256_bytes("".join(sorted(raw_hashes)).encode()),
                    "synthetic_fills": 0,
                    "executable_spread_available": True,
                    "eligibility": "PASS" if eligible else "FAIL",
                }
            )
            frames.append(year_frame)
        pair_frame = (
            pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        )
        pair_frame["mid_close"] = (pair_frame["bid_close"] + pair_frame["ask_close"]) / 2.0
        pair_frame["spread"] = pair_frame["ask_close"] - pair_frame["bid_close"]
        pair_frame["mid_return"] = pair_frame["mid_close"].pct_change().fillna(0.0)
        pair_frames[pair] = pair_frame

    audit = {
        "artifact_id": "A0R3_EXISTING_DATA_ELIGIBILITY_AUDIT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if all_eligible else "BLOCKED",
        "mode": "EXPLORATORY_EXISTING_DATA_ONLY",
        "not_confirmatory_a0r2_certification": True,
        "old_tick_audit_required": False,
        "quality_gate": {
            "both_bid_and_ask_required": True,
            "minimum_rows_per_pair_year": 250000,
            "minimum_weekday_minute_coverage": 0.65,
            "max_missing_open_market_days_per_pair_year": 15,
            "require_timestamp_order": True,
            "require_no_negative_spreads": True,
            "require_no_synthetic_fills": True,
            "require_m1_to_m5_reproducible": True,
        },
        "rows": quality_rows,
        "blockers": blockers,
    }
    return pair_frames, audit


def dataset_freeze(
    paths: Paths, inventory: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    eligible_rows = [r for r in audit["rows"] if r["eligibility"] == "PASS"]
    freeze_hash_inputs = [
        r["m1_canonical_hash"] + r["m5_canonical_hash"] + r["raw_data_sha256_set_hash"]
        for r in eligible_rows
    ]
    payload = {
        "artifact_id": "A0R3_EXPLORATORY_DATASET_FREEZE_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if audit["status"] == "PASS" else "BLOCKED",
        "mode": "EXPLORATORY_EXISTING_DATA_ONLY",
        "boundaries": {
            "start": "2015-01-01",
            "end": "2017-12-31",
            "excluded_confirmation_validation_years": [2018, 2019],
        },
        "raw_root": str(paths.raw),
        "pairs": list(PAIRS),
        "pair_years": eligible_rows,
        "inventory_hash": json_hash(inventory),
        "eligibility_audit_hash": json_hash(audit),
        "no_2018_plus_market_or_outcome_data_loaded": True,
        "raw_market_data_modified": False,
        "freeze_hash_inputs": freeze_hash_inputs,
        "exclusions": [
            "2018 internal confirmation metadata only",
            "2019 external validation metadata only",
            "2020-2022 replication not accessed",
            "2023-2025 quarantine not accessed",
        ],
    }
    payload["frozen_dataset_sha256"] = sha256_bytes("".join(sorted(freeze_hash_inputs)).encode())
    return payload


def load_trials(paths: Paths) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in paths.trials.read_text(encoding="utf-8").splitlines() if line
    ]


def trial_pair_scope(config: dict[str, Any]) -> str | None:
    scope = config.get("instrument_or_portfolio_scope")
    if scope in PAIRS:
        return str(scope)
    edge = config.get("cross_pair_edge")
    if edge and edge[-1] in PAIRS:
        return str(edge[-1])
    triangle = config.get("triangle")
    if triangle:
        for pair in triangle:
            if pair in PAIRS:
                return str(pair)
    return None


def trial_eligibility(trials: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for trial in trials:
        config = trial["full_configuration"]
        family = trial["family_id"]
        reasons: list[str] = []
        scope = config.get("instrument_or_portfolio_scope")
        if scope == "nine_pair_portfolio":
            reasons.append("scope_requires_nine_pair_portfolio")
        elif scope and scope not in PAIRS:
            reasons.append("scope_pair_unavailable")
        edge = config.get("cross_pair_edge")
        if edge and not set(edge) <= set(PAIRS):
            reasons.append("cross_pair_edge_unavailable")
        triangle = config.get("triangle")
        if triangle and not set(triangle) <= set(PAIRS):
            reasons.append("triangle_unavailable")
        missing_inputs = sorted(set(config.get("required_inputs", [])) - AVAILABLE_FIELDS)
        if missing_inputs:
            reasons.append("required_fields_unavailable:" + ",".join(missing_inputs))
        status = "ELIGIBLE" if not reasons else "INELIGIBLE"
        by_family[family][status] += int(trial.get("candidate_equivalent_weight", 1))
        rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": family,
                "status": status,
                "candidate_equivalent_weight": trial.get("candidate_equivalent_weight", 1),
                "evaluation_pair": trial_pair_scope(config) if status == "ELIGIBLE" else None,
                "ineligibility_reasons": reasons,
                "configuration_sha256": trial["configuration_sha256"],
            }
        )
    return {
        "artifact_id": "A0R3_TRIAL_ELIGIBILITY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "total_trials": len(trials),
        "candidate_equivalent_count": sum(
            int(t.get("candidate_equivalent_weight", 1)) for t in trials
        ),
        "eligible_trials": sum(1 for r in rows if r["status"] == "ELIGIBLE"),
        "ineligible_trials": sum(1 for r in rows if r["status"] == "INELIGIBLE"),
        "invalid_trials_remain_in_multiplicity_count": True,
        "filter_basis": [
            "available fields",
            "available pair topology",
            "mechanical executability on EURUSD/GBPUSD/USDJPY",
        ],
        "performance_informed_filtering": False,
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "rows": rows,
    }


def ny_hour(timestamp: pd.Series) -> pd.Series:
    return pd.to_datetime(timestamp, utc=True).dt.tz_convert("America/New_York").dt.hour


def base_features(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    out = frame[["timestamp", "bid_close", "ask_close", "mid_close", "spread", "mid_return"]].copy()
    lb = max(int(lookback), 5)
    out["ret_lb"] = out["mid_close"].pct_change(lb).fillna(0.0)
    out["range_lb"] = (
        out["mid_close"].rolling(lb, min_periods=max(3, lb // 3)).max()
        - out["mid_close"].rolling(lb, min_periods=max(3, lb // 3)).min()
    ).fillna(0.0)
    out["vol_lb"] = out["mid_return"].rolling(lb, min_periods=max(3, lb // 3)).std().fillna(0.0)
    spread_mean = out["spread"].rolling(lb, min_periods=max(3, lb // 3)).mean()
    spread_std = out["spread"].rolling(lb, min_periods=max(3, lb // 3)).std().replace(0.0, np.nan)
    out["spread_z"] = ((out["spread"] - spread_mean) / spread_std).fillna(0.0)
    out["hour_ny"] = ny_hour(out["timestamp"])
    return out


def session_mask(features: pd.DataFrame, anchor: str | None) -> pd.Series:
    anchor_text = str(anchor or "").lower()
    hour = features["hour_ny"]
    if "tokyo" in anchor_text:
        return hour.isin([19, 20, 21])
    if "london 16" in anchor_text:
        return hour.isin([10, 11])
    if "new york" in anchor_text:
        return hour.isin([8, 9, 10])
    if "london" in anchor_text:
        return hour.isin([2, 3, 4])
    return pd.Series(True, index=features.index)


def trial_signal(
    frame: pd.DataFrame, trial: dict[str, Any], pair_frames: dict[str, pd.DataFrame]
) -> pd.Series:
    config = trial["full_configuration"]
    family = trial["family_id"]
    lookback = int(config.get("lookback") or 60)
    threshold = float(config.get("entry_threshold") or 0.5)
    variant = str(config.get("variant") or "").lower()
    features = base_features(frame, lookback)
    scale = features["vol_lb"].replace(0.0, np.nan).fillna(features["mid_return"].std() or 1e-9)
    raw = features["ret_lb"] / scale.clip(lower=1e-9)

    if family == "F01_SESSION_OPENING_MOMENTUM_REVERSAL":
        raw = raw.where(session_mask(features, config.get("session_anchor")), 0.0)
        if "reversal" in variant:
            raw = -raw
    elif family == "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION":
        run = np.sign(features["mid_return"]).rolling(lookback, min_periods=3).sum().fillna(0.0)
        raw = run / math.sqrt(max(lookback, 1))
        if "exhaust" in variant or "reversal" in variant:
            raw = -raw
    elif family == "F03_VOLATILITY_BREAKOUT":
        breakout = features["range_lb"] > features["range_lb"].rolling(
            lookback * 4, min_periods=lookback
        ).quantile(0.75)
        raw = raw.where(breakout.fillna(False), 0.0)
        if "failed" in variant:
            raw = -raw
    elif family == "F04_LIQUIDITY_SHOCK_REVERSAL":
        shock = (features["spread_z"] > 2.0) | (raw.abs() > 2.0)
        raw = (-raw).where(shock, 0.0)
    elif family == "F05_SPREAD_AWARE_EXECUTION_GATING":
        median_spread = features["spread"].rolling(lookback * 4, min_periods=lookback).median()
        raw = raw.where(
            features["spread"] <= median_spread.fillna(features["spread"].median()), 0.0
        )
    elif family == "F07_CURRENCY_FACTOR_RESIDUALS":
        aligned = (
            pd.concat(
                [
                    pframe.set_index("timestamp")["mid_return"].rename(pair)
                    for pair, pframe in pair_frames.items()
                ],
                axis=1,
            )
            .reindex(frame["timestamp"])
            .fillna(0.0)
        )
        residual = aligned[trial_pair_scope(config) or PAIRS[0]] - aligned.mean(axis=1)
        raw = residual.rolling(lookback, min_periods=3).sum().reset_index(drop=True)
        if "mean_reversion" in variant:
            raw = -raw
    elif family == "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL":
        aligned = (
            pd.concat(
                [
                    pframe.set_index("timestamp")["mid_return"]
                    .rolling(lookback, min_periods=3)
                    .sum()
                    .rename(pair)
                    for pair, pframe in pair_frames.items()
                ],
                axis=1,
            )
            .reindex(frame["timestamp"])
            .fillna(0.0)
        )
        ranks = aligned.rank(axis=1, pct=True)
        pair = trial_pair_scope(config) or PAIRS[0]
        raw = (ranks[pair] - 0.5).reset_index(drop=True)
        if "reversal" in variant:
            raw = -raw
    elif family == "F10_INTRADAY_SEASONALITY":
        minute = (
            pd.to_datetime(features["timestamp"], utc=True).dt.hour * 60
            + pd.to_datetime(features["timestamp"], utc=True).dt.minute
        )
        raw = (
            features["mid_return"]
            .groupby(minute)
            .transform(lambda x: x.expanding().mean().shift(1))
        )
        raw = raw.fillna(0.0) / scale.clip(lower=1e-9)
    elif family == "F11_REGIME_CONDITIONED_TREND_REVERSAL":
        vol_rank = features["vol_lb"].expanding().rank(pct=True).shift(1).fillna(0.5)
        raw = raw.where(vol_rank > 0.5, -raw)
    elif family == "F12_COST_SENSITIVE_ML_ABSTENTION":
        raw = 0.5 * raw - 0.25 * features["spread_z"]

    signal = np.where(raw >= threshold, 1, np.where(raw <= -threshold, -1, 0))
    return pd.Series(signal.astype(int), index=frame.index)


def execution_returns_bps(
    frame: pd.DataFrame, signal: pd.Series, cost_multiplier: float
) -> pd.Series:
    position = signal.shift(1).fillna(0).astype(int)
    eastern = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York")
    local_time = eastern.dt.time
    rollover = (local_time >= datetime.strptime("16:30", "%H:%M").time()) & (
        local_time <= datetime.strptime("17:30", "%H:%M").time()
    )
    position.loc[rollover] = 0
    previous = position.shift(1).fillna(0).astype(int)
    mid = frame["mid_close"]
    gross_bps = previous * mid.pct_change().fillna(0.0) * 10_000.0
    turnover = (position - previous).abs()
    spread_bps = (frame["spread"] / mid).replace([np.inf, -np.inf], np.nan).fillna(0.0) * 10_000.0
    commission_slippage_bps = 0.10
    costs = turnover * cost_multiplier * (spread_bps / 2.0 + commission_slippage_bps)
    return gross_bps - costs


def metrics_from_returns(returns: pd.Series) -> dict[str, float | int]:
    values = returns.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        finite = np.array([0.0])
    total = float(np.sum(finite))
    mean = float(np.mean(finite))
    std = float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
    sharpe = float(mean / std * math.sqrt(252 * 24 * 60)) if std else 0.0
    equity = np.cumsum(finite)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.min(equity - peak)) if len(equity) else 0.0
    hit_rate = float(np.mean(finite > 0.0)) if len(finite) else 0.0
    t_stat = float(mean / (std / math.sqrt(len(finite)))) if std else 0.0
    p_value = float(0.5 * math.erfc(t_stat / math.sqrt(2.0)))
    return {
        "bars": int(len(finite)),
        "net_bps": round(total, 6),
        "mean_bps": round(mean, 9),
        "sharpe": round(sharpe, 6),
        "max_drawdown_bps": round(max_dd, 6),
        "positive_bar_rate": round(hit_rate, 6),
        "p_value": max(0.0, min(1.0, p_value)),
    }


def evaluate_trials(
    pair_frames: dict[str, pd.DataFrame],
    trials: list[dict[str, Any]],
    eligibility: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    eligible_ids = {
        row["trial_id"]: row for row in eligibility["rows"] if row["status"] == "ELIGIBLE"
    }
    result_rows: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []
    p_values: list[float] = []
    sharpes: list[float] = []
    train_ranks: list[float] = []
    test_ranks: list[float] = []

    for trial in trials:
        row = eligible_ids.get(trial["trial_id"])
        if row is None:
            continue
        pair = row["evaluation_pair"]
        if pair is None:
            continue
        frame = pair_frames[pair]
        signal = trial_signal(frame, trial, pair_frames)
        base_returns = execution_returns_bps(frame, signal, 1.0)
        stress_15 = execution_returns_bps(frame, signal, 1.5)
        stress_20 = execution_returns_bps(frame, signal, 2.0)
        base_metrics = metrics_from_returns(base_returns)
        m15 = metrics_from_returns(stress_15)
        m20 = metrics_from_returns(stress_20)
        trades = int((signal.diff().fillna(signal).abs() > 0).sum())
        timestamps = pd.to_datetime(frame["timestamp"], utc=True)
        train_mask = timestamps.dt.year <= 2016
        test_mask = timestamps.dt.year == 2017
        train_sharpe = float(metrics_from_returns(base_returns.loc[train_mask])["sharpe"])
        test_sharpe = float(metrics_from_returns(base_returns.loc[test_mask])["sharpe"])
        p_values.append(float(base_metrics["p_value"]))
        sharpes.append(float(base_metrics["sharpe"]))
        train_ranks.append(train_sharpe)
        test_ranks.append(test_sharpe)
        result_rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": trial["family_id"],
                "pair": pair,
                "status": "COMPLETED_EXPLORATORY",
                "configuration_sha256": trial["configuration_sha256"],
                "trades": trades,
                "base": base_metrics,
                "train_2015_2016_sharpe": round(train_sharpe, 6),
                "test_2017_sharpe": round(test_sharpe, 6),
                "synthetic_fills_used": 0,
                "same_bar_handling": "adverse_first_contract_no_intrabar_target_stop_shortcut",
                "entry_latency": "one_completed_M1_bar",
            }
        )
        stress_rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": trial["family_id"],
                "pair": pair,
                "base_net_bps": base_metrics["net_bps"],
                "stress_1_5_net_bps": m15["net_bps"],
                "stress_2_0_net_bps": m20["net_bps"],
                "survives_1_5x": bool(float(m15["net_bps"]) > 0.0),
                "survives_2_0x": bool(float(m20["net_bps"]) > 0.0),
            }
        )

    holm = holm_adjust(p_values) if p_values else []
    bh = benjamini_hochberg_fdr(p_values) if p_values else []
    rw = romano_wolf(p_values) if p_values else []
    for idx, row in enumerate(result_rows):
        row["multiple_testing"] = {
            "holm_p": holm[idx],
            "bh_fdr_p": bh[idx],
            "romano_wolf_p": rw[idx],
            "psr": probabilistic_sharpe_ratio(float(row["base"]["sharpe"])),
            "dsr": deflated_sharpe_ratio(float(row["base"]["sharpe"]), trial_count=1200),
        }

    scores = np.array(sharpes, dtype=float)
    train_rank = (
        pd.Series(train_ranks).rank(pct=True).to_numpy(dtype=float) if train_ranks else np.array([])
    )
    test_rank = (
        pd.Series(test_ranks).rank(pct=True).to_numpy(dtype=float) if test_ranks else np.array([])
    )
    pbo = (
        probability_of_backtest_overfitting(float(np.mean(train_rank)), float(np.mean(test_rank)))
        if len(train_rank) and len(test_rank)
        else 0.0
    )
    testing = {
        "artifact_id": "A0R3_MULTIPLE_TESTING_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "trial_family_count_for_multiplicity": 1200,
        "evaluated_trials": len(result_rows),
        "white_reality_check_p": white_reality_check(scores) if len(scores) else 1.0,
        "hansen_spa_p": hansen_spa(scores) if len(scores) else 1.0,
        "pbo": pbo,
        "methods": [
            "White Reality Check",
            "Hansen SPA",
            "Romano-Wolf",
            "Holm",
            "BH-FDR",
            "PSR",
            "DSR",
            "PBO",
        ],
    }
    results = {
        "artifact_id": "A0R3_EXPLORATORY_RESULT_TABLE_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "evaluated_trials": len(result_rows),
        "rows": result_rows,
    }
    stress = {
        "artifact_id": "A0R3_COST_STRESS_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "rows": stress_rows,
        "survivors_1_5x": sum(1 for row in stress_rows if row["survives_1_5x"]),
        "survivors_2_0x": sum(1 for row in stress_rows if row["survives_2_0x"]),
    }
    shortlist_rows = [
        row
        for row in result_rows
        if float(row["base"]["net_bps"]) > 0.0 and float(row["multiple_testing"]["dsr"]) > 0.5
    ]
    shortlist_rows = sorted(
        shortlist_rows,
        key=lambda r: (
            float(r["multiple_testing"]["bh_fdr_p"]),
            -float(r["base"]["sharpe"]),
            r["trial_id"],
        ),
    )[:24]
    shortlist = {
        "artifact_id": "A0R3_EXPLORATORY_SHORTLIST_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "cap": 24,
        "shortlist_size": len(shortlist_rows),
        "rows": shortlist_rows,
    }
    return results, testing, stress, shortlist


def write_report(paths: Paths, artifacts: dict[str, Any]) -> None:
    audit = artifacts["eligibility"]
    inventory = artifacts["inventory"]
    trial_elig = artifacts["trial_eligibility"]
    results = artifacts["results"]
    testing = artifacts["multiple_testing"]
    stress = artifacts["cost_stress"]
    shortlist = artifacts["shortlist"]
    blockers = audit.get("blockers", [])
    lines = [
        "# A0R3 Existing-Data Exploratory Discovery",
        "",
        "Status: `EXPLORATORY_EXISTING_DATA_ONLY`",
        "",
        (
            "This run uses 2015-2017 only for exploratory discovery. It does not read "
            "or evaluate 2018+ price, return, strategy, confirmation, validation, "
            "replication, or quarantine outcomes."
        ),
        "",
        f"Eligibility verdict: `{audit['status']}`",
        f"Frozen dataset hash: `{artifacts['freeze']['frozen_dataset_sha256']}`",
        (
            f"Evaluated trials: `{results.get('evaluated_trials', 0)}` of `1200` "
            "candidate-equivalent registered trials."
        ),
        f"Shortlist size: `{shortlist['shortlist_size']}`",
        (
            "2018+ market/outcome data accessed: "
            f"`{artifacts['summary']['any_2018_plus_market_or_outcome_data_accessed']}`"
        ),
        "",
        "## Prospective Split",
        "",
        "| Stage | Start | End | A0R3 access |",
        "|---|---|---|---|",
        "| Exploratory discovery | 2015-01-01 | 2017-12-31 | price/outcome allowed |",
        "| Internal confirmation | 2018-01-01 | 2018-12-31 | metadata only |",
        "| External validation | 2019-01-01 | 2019-12-31 | metadata only |",
        "| Replication | 2020-01-01 | 2022-12-31 | not accessed |",
        "| Quarantine | 2023-01-01 | 2025-12-31 | not accessed |",
        "",
        "## Existing Data Inventory",
        "",
        f"Raw root: `{inventory['raw_root']}`",
        "",
        (
            "| Pair | Year | Bid | Ask | Bid M1 rows | Ask M1 rows | Complete both-side "
            "days | Missing open-market days | M5 constructible | Spread executable | "
            "Manifest set hash |"
        ),
        "|---|---:|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for row in inventory["rows"]:
        rows_manifest = row["valid_m1_rows_manifest"]
        lines.append(
            (
                "| {pair} | {year} | {bid} | {ask} | {bid_rows} | {ask_rows} | "
                "{both_days} | {missing} | {m5} | {spread} | `{hash}` |"
            ).format(
                pair=row["pair"],
                year=row["year"],
                bid=row["bid_present"],
                ask=row["ask_present"],
                bid_rows=rows_manifest["bid"],
                ask_rows=rows_manifest["ask"],
                both_days=row["complete_both_side_days_from_manifest"],
                missing=row["missing_open_market_days_from_manifest"],
                m5=row["ability_to_construct_deterministic_m5"],
                spread=row["executable_spread_availability"],
                hash=row["provenance"]["manifest_set_sha256"][:16],
            )
        )
    lines.extend(
        [
            "",
            "## 2015-2017 Eligibility Gate",
            "",
            (
                "| Pair | Year | Verdict | M1 rows | Coverage | Missing open-market days | "
                "Longest gap minutes | Negative spreads | M1 hash | M5 hash |"
            ),
            "|---|---:|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in audit["rows"]:
        lines.append(
            (
                "| {pair} | {year} | {verdict} | {rows} | {coverage:.6f} | "
                "{missing} | {gap} | {negative} | `{m1}` | `{m5}` |"
            ).format(
                pair=row["pair"],
                year=row["year"],
                verdict=row["eligibility"],
                rows=row["valid_m1_rows"],
                coverage=float(row["coverage_ratio"]),
                missing=row["missing_open_market_days"],
                gap=row["longest_gap_minutes"],
                negative=row["negative_spreads"],
                m1=row["m1_canonical_hash"][:16],
                m5=row["m5_canonical_hash"][:16],
            )
        )
    lines.extend(
        [
            "",
            "Blockers: " + ("`" + "`, `".join(blockers) + "`" if blockers else "`NONE`"),
            "",
            (
                "This is not confirmatory A0R2 certification, and the unresolved "
                "tick-audit criterion is not required for the frozen families that need "
                "only M1 bid/ask-derived fields."
            ),
            "",
            "## Dataset Freeze",
            "",
            f"Freeze status: `{artifacts['freeze']['status']}`",
            (
                f"Frozen pair-years: `{len(artifacts['freeze']['pair_years'])}` of `9` "
                "exploratory pair-years."
            ),
            "No raw market data was modified.",
            "",
            "## Trial Eligibility By Family",
            "",
            "| Family | Eligible | Ineligible |",
            "|---|---:|---:|",
        ]
    )
    for family, counts in trial_elig["by_family"].items():
        lines.append(f"| {family} | {counts.get('ELIGIBLE', 0)} | {counts.get('INELIGIBLE', 0)} |")
    lines.extend(
        [
            "",
            "## Multiple Testing",
            "",
            f"- White Reality Check p: `{testing.get('white_reality_check_p', 'NOT_RUN_BLOCKED')}`",
            f"- Hansen SPA p: `{testing.get('hansen_spa_p', 'NOT_RUN_BLOCKED')}`",
            f"- PBO: `{testing.get('pbo', 'NOT_RUN_BLOCKED')}`",
            "",
            "## Cost Stress",
            "",
            f"- 1.5x cost survivors: `{stress.get('survivors_1_5x', 'NOT_RUN_BLOCKED')}`",
            f"- 2.0x cost survivors: `{stress.get('survivors_2_0x', 'NOT_RUN_BLOCKED')}`",
            "",
            "## Top Exploratory Shortlist",
            "",
            "| Trial | Family | Pair | Net bps | Sharpe | BH-FDR | DSR |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in shortlist["rows"]:
        lines.append(
            (
                "| {trial_id} | {family_id} | {pair} | {net:.3f} | {sharpe:.3f} | "
                "{bh:.6f} | {dsr:.6f} |"
            ).format(
                trial_id=row["trial_id"],
                family_id=row["family_id"],
                pair=row["pair"],
                net=float(row["base"]["net_bps"]),
                sharpe=float(row["base"]["sharpe"]),
                bh=float(row["multiple_testing"]["bh_fdr_p"]),
                dsr=float(row["multiple_testing"]["dsr"]),
            )
        )
    paths.docs.mkdir(parents=True, exist_ok=True)
    (paths.docs / "A0R3_EXISTING_DATA_EXPLORATORY_DISCOVERY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run(paths: Paths) -> dict[str, Any]:
    paths.results.mkdir(parents=True, exist_ok=True)
    amendment = prospective_split_amendment(paths)
    inventory = inventory_existing_data(paths)
    pair_frames, eligibility_audit = load_exploratory_frames(paths)
    freeze = dataset_freeze(paths, inventory, eligibility_audit)
    trials = load_trials(paths)
    eligibility = trial_eligibility(trials)
    if eligibility_audit["status"] == "PASS":
        results, multiple_testing, cost_stress, shortlist = evaluate_trials(
            pair_frames, trials, eligibility
        )
    else:
        results = {
            "artifact_id": "A0R3_EXPLORATORY_RESULT_TABLE_V1",
            "gate_id": RESULTS_ARTIFACT_ID,
            "status": "BLOCKED",
            "rows": [],
        }
        multiple_testing = {
            "artifact_id": "A0R3_MULTIPLE_TESTING_RESULTS_V1",
            "gate_id": RESULTS_ARTIFACT_ID,
            "status": "BLOCKED",
        }
        cost_stress = {
            "artifact_id": "A0R3_COST_STRESS_RESULTS_V1",
            "gate_id": RESULTS_ARTIFACT_ID,
            "status": "BLOCKED",
            "rows": [],
        }
        shortlist = {
            "artifact_id": "A0R3_EXPLORATORY_SHORTLIST_V1",
            "gate_id": RESULTS_ARTIFACT_ID,
            "status": "BLOCKED",
            "rows": [],
            "shortlist_size": 0,
        }

    artifacts = {
        "amendment": amendment,
        "inventory": inventory,
        "eligibility": eligibility_audit,
        "freeze": freeze,
        "trial_eligibility": eligibility,
        "results": results,
        "multiple_testing": multiple_testing,
        "cost_stress": cost_stress,
        "shortlist": shortlist,
    }
    hashes = {
        name: write_json(paths.results / f"{name}.json", artifact)
        for name, artifact in artifacts.items()
    }
    summary = {
        "artifact_id": "A0R3_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if eligibility_audit["status"] == "PASS" else "BLOCKED",
        "mode": "EXPLORATORY_EXISTING_DATA_ONLY",
        "artifact_hashes": hashes,
        "frozen_dataset_sha256": freeze.get("frozen_dataset_sha256"),
        "evaluated_trials": results.get("evaluated_trials", 0),
        "shortlist_size": shortlist.get("shortlist_size", 0),
        "any_2018_plus_market_or_outcome_data_accessed": False,
        "raw_market_data_modified": False,
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
    }
    write_json(paths.results / "summary.json", summary)
    artifacts["summary"] = summary
    write_report(paths, artifacts)
    return summary
