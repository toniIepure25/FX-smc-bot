"""Gate C.4 USDJPY event-alpha research helpers.

The module deliberately works at event level. It computes direction-normalized
forward markouts and matched-control effects, not strategy backtest metrics.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from fx_smc_bot.data.development_freeze import (
    freeze_scope_hash,
    validate_pair_scoped_development_freeze,
)

ALLOWED_PAIR = "USDJPY"
DEVELOPMENT_YEARS = tuple(range(2015, 2020))
DISCOVERY_YEARS = tuple(range(2015, 2018))
REPLICATION_YEARS = tuple(range(2018, 2020))
PIP_SIZE = 0.01
POINT_SCALE = 1000.0
RNG_SEED = 4242
PRIMARY_HORIZONS_MIN = {
    "liquidity_sweep_mss_fvg_reversal": 60,
    "liquidity_acceptance_fvg_continuation": 120,
    "opening_range_london": 60,
    "opening_range_new_york": 60,
}
SECONDARY_HORIZONS_MIN = [15, 30, 60, 120, 240]
MIN_TOTAL_EVENTS = 40
MIN_REPLICATION_EVENTS = 10
EMBARGO_MINUTES = max(PRIMARY_HORIZONS_MIN.values())
PROHIBITED_RESULT_KEYS = {
    "pnl",
    "equity_curve",
    "sharpe",
    "sortino",
    "profit_factor",
    "max_drawdown",
    "kelly",
    "position_size",
    "portfolio_allocation",
    "prop_challenge_probability",
}


@dataclass(frozen=True, slots=True)
class GateC4Paths:
    """Repository paths used by Gate C.4."""

    root: Path

    @property
    def results_dir(self) -> Path:
        return self.root / "results" / "gate_c4"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs" / "research"

    @property
    def row_data_dir(self) -> Path:
        return self.root / "data" / "raw" / "gate_c4"

    @property
    def freeze_path(self) -> Path:
        return self.root / "results" / "gate_c3fcrsf" / "development_dataset_freeze.json"

    @property
    def canonical_m5_dir(self) -> Path:
        return self.root / "data" / "canonical" / "gate_c3fv" / ALLOWED_PAIR / "timeframe=M5"


def stable_json_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def run_git(root: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def repository_state(root: Path, starting_sha: str | None = None) -> dict[str, Any]:
    head = run_git(root, ["rev-parse", "HEAD"])
    status = run_git(root, ["status", "--short"])
    branch = run_git(root, ["branch", "--show-current"])
    state = {
        "branch": branch,
        "head_sha": head,
        "starting_sha_expected": starting_sha,
        "starting_sha_matches": starting_sha in (None, head),
        "working_tree_short_status": status,
        "working_tree_clean": status == "",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }
    return state


def load_freeze(paths: GateC4Paths) -> dict[str, Any]:
    return json.loads(paths.freeze_path.read_text())


def freeze_integrity(paths: GateC4Paths) -> dict[str, Any]:
    freeze = load_freeze(paths)
    expected_checksums = {
        pair: checksum for pair, checksum in freeze.get("included_canonical_checksums", {}).items()
    }
    validation = validate_pair_scoped_development_freeze(
        freeze_path=paths.freeze_path,
        requested_pairs=[ALLOWED_PAIR],
        expected_audit_hash=freeze.get("development_audit_hash", ""),
        expected_certification_hash=freeze.get("development_certification_hash", ""),
        expected_pair_checksums=expected_checksums,
    )
    rejection_audits = {}
    for requested in (["EURUSD"], ["GBPUSD"], ["USDJPY", "EURUSD"]):
        result = validate_pair_scoped_development_freeze(
            freeze_path=paths.freeze_path,
            requested_pairs=requested,
            expected_audit_hash=freeze.get("development_audit_hash", ""),
            expected_certification_hash=freeze.get("development_certification_hash", ""),
            expected_pair_checksums=expected_checksums,
        )
        rejection_audits[",".join(requested)] = {
            "passed": result.passed,
            "reasons": result.reasons,
        }
    return {
        "freeze_file": str(paths.freeze_path),
        "freeze_file_sha256": file_sha256(paths.freeze_path),
        "status": freeze.get("status"),
        "scope": freeze.get("scope"),
        "selected_research_universe": freeze.get("selected_research_universe", []),
        "freeze_scope_hash": freeze.get("freeze_scope_hash"),
        "recomputed_freeze_scope_hash": freeze_scope_hash(freeze),
        "usd_jpy_validation_passed": validation.passed,
        "usd_jpy_validation_reasons": validation.reasons,
        "excluded_pair_rejection_audit": rejection_audits,
    }


def assert_development_request(pair: str, years: tuple[int, ...] = DEVELOPMENT_YEARS) -> None:
    if pair != ALLOWED_PAIR:
        raise ValueError(f"Gate C.4 is frozen to {ALLOWED_PAIR}; requested {pair}")
    outside = sorted(set(years) - set(DEVELOPMENT_YEARS))
    if outside:
        raise ValueError(f"Gate C.4 may not access validation/holdout years: {outside}")


def event_definition_inventory(root: Path) -> dict[str, Any]:
    files = {
        "sweep_source": root / "src/fx_smc_bot/alpha/intraday/sweep_reversal.py",
        "acceptance_source": root / "src/fx_smc_bot/alpha/intraday/acceptance_continuation.py",
        "opening_range_source": root / "src/fx_smc_bot/alpha/intraday/opening_range.py",
        "sweep_config": root / "configs/research/intraday_smc/sweep_reversal.yaml",
        "acceptance_config": root / "configs/research/intraday_smc/acceptance_continuation.yaml",
        "opening_range_config": root / "configs/research/intraday_smc/opening_range.yaml",
    }
    parsed_configs = {}
    for name, path in files.items():
        if path.suffix in {".yaml", ".yml"}:
            parsed_configs[name] = yaml.safe_load(path.read_text())
    families = {
        "liquidity_sweep_mss_fvg_reversal": {
            "source": str(files["sweep_source"]),
            "config": str(files["sweep_config"]),
            "operational_event": (
                "prior-day high/low liquidity sweep, same-bar close reclaim, "
                "direction opposite the swept side"
            ),
            "primary_horizon_minutes": PRIMARY_HORIZONS_MIN["liquidity_sweep_mss_fvg_reversal"],
        },
        "liquidity_acceptance_fvg_continuation": {
            "source": str(files["acceptance_source"]),
            "config": str(files["acceptance_config"]),
            "operational_event": (
                "two consecutive closes beyond prior-day high/low liquidity level, "
                "direction with the break"
            ),
            "primary_horizon_minutes": PRIMARY_HORIZONS_MIN[
                "liquidity_acceptance_fvg_continuation"
            ],
        },
        "opening_range_london": {
            "source": str(files["opening_range_source"]),
            "config": str(files["opening_range_config"]),
            "operational_event": "first London opening-range displacement close before cutoff",
            "primary_horizon_minutes": PRIMARY_HORIZONS_MIN["opening_range_london"],
        },
        "opening_range_new_york": {
            "source": str(files["opening_range_source"]),
            "config": str(files["opening_range_config"]),
            "operational_event": "first New York opening-range displacement close before cutoff",
            "primary_horizon_minutes": PRIMARY_HORIZONS_MIN["opening_range_new_york"],
        },
    }
    file_hashes = {name: file_sha256(path) for name, path in files.items()}
    return {
        "families": families,
        "file_hashes": file_hashes,
        "config_hash": stable_json_hash(parsed_configs),
        "config_instrument_audit": {
            "historical_configs_include": ["EURUSD", "GBPUSD", "USDJPY"],
            "gate_c4_runtime_universe": [ALLOWED_PAIR],
            "finding": "Runtime universe is narrowed by the CRSF pair-scoped freeze.",
        },
    }


def preregistration_payload(
    root: Path,
    inventory: dict[str, Any],
    freeze: dict[str, Any],
    starting_sha: str | None,
) -> dict[str, Any]:
    core = {
        "gate": "C.4",
        "study": "USDJPY Event-Alpha Discovery and Internal Temporal Replication",
        "starting_sha_expected": starting_sha,
        "allowed_pair": ALLOWED_PAIR,
        "development_years": DEVELOPMENT_YEARS,
        "discovery_years": DISCOVERY_YEARS,
        "replication_years": REPLICATION_YEARS,
        "primary_horizons_minutes": PRIMARY_HORIZONS_MIN,
        "secondary_horizons_minutes": SECONDARY_HORIZONS_MIN,
        "event_definition_config_hash": inventory["config_hash"],
        "event_definition_file_hashes": inventory["file_hashes"],
        "freeze_scope_hash": freeze["freeze_scope_hash"],
        "control_matching": {
            "exact_keys": ["year", "month", "session", "direction"],
            "covariates": [
                "spread",
                "atr",
                "pre_event_volatility",
                "pre_event_trend",
                "range_position",
            ],
            "replacement": True,
            "random_seed": RNG_SEED,
            "embargo_minutes": EMBARGO_MINUTES,
        },
        "inference": {
            "paired_permutation_iterations": 2000,
            "cluster_bootstrap_iterations": 1000,
            "multiple_testing": "Holm across primary family tests",
            "minimum_total_events": MIN_TOTAL_EVENTS,
            "minimum_replication_events": MIN_REPLICATION_EVENTS,
        },
        "decision_rules": {
            "confirmed": (
                "adequate event count, positive event and matched-control primary "
                "effect, Holm p<=0.05, positive replication effect, and placebo "
                "checks not reproducing the primary effect"
            ),
            "mixed": "directionally positive or heterogeneous but not confirmed",
            "null": "adequate event count without a positive primary effect",
            "insufficient": "event count below preregistered minimums",
        },
        "prohibited_metrics": sorted(PROHIBITED_RESULT_KEYS),
    }
    return {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "repository_head_sha_at_preregistration": run_git(root, ["rev-parse", "HEAD"]),
        "core": core,
        "preregistration_hash": stable_json_hash(core),
    }


def _mid_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[f"mid_{col}"] = (out[f"bid_{col}"] + out[f"ask_{col}"]) / 2.0
    out["spread"] = out["ask_open"] - out["bid_open"]
    prev_close = out["mid_close"].shift(1)
    tr = pd.concat(
        [
            out["mid_high"] - out["mid_low"],
            (out["mid_high"] - prev_close).abs(),
            (out["mid_low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(14, min_periods=5).mean().shift(1)
    ret = out["mid_close"].pct_change()
    out["pre_event_volatility"] = ret.rolling(24, min_periods=8).std().shift(1)
    out["pre_event_trend"] = (out["mid_close"].shift(1) - out["mid_close"].shift(49)) / out[
        "atr"
    ].replace(0.0, np.nan)
    roll_high = out["mid_high"].rolling(48, min_periods=12).max().shift(1)
    roll_low = out["mid_low"].rolling(48, min_periods=12).min().shift(1)
    out["range_position"] = (out["mid_close"].shift(1) - roll_low) / (roll_high - roll_low)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["year"] = out["timestamp"].dt.year
    out["month"] = out["timestamp"].dt.month
    out["utc_date"] = out["timestamp"].dt.date.astype(str)
    out["session"] = out["timestamp"].map(session_label)
    daily = out.groupby("utc_date").agg(day_high=("mid_high", "max"), day_low=("mid_low", "min"))
    daily["prev_day_high"] = daily["day_high"].shift(1)
    daily["prev_day_low"] = daily["day_low"].shift(1)
    out = out.join(daily[["prev_day_high", "prev_day_low"]], on="utc_date")
    return out.reset_index(drop=True)


def session_label(ts: pd.Timestamp) -> str:
    hour = int(ts.hour)
    if 0 <= hour < 6:
        return "asia"
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 17:
        return "new_york"
    return "other"


def load_development_m5(paths: GateC4Paths) -> pd.DataFrame:
    assert_development_request(ALLOWED_PAIR, DEVELOPMENT_YEARS)
    files = []
    for year in DEVELOPMENT_YEARS:
        year_dir = paths.canonical_m5_dir / f"year={year}"
        files.extend(sorted(year_dir.glob("month=*/part.parquet")))
    if not files:
        raise FileNotFoundError(f"No M5 canonical files found under {paths.canonical_m5_dir}")
    df = pd.concat((pd.read_parquet(path) for path in files), ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    years = set(df["timestamp"].dt.year.unique())
    if not years.issubset(set(DEVELOPMENT_YEARS)):
        raise ValueError(f"Loaded timestamps outside development years: {sorted(years)}")
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return _mid_frame(df)


def _displacement(row: pd.Series, median_body: float, direction: str) -> bool:
    body = abs(float(row["mid_close"]) - float(row["mid_open"]))
    tr = float(row["mid_high"]) - float(row["mid_low"])
    atr = float(row["atr"])
    if not np.isfinite(atr) or atr <= 0 or median_body <= 0 or tr <= 0:
        return False
    clv = (float(row["mid_close"]) - float(row["mid_low"])) / tr
    if direction == "LONG":
        return body >= 1.5 * median_body and tr >= 1.2 * atr and clv >= 0.5
    return body >= 1.5 * median_body and tr >= 1.2 * atr and clv <= 0.5


def _event_id(family: str, ts: pd.Timestamp, direction: str, level: float) -> str:
    payload = f"{family}|{ts.isoformat()}|{direction}|{level:.5f}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _base_event(
    df: pd.DataFrame,
    idx: int,
    family: str,
    direction: str,
    source_level: float,
    subtype: str,
) -> dict[str, Any] | None:
    if idx + 1 + max(h // 5 for h in SECONDARY_HORIZONS_MIN) >= len(df):
        return None
    row = df.iloc[idx]
    covars = ["spread", "atr", "pre_event_volatility", "pre_event_trend", "range_position"]
    if any(not np.isfinite(float(row[c])) for c in covars):
        return None
    return {
        "event_id": _event_id(family, row["timestamp"], direction, source_level),
        "pair": ALLOWED_PAIR,
        "family": family,
        "subtype": subtype,
        "direction": direction,
        "confirmation_index": idx,
        "confirmation_timestamp": row["timestamp"],
        "earliest_entry_index": idx + 1,
        "earliest_entry_timestamp": df.iloc[idx + 1]["timestamp"],
        "source_level": float(source_level),
        "year": int(row["year"]),
        "month": int(row["month"]),
        "session": str(row["session"]),
        "utc_date": str(row["utc_date"]),
        "spread": float(row["spread"]),
        "atr": float(row["atr"]),
        "pre_event_volatility": float(row["pre_event_volatility"]),
        "pre_event_trend": float(row["pre_event_trend"]),
        "range_position": float(row["range_position"]),
        "primary_horizon_minutes": PRIMARY_HORIZONS_MIN[family],
    }


def extract_events(df: pd.DataFrame) -> pd.DataFrame:
    events: list[dict[str, Any]] = []
    median_body = (df["mid_close"] - df["mid_open"]).abs().rolling(20, min_periods=5).median()
    for idx in range(50, len(df) - 50):
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        prev2 = df.iloc[idx - 2]
        atr = float(row["atr"])
        spread = float(row["spread"])
        high_level = float(row["prev_day_high"])
        low_level = float(row["prev_day_low"])
        if not all(np.isfinite(v) for v in (atr, spread, high_level, low_level)):
            continue
        sweep_min = max(0.5 * atr, 2.0 * spread, 3.0 * PIP_SIZE)
        break_min = max(0.3 * atr, 1.5 * spread, 2.0 * PIP_SIZE)
        if float(row["mid_high"]) > high_level + sweep_min and float(row["mid_close"]) < high_level:
            event = _base_event(
                df,
                idx,
                "liquidity_sweep_mss_fvg_reversal",
                "SHORT",
                high_level,
                "prior_day_high_sweep_reclaim",
            )
            if event:
                events.append(event)
        if float(row["mid_low"]) < low_level - sweep_min and float(row["mid_close"]) > low_level:
            event = _base_event(
                df,
                idx,
                "liquidity_sweep_mss_fvg_reversal",
                "LONG",
                low_level,
                "prior_day_low_sweep_reclaim",
            )
            if event:
                events.append(event)
        high_break = high_level + break_min
        low_break = low_level - break_min
        if (
            float(prev["mid_close"]) > high_break
            and float(row["mid_close"]) > high_break
            and float(prev2["mid_close"]) <= high_break
        ):
            event = _base_event(
                df,
                idx,
                "liquidity_acceptance_fvg_continuation",
                "LONG",
                high_level,
                "prior_day_high_acceptance",
            )
            if event:
                events.append(event)
        if (
            float(prev["mid_close"]) < low_break
            and float(row["mid_close"]) < low_break
            and float(prev2["mid_close"]) >= low_break
        ):
            event = _base_event(
                df,
                idx,
                "liquidity_acceptance_fvg_continuation",
                "SHORT",
                low_level,
                "prior_day_low_acceptance",
            )
            if event:
                events.append(event)
    events.extend(_opening_range_events(df, median_body, "opening_range_london"))
    events.extend(_opening_range_events(df, median_body, "opening_range_new_york"))
    out = pd.DataFrame(events)
    if out.empty:
        return out
    return (
        out.drop_duplicates("event_id").sort_values("confirmation_timestamp").reset_index(drop=True)
    )


def _opening_range_events(
    df: pd.DataFrame,
    median_body: pd.Series,
    family: str,
) -> list[dict[str, Any]]:
    if family == "opening_range_london":
        tz = ZoneInfo("Europe/London")
        start = time(8, 0)
        end = time(8, 30)
        cutoff = time(11, 0)
    else:
        tz = ZoneInfo("America/New_York")
        start = time(8, 0)
        end = time(8, 30)
        cutoff = time(11, 0)
    local = df["timestamp"].dt.tz_convert(tz)
    work = df.assign(local_date=local.dt.date.astype(str), local_time=local.dt.time)
    events: list[dict[str, Any]] = []
    for _, day in work.groupby("local_date", sort=True):
        range_rows = day[(day["local_time"] >= start) & (day["local_time"] < end)]
        if range_rows.empty:
            continue
        after = day[(day["local_time"] >= end) & (day["local_time"] < cutoff)]
        if after.empty:
            continue
        rng_high = float(range_rows["mid_high"].max())
        rng_low = float(range_rows["mid_low"].min())
        atr0 = float(after.iloc[0]["atr"])
        if not np.isfinite(atr0) or atr0 <= 0:
            continue
        range_atr = (rng_high - rng_low) / atr0
        if range_atr < 0.3 or range_atr > 3.0:
            continue
        for idx, row in after.iterrows():
            atr = float(row["atr"])
            min_dist = 0.2 * atr
            direction = None
            level = math.nan
            subtype = ""
            if float(row["mid_close"]) > rng_high + min_dist:
                direction = "LONG"
                level = rng_high
                subtype = "opening_range_high_break"
            elif float(row["mid_close"]) < rng_low - min_dist:
                direction = "SHORT"
                level = rng_low
                subtype = "opening_range_low_break"
            if direction and _displacement(row, float(median_body.iloc[idx]), direction):
                event = _base_event(df, int(idx), family, direction, level, subtype)
                if event:
                    event["opening_range_atr"] = float(range_atr)
                    events.append(event)
                break
    return events


def apply_outcomes(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    horizon_bars = {minutes: minutes // 5 for minutes in SECONDARY_HORIZONS_MIN}
    for record in events.to_dict("records"):
        entry_idx = int(record["earliest_entry_index"])
        direction = str(record["direction"])
        entry = df.iloc[entry_idx]
        rec = dict(record)
        for minutes, bars in horizon_bars.items():
            exit_idx = entry_idx + bars
            if exit_idx >= len(df):
                rec[f"h{minutes}_complete"] = False
                continue
            exit_row = df.iloc[exit_idx]
            if direction == "LONG":
                executable = (float(exit_row["bid_close"]) - float(entry["ask_open"])) * POINT_SCALE
                mid = (float(exit_row["mid_close"]) - float(entry["mid_open"])) * POINT_SCALE
            else:
                executable = (float(entry["bid_open"]) - float(exit_row["ask_close"])) * POINT_SCALE
                mid = (float(entry["mid_open"]) - float(exit_row["mid_close"])) * POINT_SCALE
            rec[f"h{minutes}_executable_markout_points"] = executable
            rec[f"h{minutes}_mid_markout_points"] = mid
            rec[f"h{minutes}_positive"] = executable > 0
            rec[f"h{minutes}_complete"] = True
        primary = int(rec["primary_horizon_minutes"])
        rec["primary_executable_markout_points"] = rec[f"h{primary}_executable_markout_points"]
        rec["primary_mid_markout_points"] = rec[f"h{primary}_mid_markout_points"]
        rec["primary_positive"] = rec[f"h{primary}_positive"]
        records.append(rec)
    return pd.DataFrame(records)


def mark_non_overlapping(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    out["non_overlap_primary"] = False
    selected_until: dict[str, pd.Timestamp] = {}
    for idx, row in out.sort_values("confirmation_timestamp").iterrows():
        family = str(row["family"])
        ts = row["confirmation_timestamp"]
        until = selected_until.get(family)
        if until is None or ts > until:
            out.at[idx, "non_overlap_primary"] = True
            selected_until[family] = row["earliest_entry_timestamp"] + pd.Timedelta(
                minutes=int(row["primary_horizon_minutes"])
            )
    return out


def _candidate_pool(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    blocked = np.zeros(len(df), dtype=bool)
    embargo_bars = EMBARGO_MINUTES // 5
    for idx in events["confirmation_index"].astype(int):
        lo = max(0, idx - embargo_bars)
        hi = min(len(df), idx + embargo_bars + 1)
        blocked[lo:hi] = True
    covars = ["spread", "atr", "pre_event_volatility", "pre_event_trend", "range_position"]
    pool = df.loc[~blocked, ["timestamp", "year", "month", "session", *covars]].copy()
    pool["bar_index"] = pool.index
    return pool.dropna(subset=covars)


def match_controls(df: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    pool = _candidate_pool(df, events)
    covars = ["spread", "atr", "pre_event_volatility", "pre_event_trend", "range_position"]
    scale = pool[covars].std().replace(0.0, 1.0)
    matches = []
    rng = np.random.default_rng(RNG_SEED)
    grouped = {key: grp for key, grp in pool.groupby(["year", "month", "session"], sort=False)}
    for event in events.to_dict("records"):
        key = (event["year"], event["month"], event["session"])
        candidates = grouped.get(key)
        loosened = False
        if candidates is None or candidates.empty:
            candidates = pool[
                (pool["year"] == event["year"]) & (pool["session"] == event["session"])
            ]
            loosened = True
        if candidates.empty:
            candidates = pool[pool["year"] == event["year"]]
            loosened = True
        if len(candidates) > 2000:
            seed = int(hashlib.sha256(str(event["event_id"]).encode()).hexdigest()[:8], 16)
            candidates = candidates.sample(n=2000, random_state=seed)
        event_vec = np.array([event[c] for c in covars], dtype=float)
        cand_mat = candidates[covars].to_numpy(dtype=float)
        dist = np.sum(((cand_mat - event_vec) / scale.to_numpy(dtype=float)) ** 2, axis=1)
        min_dist = np.nanmin(dist)
        ties = np.flatnonzero(np.isclose(dist, min_dist))
        chosen_pos = int(rng.choice(ties))
        chosen = candidates.iloc[chosen_pos]
        matches.append(
            {
                "event_id": event["event_id"],
                "family": event["family"],
                "direction": event["direction"],
                "control_index": int(chosen["bar_index"]),
                "control_timestamp": chosen["timestamp"],
                "match_distance": float(min_dist),
                "loosened_exact_match": bool(loosened),
                **{f"event_{c}": float(event[c]) for c in covars},
                **{f"control_{c}": float(chosen[c]) for c in covars},
            }
        )
    match_df = pd.DataFrame(matches)
    audit = balance_audit(match_df)
    audit["candidate_pool_rows"] = int(len(pool))
    audit["matches_with_loosened_exact_keys"] = int(match_df["loosened_exact_match"].sum())
    audit["matching_seed"] = RNG_SEED
    return match_df, audit


def add_control_outcomes(
    df: pd.DataFrame, events: pd.DataFrame, matches: pd.DataFrame
) -> pd.DataFrame:
    event_lookup = events.set_index("event_id")
    records = []
    for match in matches.to_dict("records"):
        event = event_lookup.loc[match["event_id"]]
        direction = str(match["direction"])
        entry_idx = int(match["control_index"]) + 1
        rec = dict(match)
        rec["control_entry_index"] = entry_idx
        if entry_idx + max(h // 5 for h in SECONDARY_HORIZONS_MIN) >= len(df):
            continue
        entry = df.iloc[entry_idx]
        for minutes in SECONDARY_HORIZONS_MIN:
            exit_row = df.iloc[entry_idx + minutes // 5]
            if direction == "LONG":
                executable = (float(exit_row["bid_close"]) - float(entry["ask_open"])) * POINT_SCALE
                mid = (float(exit_row["mid_close"]) - float(entry["mid_open"])) * POINT_SCALE
            else:
                executable = (float(entry["bid_open"]) - float(exit_row["ask_close"])) * POINT_SCALE
                mid = (float(entry["mid_open"]) - float(exit_row["mid_close"])) * POINT_SCALE
            rec[f"h{minutes}_control_executable_markout_points"] = executable
            rec[f"h{minutes}_control_mid_markout_points"] = mid
        primary = int(event["primary_horizon_minutes"])
        rec["primary_control_executable_markout_points"] = rec[
            f"h{primary}_control_executable_markout_points"
        ]
        rec["primary_control_mid_markout_points"] = rec[f"h{primary}_control_mid_markout_points"]
        records.append(rec)
    return pd.DataFrame(records)


def balance_audit(matches: pd.DataFrame) -> dict[str, Any]:
    covars = ["spread", "atr", "pre_event_volatility", "pre_event_trend", "range_position"]
    by_cov = {}
    for covar in covars:
        e = matches[f"event_{covar}"].to_numpy(dtype=float)
        c = matches[f"control_{covar}"].to_numpy(dtype=float)
        pooled = np.sqrt((np.nanvar(e) + np.nanvar(c)) / 2.0) or 1.0
        by_cov[covar] = {
            "event_mean": float(np.nanmean(e)),
            "control_mean": float(np.nanmean(c)),
            "standardized_mean_difference": float((np.nanmean(e) - np.nanmean(c)) / pooled),
        }
    max_abs = max(abs(v["standardized_mean_difference"]) for v in by_cov.values())
    return {"covariate_balance": by_cov, "max_abs_standardized_mean_difference": max_abs}


def summarize_counts(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {}
    return {
        "by_family": events.groupby("family").size().astype(int).to_dict(),
        "by_family_year": _nested_count(events, ["family", "year"]),
        "by_family_session": _nested_count(events, ["family", "session"]),
        "by_family_direction": _nested_count(events, ["family", "direction"]),
    }


def _nested_count(df: pd.DataFrame, keys: list[str]) -> dict[str, int]:
    return {"|".join(map(str, idx)): int(val) for idx, val in df.groupby(keys).size().items()}


def infer_primary(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls[
            [
                "event_id",
                "primary_control_executable_markout_points",
                "primary_control_mid_markout_points",
            ]
        ],
        on="event_id",
        how="inner",
    )
    families = {}
    raw_p_values = {}
    for family, fam in merged.groupby("family"):
        sample = fam[fam["non_overlap_primary"]].copy()
        result = family_estimand(sample)
        families[family] = result
        raw_p_values[family] = result["paired_permutation_p_value"]
    adjusted = holm_adjust(raw_p_values)
    for family, value in adjusted.items():
        families[family]["holm_adjusted_p_value"] = value
    return {
        "families": families,
        "multiple_testing": "Holm correction across primary non-overlap family tests",
    }


def family_estimand(sample: pd.DataFrame) -> dict[str, Any]:
    if sample.empty:
        return {"n_events": 0, "status": "INSUFFICIENT_EVENTS"}
    event = sample["primary_executable_markout_points"].to_numpy(dtype=float)
    control = sample["primary_control_executable_markout_points"].to_numpy(dtype=float)
    diff = event - control
    days = sample["utc_date"].to_numpy()
    ci = cluster_bootstrap_ci(diff, days, RNG_SEED, 1000)
    p_value = paired_permutation_p_value(diff, RNG_SEED, 2000)
    return {
        "n_events": int(len(sample)),
        "mean_event_markout_points": float(np.mean(event)),
        "median_event_markout_points": float(np.median(event)),
        "trimmed_mean_event_markout_points": float(stats.trim_mean(event, 0.1)),
        "positive_forward_return_probability": float(np.mean(event > 0)),
        "mean_matched_control_markout_points": float(np.mean(control)),
        "mean_event_minus_control_points": float(np.mean(diff)),
        "median_event_minus_control_points": float(np.median(diff)),
        "cluster_bootstrap_ci95_mean_diff_points": ci,
        "paired_permutation_p_value": p_value,
    }


def cluster_bootstrap_ci(
    values: np.ndarray,
    clusters: np.ndarray,
    seed: int,
    iterations: int,
) -> list[float | None]:
    if len(values) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    unique = np.unique(clusters)
    means = []
    for _ in range(iterations):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        mask = np.isin(clusters, sampled)
        if mask.any():
            means.append(float(np.mean(values[mask])))
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def paired_permutation_p_value(values: np.ndarray, seed: int, iterations: int) -> float:
    if len(values) < 2:
        return 1.0
    rng = np.random.default_rng(seed)
    observed = abs(float(np.mean(values)))
    draws = 0
    for _ in range(iterations):
        signs = rng.choice(np.array([-1.0, 1.0]), size=len(values), replace=True)
        if abs(float(np.mean(values * signs))) >= observed:
            draws += 1
    return float((draws + 1) / (iterations + 1))


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted = {}
    running = 0.0
    for rank, (family, p_value) in enumerate(ordered):
        adj = min(1.0, (m - rank) * p_value)
        running = max(running, adj)
        adjusted[family] = running
    return adjusted


def temporal_replication(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls[["event_id", "primary_control_executable_markout_points"]],
        on="event_id",
        how="inner",
    )
    out = {}
    for family, fam in merged.groupby("family"):
        parts = {}
        for name, years in (("discovery", DISCOVERY_YEARS), ("replication", REPLICATION_YEARS)):
            sample = fam[fam["year"].isin(years) & fam["non_overlap_primary"]]
            diff = sample["primary_executable_markout_points"].to_numpy(dtype=float) - sample[
                "primary_control_executable_markout_points"
            ].to_numpy(dtype=float)
            parts[name] = {
                "years": list(years),
                "n_events": int(len(sample)),
                "mean_event_minus_control_points": float(np.mean(diff)) if len(diff) else None,
                "mean_event_markout_points": float(
                    np.mean(sample["primary_executable_markout_points"])
                )
                if len(sample)
                else None,
            }
        out[family] = parts
    return out


def placebo_results(
    df: pd.DataFrame, events: pd.DataFrame, controls: pd.DataFrame
) -> dict[str, Any]:
    merged = events.merge(
        controls[["event_id", "primary_control_executable_markout_points"]],
        on="event_id",
        how="inner",
    )
    out = {}
    index_by_ts = {ts: i for i, ts in enumerate(df["timestamp"])}
    for family, fam in merged.groupby("family"):
        sample = fam[fam["non_overlap_primary"]].copy()
        event_mean = (
            float(sample["primary_executable_markout_points"].mean()) if len(sample) else None
        )
        direction_flip = -sample["primary_mid_markout_points"].to_numpy(dtype=float)
        shifted = []
        for row in sample.to_dict("records"):
            shifted_ts = row["confirmation_timestamp"] + pd.Timedelta(days=1)
            shifted_idx = index_by_ts.get(shifted_ts)
            if shifted_idx is None:
                continue
            pseudo = dict(row)
            pseudo["earliest_entry_index"] = shifted_idx + 1
            pseudo_df = apply_outcomes(df, pd.DataFrame([pseudo]))
            if not pseudo_df.empty:
                shifted.append(float(pseudo_df.iloc[0]["primary_executable_markout_points"]))
        random_control = sample["primary_control_executable_markout_points"].to_numpy(dtype=float)
        out[family] = {
            "n_events": int(len(sample)),
            "primary_event_mean_points": event_mean,
            "direction_flip_mid_mean_points": float(np.mean(direction_flip))
            if len(direction_flip)
            else None,
            "timestamp_shift_plus_one_day_mean_points": float(np.mean(shifted))
            if shifted
            else None,
            "random_matched_time_mean_points": float(np.mean(random_control))
            if len(random_control)
            else None,
            "placebo_reproduces_primary_direction": _placebo_reproduces(
                event_mean,
                [
                    float(np.mean(direction_flip)) if len(direction_flip) else None,
                    float(np.mean(shifted)) if shifted else None,
                    float(np.mean(random_control)) if len(random_control) else None,
                ],
            ),
        }
    return out


def _placebo_reproduces(primary: float | None, placebos: list[float | None]) -> bool:
    if primary is None or primary <= 0:
        return False
    return any(value is not None and value > 0.5 * primary for value in placebos)


def robustness_results(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls[
            [
                "event_id",
                "primary_control_executable_markout_points",
                "primary_control_mid_markout_points",
            ]
        ],
        on="event_id",
        how="inner",
    )
    out = {}
    for family, fam in merged.groupby("family"):
        diff_exec = (
            fam["primary_executable_markout_points"]
            - fam["primary_control_executable_markout_points"]
        )
        diff_mid = fam["primary_mid_markout_points"] - fam["primary_control_mid_markout_points"]
        non_overlap = fam[fam["non_overlap_primary"]]
        spread_cut = fam["spread"].quantile(0.9)
        low_spread = fam[fam["spread"] <= spread_cut]
        out[family] = {
            "all_events_mean_diff_points": float(diff_exec.mean()),
            "non_overlap_mean_diff_points": float(
                (
                    non_overlap["primary_executable_markout_points"]
                    - non_overlap["primary_control_executable_markout_points"]
                ).mean()
            )
            if len(non_overlap)
            else None,
            "mid_markout_mean_diff_points": float(diff_mid.mean()),
            "exclude_top_spread_decile_mean_diff_points": float(
                (
                    low_spread["primary_executable_markout_points"]
                    - low_spread["primary_control_executable_markout_points"]
                ).mean()
            )
            if len(low_spread)
            else None,
            "year_by_year_mean_diff_points": {
                str(year): float(
                    (
                        group["primary_executable_markout_points"]
                        - group["primary_control_executable_markout_points"]
                    ).mean()
                )
                for year, group in fam.groupby("year")
            },
            "session_mean_diff_points": {
                str(session): float(
                    (
                        group["primary_executable_markout_points"]
                        - group["primary_control_executable_markout_points"]
                    ).mean()
                )
                for session, group in fam.groupby("session")
            },
        }
    return out


def power_and_sensitivity(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls[["event_id", "primary_control_executable_markout_points"]],
        on="event_id",
        how="inner",
    )
    out = {}
    for family, fam in merged.groupby("family"):
        sample = fam[fam["non_overlap_primary"]]
        diff = sample["primary_executable_markout_points"].to_numpy(dtype=float) - sample[
            "primary_control_executable_markout_points"
        ].to_numpy(dtype=float)
        if len(diff) < 2:
            out[family] = {"n_events": int(len(diff)), "mde80_points": None}
            continue
        out[family] = {
            "n_events": int(len(diff)),
            "sd_pair_diff_points": float(np.std(diff, ddof=1)),
            "mde80_two_sided_alpha05_points": float(
                2.8 * np.std(diff, ddof=1) / math.sqrt(len(diff))
            ),
        }
    return out


def event_family_decisions(
    estimands: dict[str, Any],
    replication: dict[str, Any],
    placebos: dict[str, Any],
) -> dict[str, Any]:
    decisions = {}
    for family, est in estimands["families"].items():
        n_total = int(est.get("n_events", 0))
        rep = replication.get(family, {}).get("replication", {})
        rep_n = int(rep.get("n_events") or 0)
        rep_effect = rep.get("mean_event_minus_control_points")
        effect = est.get("mean_event_minus_control_points")
        event_mean = est.get("mean_event_markout_points")
        holm_p = est.get("holm_adjusted_p_value", 1.0)
        placebo_bad = placebos.get(family, {}).get("placebo_reproduces_primary_direction", False)
        if n_total < MIN_TOTAL_EVENTS or rep_n < MIN_REPLICATION_EVENTS:
            decision = "INSUFFICIENT_EVENTS"
        elif (
            effect is not None
            and event_mean is not None
            and effect > 0
            and event_mean > 0
            and holm_p <= 0.05
            and rep_effect is not None
            and rep_effect > 0
            and not placebo_bad
        ):
            decision = "CONFIRMED_READY_FOR_TEMPORAL_VALIDATION"
        elif effect is not None and (effect > 0 or (rep_effect is not None and rep_effect > 0)):
            decision = "MIXED_EXPLORATORY_SIGNAL"
        else:
            decision = "NULL_SUPPORTED"
        decisions[family] = {
            "decision": decision,
            "n_non_overlap_events": n_total,
            "replication_events": rep_n,
            "mean_event_minus_control_points": effect,
            "holm_adjusted_p_value": holm_p,
            "replication_mean_event_minus_control_points": rep_effect,
            "placebo_reproduces_primary_direction": placebo_bad,
        }
    family_values = [item["decision"] for item in decisions.values()]
    if any(value == "CONFIRMED_READY_FOR_TEMPORAL_VALIDATION" for value in family_values):
        final = "USDJPY_EVENT_ALPHA_CONFIRMED_READY_FOR_TEMPORAL_VALIDATION"
    elif any(value == "MIXED_EXPLORATORY_SIGNAL" for value in family_values):
        final = "USDJPY_EVENT_ALPHA_MIXED_EXPLORATORY_ONLY"
    elif family_values and all(value == "INSUFFICIENT_EVENTS" for value in family_values):
        final = "USDJPY_EVENT_ALPHA_INSUFFICIENT_EVENTS"
    else:
        final = "USDJPY_EVENT_ALPHA_NULL_RESULT"
    return {"family_decisions": decisions, "final_decision": final}


def overlap_audit(events: pd.DataFrame) -> dict[str, Any]:
    return {
        "total_events": int(len(events)),
        "non_overlap_primary_events": int(events["non_overlap_primary"].sum()),
        "overlapped_primary_events": int((~events["non_overlap_primary"]).sum()),
        "by_family_non_overlap": events.groupby("family")["non_overlap_primary"]
        .sum()
        .astype(int)
        .to_dict(),
    }


def ensure_no_prohibited_metrics(payload: Any) -> list[str]:
    found: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_text = str(key).lower()
                for prohibited in PROHIBITED_RESULT_KEYS:
                    if prohibited in key_text:
                        found.add(prohibited)
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    return sorted(found)


def render_prereg_docs(
    paths: GateC4Paths, inventory: dict[str, Any], prereg: dict[str, Any]
) -> None:
    families = "\n".join(
        (
            f"- `{name}`: primary {info['primary_horizon_minutes']} minutes; "
            f"{info['operational_event']}"
        )
        for name, info in inventory["families"].items()
    )
    hashes = "\n".join(f"- `{name}`: `{value}`" for name, value in inventory["file_hashes"].items())
    write_text(
        paths.docs_dir / "GATE_C4_EVENT_DEFINITION_AUDIT.md",
        f"""# Gate C.4 Event Definition Audit

Status: PREREGISTERED

Runtime universe: `{ALLOWED_PAIR}` only, enforced by the CRSF pair-scoped freeze.

## Event Families
{families}

## Definition Hashes
Config hash: `{inventory["config_hash"]}`

{hashes}

## Audit Finding
The historical YAML configs still list EURUSD and GBPUSD alongside USDJPY. Gate C.4
does not inherit that universe; it narrows runtime access to the certified CRSF
universe, `{ALLOWED_PAIR}`.
""",
    )
    core = prereg["core"]
    write_text(
        paths.docs_dir / "GATE_C4_PREREGISTRATION.md",
        f"""# Gate C.4 Preregistration

Status: PREREGISTERED BEFORE OUTCOMES

Preregistration hash: `{prereg["preregistration_hash"]}`

Repository SHA at preregistration: `{prereg["repository_head_sha_at_preregistration"]}`

## Dataset
- Pair: `{core["allowed_pair"]}`
- Development years: `{list(core["development_years"])}`
- Discovery years: `{list(core["discovery_years"])}`
- Internal temporal replication years: `{list(core["replication_years"])}`
- Freeze scope hash: `{core["freeze_scope_hash"]}`

## Primary Horizons
{json.dumps(core["primary_horizons_minutes"], indent=2, sort_keys=True)}

## Matching And Inference
Matched controls are exact on year, month, session, and direction where available,
then nearest on preregistered pre-event covariates. Primary tests use paired
permutation p-values, day-cluster bootstrap confidence intervals, and Holm
correction across the four primary family tests.

## Decision Rules
{json.dumps(core["decision_rules"], indent=2, sort_keys=True)}

## Prohibited Metrics
No full-strategy performance, sizing, portfolio, equity, or challenge-probability
metrics are calculated or reported in Gate C.4.
""",
    )


def render_analysis_docs(
    paths: GateC4Paths,
    counts: dict[str, Any],
    overlap: dict[str, Any],
    controls: dict[str, Any],
    estimands: dict[str, Any],
    replication: dict[str, Any],
    placebos: dict[str, Any],
    robustness: dict[str, Any],
    power: dict[str, Any],
    decisions: dict[str, Any],
) -> None:
    write_text(
        paths.docs_dir / "GATE_C4_CONTROL_MATCHING.md",
        f"""# Gate C.4 Control Matching

Candidate pool rows: `{controls["candidate_pool_rows"]}`

Matches with loosened exact keys: `{controls["matches_with_loosened_exact_keys"]}`

Maximum absolute standardized mean difference:
`{controls["max_abs_standardized_mean_difference"]:.6f}`

Covariate balance:

```json
{json.dumps(controls["covariate_balance"], indent=2, sort_keys=True)}
```
""",
    )
    write_text(
        paths.docs_dir / "GATE_C4_PLACEBO_TESTS.md",
        f"""# Gate C.4 Placebo Tests

```json
{json.dumps(placebos, indent=2, sort_keys=True)}
```
""",
    )
    write_text(
        paths.docs_dir / "GATE_C4_EVENT_ALPHA_RESULTS.md",
        f"""# Gate C.4 Event-Alpha Results

## Event Counts
```json
{json.dumps(counts, indent=2, sort_keys=True)}
```

## Overlap Audit
```json
{json.dumps(overlap, indent=2, sort_keys=True)}
```

## Primary Estimands
```json
{json.dumps(estimands, indent=2, sort_keys=True)}
```

## Internal Temporal Replication
```json
{json.dumps(replication, indent=2, sort_keys=True)}
```

## Robustness
```json
{json.dumps(robustness, indent=2, sort_keys=True)}
```

## Power And Sensitivity
```json
{json.dumps(power, indent=2, sort_keys=True)}
```
""",
    )
    write_text(
        paths.docs_dir / "GATE_C4_FINAL_DECISION_MEMO.md",
        f"""# Gate C.4 Final Decision Memo

Final decision: `{decisions["final_decision"]}`

## Family Decisions
```json
{json.dumps(decisions["family_decisions"], indent=2, sort_keys=True)}
```

Validation and holdout integrity: no validation or holdout years were loaded,
counted, analyzed, or reported. Gate C.4 remains development-only.
""",
    )


def run_preregistration(paths: GateC4Paths, starting_sha: str | None) -> dict[str, Any]:
    paths.results_dir.mkdir(parents=True, exist_ok=True)
    paths.docs_dir.mkdir(parents=True, exist_ok=True)
    repo = repository_state(paths.root, starting_sha)
    freeze = freeze_integrity(paths)
    inventory = event_definition_inventory(paths.root)
    prereg = preregistration_payload(paths.root, inventory, freeze, starting_sha)
    write_json(paths.results_dir / "repository_state.json", repo)
    write_json(paths.results_dir / "freeze_integrity.json", freeze)
    write_json(paths.results_dir / "event_definition_inventory.json", inventory)
    write_json(paths.results_dir / "preregistration.json", prereg)
    render_prereg_docs(paths, inventory, prereg)
    return {
        "repository_state": repo,
        "freeze_integrity": freeze,
        "event_definition_inventory": inventory,
        "preregistration": prereg,
    }


def validate_preregistration(paths: GateC4Paths) -> dict[str, Any]:
    prereg_path = paths.results_dir / "preregistration.json"
    if not prereg_path.exists():
        raise FileNotFoundError("Gate C.4 preregistration artifact is missing")
    prereg = json.loads(prereg_path.read_text())
    actual = stable_json_hash(prereg["core"])
    if actual != prereg["preregistration_hash"]:
        raise ValueError("Gate C.4 preregistration hash mismatch")
    committed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(prereg_path.relative_to(paths.root))],
        cwd=paths.root,
        text=True,
        capture_output=True,
        check=False,
    )
    if committed.returncode != 0:
        raise ValueError("Gate C.4 preregistration artifact is not tracked")
    return prereg


def run_analysis(paths: GateC4Paths) -> dict[str, Any]:
    prereg = validate_preregistration(paths)
    freeze = freeze_integrity(paths)
    if not freeze["usd_jpy_validation_passed"]:
        raise RuntimeError("USDJPY freeze validation failed")
    df = load_development_m5(paths)
    raw_events = extract_events(df)
    event_outcomes = apply_outcomes(df, raw_events)
    event_outcomes = mark_non_overlapping(event_outcomes)
    matches, control_audit = match_controls(df, event_outcomes)
    controls = add_control_outcomes(df, event_outcomes, matches)
    counts = summarize_counts(event_outcomes)
    overlap = overlap_audit(event_outcomes)
    estimands = infer_primary(event_outcomes, controls)
    replication = temporal_replication(event_outcomes, controls)
    placebos = placebo_results(df, event_outcomes, controls)
    robustness = robustness_results(event_outcomes, controls)
    power = power_and_sensitivity(event_outcomes, controls)
    decisions = event_family_decisions(estimands, replication, placebos)
    manifest = {
        "event_table_path": str(paths.row_data_dir / "usdjpy_event_table.parquet"),
        "control_matches_path": str(paths.row_data_dir / "usdjpy_control_matches.parquet"),
        "row_data_ignored_by_git": True,
        "event_count": int(len(event_outcomes)),
        "control_count": int(len(controls)),
        "event_table_hash": stable_json_hash(
            event_outcomes[["event_id", "family", "direction", "confirmation_timestamp"]]
            .astype(str)
            .to_dict("records")
        ),
        "preregistration_hash": prereg["preregistration_hash"],
    }
    split_integrity = {
        "loaded_pair": ALLOWED_PAIR,
        "loaded_years": sorted(df["year"].unique().astype(int).tolist()),
        "development_only": sorted(df["year"].unique().astype(int).tolist())
        == list(DEVELOPMENT_YEARS),
        "validation_or_holdout_loaded": False,
        "validation_or_holdout_event_counts_reported": False,
    }
    quality = {
        "no_prohibited_metric_keys_found": ensure_no_prohibited_metrics(
            {
                "estimands": estimands,
                "replication": replication,
                "placebos": placebos,
                "robustness": robustness,
                "power": power,
                "decisions": decisions,
            }
        )
        == [],
        "prohibited_metric_key_hits": ensure_no_prohibited_metrics(
            {
                "estimands": estimands,
                "replication": replication,
                "placebos": placebos,
                "robustness": robustness,
                "power": power,
                "decisions": decisions,
            }
        ),
        "final_decision": decisions["final_decision"],
    }
    paths.row_data_dir.mkdir(parents=True, exist_ok=True)
    event_outcomes.to_parquet(paths.row_data_dir / "usdjpy_event_table.parquet", index=False)
    controls.to_parquet(paths.row_data_dir / "usdjpy_control_matches.parquet", index=False)
    write_json(paths.results_dir / "event_table_manifest.json", manifest)
    write_json(paths.results_dir / "event_overlap_audit.json", overlap)
    write_json(paths.results_dir / "control_matching_audit.json", control_audit)
    write_json(paths.results_dir / "primary_estimands.json", estimands)
    write_json(paths.results_dir / "temporal_replication.json", replication)
    write_json(paths.results_dir / "placebo_results.json", placebos)
    write_json(paths.results_dir / "robustness_results.json", robustness)
    write_json(paths.results_dir / "power_and_sensitivity.json", power)
    write_json(paths.results_dir / "event_family_decisions.json", decisions)
    write_json(paths.results_dir / "split_integrity.json", split_integrity)
    write_json(paths.results_dir / "quality_gate_final.json", quality)
    render_analysis_docs(
        paths,
        counts,
        overlap,
        control_audit,
        estimands,
        replication,
        placebos,
        robustness,
        power,
        decisions,
    )
    return {
        "event_table_manifest": manifest,
        "event_counts": counts,
        "event_overlap_audit": overlap,
        "control_matching_audit": control_audit,
        "primary_estimands": estimands,
        "temporal_replication": replication,
        "placebo_results": placebos,
        "robustness_results": robustness,
        "power_and_sensitivity": power,
        "event_family_decisions": decisions,
        "split_integrity": split_integrity,
        "quality_gate_final": quality,
    }
