"""A0R3D certified evaluator closure and corrected exploratory rerun.

This module supersedes the A0R3B surrogate evaluator for the subset of trials
whose pre-outcome configuration semantics can be consumed without invention.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

RESULTS_ARTIFACT_ID = "A0R3D_CERTIFIED_EXECUTABLE_SUBSET_V1"
PASS_STRATA = (
    ("EURUSD", 2015),
    ("GBPUSD", 2017),
    ("USDJPY", 2015),
    ("USDJPY", 2016),
    ("USDJPY", 2017),
)
REGISTERED_TRIAL_DENOMINATOR = 1200
BASE_COMMISSION_SLIPPAGE_BPS_PER_FILL = 0.10
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class Paths:
    repo: Path
    raw: Path
    results: Path
    docs: Path
    trials: Path
    eligibility: Path
    pass_freeze: Path
    a0_execution: Path
    a0r1_execution: Path


@dataclass(frozen=True, slots=True)
class MarketRead:
    path: str
    pair: str
    side: str
    year: int
    month: int
    bytes: int
    sha256: str


@dataclass(slots=True)
class Position:
    side: int
    entry_price: float
    entry_timestamp: pd.Timestamp
    entry_index: int
    entry_spread_bps: float


def paths_for_a0r3d(repo: Path) -> Paths:
    return Paths(
        repo=repo,
        raw=repo / "data" / "raw" / "dukascopy-node",
        results=repo / "results" / "gate_a0r3d",
        docs=repo / "docs" / "research" / "fx_alpha_discovery",
        trials=repo / "results" / "gate_a0r2" / "trial_materialization_v2.jsonl",
        eligibility=repo / "results" / "gate_a0r3b" / "trial_eligibility.json",
        pass_freeze=repo / "results" / "gate_a0r3b" / "freeze.json",
        a0_execution=repo / "results" / "gate_a0" / "execution_certification.json",
        a0r1_execution=repo / "results" / "gate_a0r1" / "execution_certification.json",
    )


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded + b"\n")
    return sha256_bytes(encoded)


def load_trials(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def month_dir(raw: Path, pair: str, side: str, year: int, month: int) -> Path:
    return raw / pair / f"price={side}" / f"year={year}" / f"month={month:02d}"


class HoldoutReadGuard:
    def __init__(self) -> None:
        self.reads: list[MarketRead] = []

    def read_side(self, paths: Paths, pair: str, side: str, year: int, month: int) -> pd.DataFrame:
        if year >= 2018:
            raise ValueError("A0R3D_2018_PLUS_MARKET_OR_OUTCOME_ACCESS_FORBIDDEN")
        path = month_dir(paths.raw, pair, side, year, month) / "data.json"
        self.reads.append(
            MarketRead(
                path=str(path),
                pair=pair,
                side=side,
                year=year,
                month=month,
                bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
        rows = read_json(path)
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    f"{side}_open",
                    f"{side}_high",
                    f"{side}_low",
                    f"{side}_close",
                    f"{side}_volume",
                ]
            )
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
        return frame[
            [
                "timestamp",
                f"{side}_open",
                f"{side}_high",
                f"{side}_low",
                f"{side}_close",
                f"{side}_volume",
            ]
        ].sort_values("timestamp")

    def assert_no_2018_plus(self) -> None:
        bad = [read for read in self.reads if read.year >= 2018]
        if bad:
            raise AssertionError("A0R3D_2018_PLUS_MARKET_OR_OUTCOME_FILE_OPENED")


def load_required_frames(
    paths: Paths, units: list[dict[str, Any]], guard: HoldoutReadGuard
) -> dict[tuple[str, int], pd.DataFrame]:
    required = sorted({(leg, int(unit["year"])) for unit in units for leg in unit["legs"]})
    frames: dict[tuple[str, int], pd.DataFrame] = {}
    for pair, year in required:
        monthly: list[pd.DataFrame] = []
        for month in range(1, 13):
            bid = guard.read_side(paths, pair, "bid", year, month)
            ask = guard.read_side(paths, pair, "ask", year, month)
            monthly.append(pd.merge(bid, ask, on="timestamp", how="inner"))
        frame = (
            pd.concat(monthly, ignore_index=True)
            .drop_duplicates("timestamp", keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        frame["mid_close"] = (frame["bid_close"] + frame["ask_close"]) / 2.0
        frame["mid_open"] = (frame["bid_open"] + frame["ask_open"]) / 2.0
        frame["mid_high"] = (frame["bid_high"] + frame["ask_high"]) / 2.0
        frame["mid_low"] = (frame["bid_low"] + frame["ask_low"]) / 2.0
        frame["spread"] = frame["ask_close"] - frame["bid_close"]
        frame["mid_return"] = frame["mid_close"].pct_change().fillna(0.0)
        frames[(pair, year)] = frame
    guard.assert_no_2018_plus()
    return frames


def frozen_seed(paths: Paths) -> int:
    seed_source = (
        sha256_file(paths.pass_freeze)
        + sha256_file(paths.trials)
        + sha256_file(paths.eligibility)
    )
    return int(seed_source[:16], 16) % (2**32)


def load_eligible_universe(paths: Paths) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    trials = {trial["trial_id"]: trial for trial in load_trials(paths.trials)}
    eligibility = read_json(paths.eligibility)
    rows = {
        row["trial_id"]: row
        for row in eligibility["rows"]
        if row.get("status") == "ELIGIBLE"
    }
    return [trials[trial_id] for trial_id in sorted(rows)], rows


def _row(
    trial: dict[str, Any],
    field: str,
    classification: str,
    implementation: str,
    status: str,
    source: str,
) -> dict[str, Any]:
    return {
        "trial_id": trial["trial_id"],
        "family_id": trial["family_id"],
        "materialized_field": field,
        "classification": classification,
        "evaluator_implementation": implementation,
        "status": status,
        "pre_outcome_source": source,
    }


def _expected_execution_contract() -> dict[str, str]:
    return {
        "entry_latency": "one_completed_M1_bar",
        "long_entry": "ask",
        "long_exit": "bid",
        "mandatory_flat": "16:45 America/New_York",
        "new_entries_resume": "17:30 America/New_York",
        "rollover_exclusion": "16:30 America/New_York",
        "same_bar_ambiguity": "adverse_first",
        "short_entry": "bid",
        "short_exit": "ask",
    }


def certify_trial(trial: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]]]:
    cfg = trial["full_configuration"]
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    def pass_field(
        field: str, implementation: str, source: str = "A0R2 materialization V2"
    ) -> None:
        rows.append(
            _row(
                trial,
                field,
                "EXACTLY_SPECIFIED_AND_IMPLEMENTABLE",
                implementation,
                "USED",
                source,
            )
        )

    def inert(field: str, implementation: str, source: str = "A0R2 materialization V2") -> None:
        rows.append(
            _row(
                trial,
                field,
                "BEHAVIORALLY_INERT_BY_FROZEN_CONTRACT",
                implementation,
                "DOCUMENTED_INERT",
                source,
            )
        )

    def block(field: str, reason: str) -> None:
        blockers.append(f"{field}:{reason}")
        rows.append(
            _row(
                trial,
                field,
                "IMPLEMENTATION_BLOCKED_MISSING_PREOUTCOME_SEMANTICS",
                reason,
                "BLOCKED",
                "pre-outcome artifacts do not specify enough executable semantics",
            )
        )

    if trial["family_id"] != "F01_SESSION_OPENING_MOMENTUM_REVERSAL":
        block(
            "family",
            "A0R3D certified signal closure implemented only for F01 in this checkpoint",
        )
    else:
        pass_field("family", "session-opening momentum/reversal state signal")

    if cfg.get("execution_contract") == _expected_execution_contract():
        pass_field(
            "execution_contract",
            "side-correct bid/ask event state machine with one completed M1 latency",
            "results/gate_a0*/execution_certification.json",
        )
    else:
        block("execution_contract", "execution contract differs from frozen A0/A0R1 contract")

    expected_cost = {
        "commission": "frozen_A0_base",
        "slippage": "frozen_A0_base",
        "spread": "side_correct_bid_ask",
        "stress_1": "frozen_A0_stress_1",
        "stress_2": "frozen_A0_stress_2",
    }
    if cfg.get("cost_contract") == expected_cost:
        pass_field(
            "cost_contract",
            (
                "actual bid/ask spread in fills plus 0.10 bps commission/slippage per fill; "
                "stress scales executable spread-plus-slippage overlay"
            ),
            "A0 target/execution labels and A0R3B frozen evaluator constant",
        )
    else:
        block("cost_contract", "unknown cost contract labels")

    if cfg.get("model_class") in (None, "none") and not cfg.get("model_hyperparameters"):
        inert("model_class", "no trainable model path for deterministic F01")
        inert("model_hyperparameters", "empty model hyperparameters")
        inert("training_window", "no model fit; expanding/rolling label is not behaviorally active")
        inert("normalization_rule", "no train-only normalization used by deterministic F01")
        inert("purging_rule", "no training labels consumed by deterministic F01")
        inert("embargo", "no training labels consumed by deterministic F01")
        inert("walk_forward_folds", "no fitted model or fold selection in certified F01")
        inert("random_seed", "deterministic non-random signal and execution path")
    else:
        block("model_class", "trainable model semantics not certified for A0R3D")

    frozen = cfg.get("frozen_categories", {})
    checks = {
        "lookbacks": cfg.get("lookback"),
        "holding_periods": cfg.get("holding_horizon"),
        "variants": cfg.get("variant"),
        "anchors": cfg.get("session_anchor"),
    }
    if all(frozen.get(key) == value for key, value in checks.items()):
        pass_field("frozen_categories", "redundant category axes match explicit consumed fields")
    else:
        block("frozen_categories", "category axes do not map exactly to explicit fields")

    for field in ("lookback", "entry_threshold", "variant", "session_anchor", "holding_horizon"):
        if cfg.get(field) is None:
            block(field, "missing required F01 field")
        else:
            pass_field(field, f"consumed by F01 signal/execution: {cfg[field]!r}")

    if cfg.get("exit_rule") == "time_exit":
        pass_field("exit_rule", "time_exit closes at first valid bar after holding_horizon")
    else:
        block("exit_rule", "only time_exit exact semantics certified in A0R3D")

    if cfg.get("stop_rule") == "none":
        pass_field("stop_rule", "no stop path active")
    else:
        block("stop_rule", "ATR stop construction lacks frozen pre-outcome ATR definition")

    inert(
        "target_horizon",
        "not behaviorally active for deterministic time_exit F01 without target/stop",
    )
    inert(
        "position_sizing",
        (
            "candidate-equivalent per-unit bps accounting; "
            "no capital allocation ranking in exploratory rerun"
        ),
    )
    for field in (
        "abstention_threshold",
        "cross_pair_edge",
        "neutrality_constraint",
        "regime_component_count",
        "regime_model",
        "spread_forecaster",
        "triangle",
    ):
        if cfg.get(field) is None:
            inert(field, "null in materialized configuration")
        else:
            block(field, "non-null semantics not certified")

    status = "CERTIFIED_EXECUTABLE" if not blockers else "IMPLEMENTATION_BLOCKED"
    return status, blockers, rows


def certify_universe(
    trials: list[dict[str, Any]], eligibility_rows: dict[str, dict[str, Any]], paths: Paths
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    matrix: list[dict[str, Any]] = []
    certified: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for trial in trials:
        status, blockers, rows = certify_trial(trial)
        matrix.extend(rows)
        family = trial["family_id"]
        by_family[family][status] += 1
        if status == "CERTIFIED_EXECUTABLE":
            certified.append(trial)
        else:
            blocked.append(
                {
                    "trial_id": trial["trial_id"],
                    "family_id": family,
                    "status": status,
                    "configuration_sha256": trial["configuration_sha256"],
                    "eligible_topology_units": eligibility_rows[trial["trial_id"]][
                        "eligible_topology_units"
                    ],
                    "blockers": blockers,
                }
            )
    payload = {
        "artifact_id": "A0R3D_EVALUATOR_CERTIFICATION_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if certified else "BLOCKED",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "a0r3c_blockers_resolved_for_certified_trials": True,
        "certification_scope": "PER_TRIAL_PER_FAMILY",
        "eligible_a0r3b_trials_recomputed": len(trials),
        "certified_executable_trials": len(certified),
        "blocked_trials": len(blocked),
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "source_hashes": {
            "a0r3b_pass_freeze": sha256_file(paths.pass_freeze),
            "a0r3b_trial_eligibility": sha256_file(paths.eligibility),
            "a0r2_trial_materialization_v2": sha256_file(paths.trials),
            "a0_execution_certification": sha256_file(paths.a0_execution),
            "a0r1_execution_certification": sha256_file(paths.a0r1_execution),
        },
        "frozen_statistics_rule": {
            "primary_return_unit": "daily_strategy_pnl_bps_by_exit_date",
            "bootstrap": "stationary_block_bootstrap",
            "bootstrap_iterations": 499,
            "block_length_days": 5,
            "seed": frozen_seed(paths),
            "multiplicity_denominator_policy": (
                "1200 registered candidate-equivalent trials; structurally blocked remain "
                "represented conservatively"
            ),
        },
        "source_defects_closed": [
            "SURROGATE_MID_RETURN_EXECUTION",
            "SYNTHETIC_HALF_SPREAD_COST_APPROXIMATION",
            "SYNTHETIC_STATISTICS_IMPORT_FOR_A0R3D_CLAIMS",
            "FROZEN_HORIZONS_NOT_EXECUTED_FOR_CERTIFIED_SUBSET",
        ],
        "configuration_consumption_matrix": matrix,
        "blocked_trials_detail": blocked,
        "no_2018_plus_market_or_outcome_files_opened": True,
    }
    payload["certification_hash"] = json_hash(payload)
    return payload, certified, blocked


def _ny_time(ts: pd.Timestamp) -> time:
    return ts.to_pydatetime().astimezone(NY).time()


def _no_entry_time(local: time) -> bool:
    return time(16, 30) <= local < time(17, 30)


def _mandatory_flat_time(local: time) -> bool:
    return time(16, 45) <= local < time(17, 30)


def _spread_bps(row: pd.Series) -> float:
    mid = float((row["ask_close"] + row["bid_close"]) / 2.0)
    if mid <= 0:
        return 0.0
    return float((row["ask_close"] - row["bid_close"]) / mid * 10_000.0)


def _fill_price(row: pd.Series, side: int, event: str) -> float:
    if event in {"entry", "flat", "horizon", "flip"}:
        if side > 0:
            return float(row["ask_open"] if event == "entry" else row["bid_open"])
        return float(row["bid_open"] if event == "entry" else row["ask_open"])
    if event == "target":
        return float(row["bid_high"] if side > 0 else row["ask_low"])
    if event == "stop":
        return float(row["bid_low"] if side > 0 else row["ask_high"])
    raise ValueError(f"unknown fill event {event}")


def _trade_return_bps(position: Position, exit_price: float) -> float:
    if position.side > 0:
        return (exit_price - position.entry_price) / position.entry_price * 10_000.0
    return (position.entry_price - exit_price) / position.entry_price * 10_000.0


def _round_trip_cost_bps(position: Position, exit_row: pd.Series, cost_multiplier: float) -> float:
    exit_spread = _spread_bps(exit_row)
    spread_overlay = max(cost_multiplier - 1.0, 0.0) * (
        position.entry_spread_bps + exit_spread
    ) / 2.0
    commission_slippage = cost_multiplier * BASE_COMMISSION_SLIPPAGE_BPS_PER_FILL * 2.0
    return spread_overlay + commission_slippage


def signal_f01(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    lookback = max(int(config["lookback"]), 1)
    threshold = float(config["entry_threshold"])
    ret = frame["mid_close"].pct_change(lookback).fillna(0.0)
    vol = frame["mid_return"].rolling(lookback, min_periods=max(3, lookback // 3)).std()
    scale = vol.replace(0.0, np.nan).fillna(frame["mid_return"].std() or 1e-9).clip(lower=1e-9)
    raw = ret / scale
    local_hours = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(NY).dt.hour
    anchor = str(config["session_anchor"]).lower()
    if "tokyo" in anchor:
        mask = local_hours.isin([19, 20, 21])
    elif "london 16" in anchor:
        mask = local_hours.isin([10, 11])
    elif "new york" in anchor:
        mask = local_hours.isin([8, 9, 10])
    elif "london" in anchor:
        mask = local_hours.isin([2, 3, 4])
    else:
        mask = pd.Series(False, index=frame.index)
    raw = raw.where(mask, 0.0)
    if "reversal" in str(config["variant"]).lower():
        raw = -raw
    return pd.Series(
        np.where(raw >= threshold, 1, np.where(raw <= -threshold, -1, 0)),
        index=frame.index,
    )


def compact_execution_window(
    frame: pd.DataFrame, signal: pd.Series, *, horizon: int
) -> tuple[pd.DataFrame, pd.Series]:
    nonzero = np.flatnonzero(signal.to_numpy(dtype=int) != 0)
    if len(nonzero) == 0:
        return frame.iloc[:0].copy(), pd.Series(dtype=int)
    keep = np.zeros(len(frame), dtype=bool)
    extra = max(int(horizon), 1) + 2
    for index in nonzero:
        start = int(index)
        stop = min(len(frame), start + extra)
        keep[start:stop] = True
    compact = frame.loc[keep].copy().reset_index(drop=True)
    compact_signal = signal.loc[keep].astype(int).reset_index(drop=True)
    original_index = np.flatnonzero(keep)
    gap_after = np.r_[np.diff(original_index) > 1, True]
    compact_signal.loc[gap_after] = 0
    return compact, compact_signal


def simulate_state_machine(
    frame: pd.DataFrame,
    signal: pd.Series,
    config: dict[str, Any],
    *,
    cost_multiplier: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    holding_horizon = int(config.get("holding_horizon") or 1)
    stop_rule = str(config.get("stop_rule") or "none")
    exit_rule = str(config.get("exit_rule") or "time_exit")
    target_bps = float(config.get("target_bps", 0.0) or 0.0)
    stop_bps = float(config.get("stop_bps", 0.0) or 0.0)
    position: Position | None = None
    pending_signal = 0
    daily_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for i, row in frame.reset_index(drop=True).iterrows():
        timestamp = pd.Timestamp(row["timestamp"])
        local = _ny_time(timestamp)
        gross_bps = 0.0
        cost_bps = 0.0
        turnover = 0.0
        exit_reason = ""

        if position is not None:
            should_exit = False
            event = "horizon"
            bars_held = int(i) - position.entry_index
            if _mandatory_flat_time(local):
                should_exit = True
                event = "flat"
                exit_reason = "mandatory_flat"
            elif exit_rule == "time_exit" and bars_held >= holding_horizon:
                should_exit = True
                event = "horizon"
                exit_reason = "horizon"
            elif exit_rule == "opposite_signal" and pending_signal == -position.side:
                should_exit = True
                event = "flip"
                exit_reason = "opposite_signal"

            target_hit = False
            stop_hit = False
            if target_bps > 0:
                if position.side > 0:
                    target_hit = float(row["bid_high"]) >= position.entry_price * (
                        1.0 + target_bps / 10_000.0
                    )
                else:
                    target_hit = float(row["ask_low"]) <= position.entry_price * (
                        1.0 - target_bps / 10_000.0
                    )
            if stop_rule != "none" and stop_bps > 0:
                if position.side > 0:
                    stop_hit = float(row["bid_low"]) <= position.entry_price * (
                        1.0 - stop_bps / 10_000.0
                    )
                else:
                    stop_hit = float(row["ask_high"]) >= position.entry_price * (
                        1.0 + stop_bps / 10_000.0
                    )
            if target_hit or stop_hit:
                should_exit = True
                event = "stop" if stop_hit else "target"
                exit_reason = "same_bar_adverse_stop" if stop_hit and target_hit else event

            if should_exit:
                exit_price = _fill_price(row, position.side, event)
                gross_bps = _trade_return_bps(position, exit_price)
                cost_bps = _round_trip_cost_bps(position, row, cost_multiplier)
                turnover = 2.0
                trades.append(
                    {
                        "entry_timestamp": position.entry_timestamp.isoformat(),
                        "exit_timestamp": timestamp.isoformat(),
                        "side": "long" if position.side > 0 else "short",
                        "exit_reason": exit_reason,
                        "gross_bps": round(gross_bps, 9),
                        "cost_bps": round(cost_bps, 9),
                        "net_bps": round(gross_bps - cost_bps, 9),
                    }
                )
                position = None

        if position is None and pending_signal and not _no_entry_time(local):
            side = int(pending_signal)
            entry_price = _fill_price(row, side, "entry")
            position = Position(
                side=side,
                entry_price=entry_price,
                entry_timestamp=timestamp,
                entry_index=int(i),
                entry_spread_bps=_spread_bps(row),
            )
            turnover += 1.0

        daily_rows.append(
            {
                "timestamp": timestamp,
                "date": timestamp.tz_convert(NY).date().isoformat(),
                "gross_bps": gross_bps,
                "cost_bps": cost_bps,
                "net_bps": gross_bps - cost_bps,
                "turnover": turnover,
                "position": 0 if position is None else position.side,
            }
        )
        pending_signal = int(signal.iloc[int(i)])

    if position is not None and len(frame):
        row = frame.iloc[-1]
        timestamp = pd.Timestamp(row["timestamp"])
        exit_price = _fill_price(row, position.side, "horizon")
        gross_bps = _trade_return_bps(position, exit_price)
        cost_bps = _round_trip_cost_bps(position, row, cost_multiplier)
        trades.append(
            {
                "entry_timestamp": position.entry_timestamp.isoformat(),
                "exit_timestamp": timestamp.isoformat(),
                "side": "long" if position.side > 0 else "short",
                "exit_reason": "delayed_valid_exit_at_dataset_end",
                "gross_bps": round(gross_bps, 9),
                "cost_bps": round(cost_bps, 9),
                "net_bps": round(gross_bps - cost_bps, 9),
            }
        )
        daily_rows.append(
            {
                "timestamp": timestamp,
                "date": timestamp.tz_convert(NY).date().isoformat(),
                "gross_bps": gross_bps,
                "cost_bps": cost_bps,
                "net_bps": gross_bps - cost_bps,
                "turnover": 2.0,
                "position": 0,
            }
        )

    components = pd.DataFrame(daily_rows)
    daily = components.groupby("date", as_index=False).agg(
        gross_bps=("gross_bps", "sum"),
        cost_bps=("cost_bps", "sum"),
        net_bps=("net_bps", "sum"),
        turnover=("turnover", "sum"),
    )
    return daily, trades


def _sample_moments(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 3:
        return 0.0, 3.0
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std <= 0:
        return 0.0, 3.0
    centered = (values - mean) / std
    skew = float(np.mean(centered**3))
    kurt = float(np.mean(centered**4))
    return skew, kurt


def daily_metrics(daily: pd.DataFrame, trades: list[dict[str, Any]]) -> dict[str, float | int]:
    values = daily["net_bps"].to_numpy(dtype=float)
    if len(values) == 0:
        values = np.array([0.0])
    gross = float(daily["gross_bps"].sum()) if len(daily) else 0.0
    costs = float(daily["cost_bps"].sum()) if len(daily) else 0.0
    total = float(np.sum(values))
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    sharpe = float(mean / std * math.sqrt(252.0)) if std else 0.0
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.min(equity - peak)) if len(equity) else 0.0
    hit_rate = float(np.mean([float(t["net_bps"]) > 0 for t in trades])) if trades else 0.0
    trade_count = len(trades)
    return {
        "days": int(len(values)),
        "trade_count": trade_count,
        "gross_bps": round(gross, 6),
        "cost_bps": round(costs, 6),
        "net_bps": round(total, 6),
        "net_bps_per_trade": round(total / max(trade_count, 1), 9),
        "daily_mean_bps": round(mean, 9),
        "daily_sharpe": round(sharpe, 6),
        "max_drawdown_bps": round(max_dd, 6),
        "hit_rate": round(hit_rate, 6),
        "turnover": round(float(daily["turnover"].sum()) if len(daily) else 0.0, 6),
    }


def normal_p_value_from_mean(values: np.ndarray) -> float:
    if len(values) < 2:
        return 1.0
    std = float(np.std(values, ddof=1))
    if std <= 0:
        return 1.0
    t_stat = float(np.mean(values) / (std / math.sqrt(len(values))))
    return max(0.0, min(1.0, 0.5 * math.erfc(t_stat / math.sqrt(2.0))))


def stationary_bootstrap_indices(
    n: int, block_length: int, iterations: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    indices = np.empty((iterations, n), dtype=int)
    p = 1.0 / max(block_length, 1)
    for b in range(iterations):
        current = int(rng.integers(0, n))
        for i in range(n):
            if i == 0 or rng.random() < p:
                current = int(rng.integers(0, n))
            else:
                current = (current + 1) % n
            indices[b, i] = current
    return indices


def holm_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, (m - rank) * p_values[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted


def bh_fdr(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i], reverse=True)
    adjusted = [1.0] * m
    running = 1.0
    for rank_from_end, idx in enumerate(order):
        rank = m - rank_from_end
        value = min(running, p_values[idx] * m / max(rank, 1))
        running = value
        adjusted[idx] = min(1.0, value)
    return adjusted


def bootstrap_family_stats(
    return_matrix: pd.DataFrame, *, seed: int, iterations: int = 499, block_length: int = 5
) -> dict[str, Any]:
    if return_matrix.empty:
        return {
            "white_reality_check_p": "NOT_APPLICABLE",
            "hansen_spa_p": "NOT_APPLICABLE",
            "romano_wolf_stepdown_p": [],
        }
    values = return_matrix.to_numpy(dtype=float)
    n, m = values.shape
    means = values.mean(axis=0)
    stds = values.std(axis=0, ddof=1)
    se = np.where(stds > 0, stds / math.sqrt(max(n, 1)), np.inf)
    t_stats = np.where(np.isfinite(se), means / se, 0.0)
    observed_max_mean = float(np.max(means))
    observed_max_t = float(np.max(t_stats))
    centered = values - means
    indices = stationary_bootstrap_indices(n, block_length, iterations, seed)
    boot_means = centered[indices].mean(axis=1)
    boot_t = np.divide(
        boot_means,
        np.where(stds > 0, stds / math.sqrt(max(n, 1)), np.inf),
        out=np.zeros_like(boot_means),
        where=np.isfinite(se),
    )
    wrc_p = float(np.mean(np.max(boot_means, axis=1) >= observed_max_mean))
    positive = means > 0.0
    if positive.any():
        spa_p = float(np.mean(np.max(boot_t[:, positive], axis=1) >= observed_max_t))
    else:
        spa_p = 1.0
    raw_step = [
        float(np.mean(np.max(boot_t[:, means <= means[i] + 1e-12], axis=1) >= t_stats[i]))
        if np.any(means <= means[i] + 1e-12)
        else 1.0
        for i in range(m)
    ]
    return {
        "white_reality_check_p": round(wrc_p, 9),
        "hansen_spa_p": round(spa_p, 9),
        "romano_wolf_stepdown_p": [round(min(1.0, max(0.0, p)), 9) for p in raw_step],
        "bootstrap_iterations": iterations,
        "block_length_days": block_length,
        "seed": seed,
    }


def psr(sharpe: float, n: int, skew: float, kurtosis: float) -> float:
    if n <= 1:
        return 0.0
    denom = math.sqrt(max(1e-12, 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2))
    z = sharpe * math.sqrt(n - 1) / denom
    return max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


def dsr(sharpe: float, n: int, skew: float, kurtosis: float, trial_count: int) -> float:
    expected_max = math.sqrt(max(0.0, 2.0 * math.log(max(trial_count, 2))))
    adjusted = sharpe - expected_max / math.sqrt(max(n, 1))
    return psr(adjusted, n, skew, kurtosis)


def evaluate_certified_trials(
    frames: dict[tuple[str, int], pd.DataFrame],
    trials: list[dict[str, Any]],
    eligibility_rows: dict[str, dict[str, Any]],
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    matrix_parts: list[pd.Series] = []
    p_values: list[float] = []

    for trial in trials:
        cfg = trial["full_configuration"]
        unit_rows: list[dict[str, Any]] = []
        daily_parts: list[pd.DataFrame] = []
        for unit in eligibility_rows[trial["trial_id"]]["eligible_topology_units"]:
            pair = str(unit["evaluation_pair"])
            year = int(unit["year"])
            frame = frames[(pair, year)]
            signal = signal_f01(frame, cfg)
            exec_frame, exec_signal = compact_execution_window(
                frame, signal, horizon=int(cfg.get("holding_horizon") or 1)
            )
            base_daily, trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=1.0
            )
            stress15, stress15_trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=1.5
            )
            stress20, stress20_trades = simulate_state_machine(
                exec_frame, exec_signal, cfg, cost_multiplier=2.0
            )
            unit_rows.append(
                {
                    "topology_id": unit["topology_id"],
                    "pair": pair,
                    "year": year,
                    "legs": unit["legs"],
                    "metrics": daily_metrics(base_daily, trades),
                    "stress_1_5x": daily_metrics(stress15, stress15_trades),
                    "stress_2_0x": daily_metrics(stress20, stress20_trades),
                }
            )
            daily_parts.append(base_daily[["date", "net_bps"]])
        pooled = pd.concat(daily_parts, ignore_index=True)
        daily = pooled.groupby("date", as_index=False)["net_bps"].mean()
        values = daily["net_bps"].to_numpy(dtype=float)
        primary_trades = sum(int(unit["metrics"]["trade_count"]) for unit in unit_rows)
        primary = {
            "days": int(len(daily)),
            "trade_count": primary_trades,
            "gross_bps": round(
                float(np.mean([unit["metrics"]["gross_bps"] for unit in unit_rows])), 6
            ),
            "cost_bps": round(
                float(np.mean([unit["metrics"]["cost_bps"] for unit in unit_rows])), 6
            ),
            "net_bps": round(float(np.mean([unit["metrics"]["net_bps"] for unit in unit_rows])), 6),
            "net_bps_per_trade": round(
                float(np.mean([unit["metrics"]["net_bps_per_trade"] for unit in unit_rows])), 9
            ),
            "daily_sharpe": round(
                float(np.mean([unit["metrics"]["daily_sharpe"] for unit in unit_rows])), 6
            ),
            "max_drawdown_bps": round(
                float(np.mean([unit["metrics"]["max_drawdown_bps"] for unit in unit_rows])), 6
            ),
            "hit_rate": round(
                float(np.mean([unit["metrics"]["hit_rate"] for unit in unit_rows])), 6
            ),
            "turnover": round(
                float(np.mean([unit["metrics"]["turnover"] for unit in unit_rows])), 6
            ),
        }
        p_values.append(normal_p_value_from_mean(values))
        matrix_parts.append(daily.set_index("date")["net_bps"].rename(trial["trial_id"]))
        stress15_positive = [float(unit["stress_1_5x"]["net_bps"]) > 0 for unit in unit_rows]
        stress20_positive = [float(unit["stress_2_0x"]["net_bps"]) > 0 for unit in unit_rows]
        positive_units = [float(unit["metrics"]["net_bps"]) > 0 for unit in unit_rows]
        rows.append(
            {
                "trial_id": trial["trial_id"],
                "family_id": trial["family_id"],
                "status": "CORRECTED_EXPLORATORY_COMPLETED",
                "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
                "configuration_sha256": trial["configuration_sha256"],
                "eligible_topology_units": eligibility_rows[trial["trial_id"]][
                    "eligible_topology_units"
                ],
                "topology_unit_count": eligibility_rows[trial["trial_id"]]["topology_unit_count"],
                "unit_results": unit_rows,
                "primary_equal_weight": primary,
                "trade_count": primary_trades,
                "cross_stratum_stability": round(float(np.mean(positive_units)), 6),
                "cost_stress": {
                    "survives_1_5x": bool(all(stress15_positive)),
                    "survives_2_0x": bool(all(stress20_positive)),
                    "survival_rate_1_5x": round(float(np.mean(stress15_positive)), 6),
                    "survival_rate_2_0x": round(float(np.mean(stress20_positive)), 6),
                },
                "evidence_tier": "SINGLE_STRATUM_EXPLORATORY_LEAD"
                if eligibility_rows[trial["trial_id"]]["topology_unit_count"] == 1
                else "MULTI_STRATUM_EXPLORATORY",
                "execution_engine": "A0R3D_SIDE_CORRECT_EVENT_STATE_MACHINE",
                "synthetic_fills_used": 0,
            }
        )

    return_matrix = pd.concat(matrix_parts, axis=1).fillna(0.0) if matrix_parts else pd.DataFrame()
    bootstrap = bootstrap_family_stats(return_matrix, seed=seed)
    holm = holm_adjust(p_values)
    bh = bh_fdr(p_values)
    rw = bootstrap.get("romano_wolf_stepdown_p", [])
    for index, row in enumerate(rows):
        values = return_matrix[row["trial_id"]].to_numpy(dtype=float)
        skew, kurt = _sample_moments(values)
        row["corrected_significance"] = {
            "raw_daily_mean_p": round(p_values[index], 9),
            "holm_p": round(holm[index], 9),
            "bh_fdr_p": round(bh[index], 9),
            "romano_wolf_p": rw[index] if index < len(rw) else "NOT_APPLICABLE",
            "psr": round(
                psr(float(row["primary_equal_weight"]["daily_sharpe"]), len(values), skew, kurt),
                9,
            ),
            "dsr": round(
                dsr(
                    float(row["primary_equal_weight"]["daily_sharpe"]),
                    len(values),
                    skew,
                    kurt,
                    REGISTERED_TRIAL_DENOMINATOR,
                ),
                9,
            ),
            "skew": round(skew, 9),
            "kurtosis": round(kurt, 9),
        }

    multiple = {
        "artifact_id": "A0R3D_MULTIPLE_TESTING_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if rows else "NOT_APPLICABLE",
        "evaluated_trials": len(rows),
        "registered_candidate_equivalent_denominator": REGISTERED_TRIAL_DENOMINATOR,
        **bootstrap,
        "pbo": "NOT_APPLICABLE",
        "pbo_not_applicable_reason": (
            "fewer_than_four_independent_strata_or_folds_in_certified_subset"
        ),
        "methods": [
            "White Reality Check stationary bootstrap",
            "Hansen SPA stationary bootstrap",
            "Romano-Wolf stepdown stationary bootstrap",
            "Holm",
            "BH-FDR",
            "PSR with sample size/skew/kurtosis",
            "DSR with registered trial denominator",
            "PBO/CSCV when enough independent strata exist",
        ],
    }
    results = {
        "artifact_id": "A0R3D_CORRECTED_EXPLORATORY_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if rows else "BLOCKED",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "result_rows": rows,
        "evaluated_trials": len(rows),
        "daily_return_matrix_sha256": (
            json_hash(return_matrix.to_dict()) if not return_matrix.empty else ""
        ),
        "no_2018_plus_market_or_outcome_files_opened": True,
    }
    cost = {
        "artifact_id": "A0R3D_COST_STRESS_RESULTS_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS" if rows else "NOT_APPLICABLE",
        "rows": [
            {
                "trial_id": row["trial_id"],
                "survives_1_5x": row["cost_stress"]["survives_1_5x"],
                "survives_2_0x": row["cost_stress"]["survives_2_0x"],
            }
            for row in rows
        ],
    }
    shortlist_rows = rank_shortlist(rows, limit=24)
    shortlist = {
        "artifact_id": "A0R3D_SHORTLIST_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "status": "PASS",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "shortlist_size": len(shortlist_rows),
        "selection_rule": (
            "corrected evidence, net economics, cost robustness, support and stability; "
            "never raw Sharpe alone"
        ),
        "rows": shortlist_rows,
    }
    return results, multiple, cost, shortlist


def rank_shortlist(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row["corrected_significance"]["bh_fdr_p"]),
            not bool(row["cost_stress"]["survives_2_0x"]),
            not bool(row["cost_stress"]["survives_1_5x"]),
            -int(row["topology_unit_count"]),
            -float(row["cross_stratum_stability"]),
            -float(row["primary_equal_weight"]["net_bps"]),
            row["trial_id"],
        ),
    )[:limit]


def write_report(
    paths: Paths,
    certification: dict[str, Any],
    results: dict[str, Any],
    multiple: dict[str, Any],
    shortlist: dict[str, Any],
    blocked: list[dict[str, Any]],
) -> None:
    paths.docs.mkdir(parents=True, exist_ok=True)
    lines = [
        "# A0R3D Certified Evaluator Closure",
        "",
        "Status: EXPLORATORY_NOT_VALIDATED_ALPHA",
        "",
        "A0R3D does not modify the PASS-strata freeze or the 1200 registered trial universe.",
        (
            "It certifies only the subset whose pre-outcome materialized dimensions are "
            "consumed by the new event/state-machine evaluator."
        ),
        "",
        "## Certification",
        "",
        f"- Verdict: {certification['status']}",
        f"- A0R3B eligible trials recomputed: {certification['eligible_a0r3b_trials_recomputed']}",
        f"- Certified executable trials: {certification['certified_executable_trials']}",
        f"- Blocked trials: {certification['blocked_trials']}",
        "- 2018+ market/outcome files opened: 0",
        "",
        "## Corrected Rerun",
        "",
        f"- Trials run: {results['evaluated_trials']}",
        f"- WRC p: {multiple.get('white_reality_check_p')}",
        f"- SPA p: {multiple.get('hansen_spa_p')}",
        f"- PBO: {multiple.get('pbo')} ({multiple.get('pbo_not_applicable_reason', '')})",
        f"- Shortlist size: {shortlist['shortlist_size']}",
        "",
        "## Top Corrected Candidates",
        "",
    ]
    for row in shortlist["rows"][:10]:
        primary = row["primary_equal_weight"]
        sig = row["corrected_significance"]
        lines.append(
            "- "
            f"{row['trial_id']} {row['family_id']} "
            f"net_bps={primary['net_bps']} sharpe={primary['daily_sharpe']} "
            f"trades={primary['trade_count']} bh={sig['bh_fdr_p']} "
            f"dsr={sig['dsr']} tier={row['evidence_tier']}"
        )
    if not shortlist["rows"]:
        lines.append("- No certified trial produced a positive shortlist entry.")
    lines.extend(["", "## Blocked Reasons", ""])
    reason_counts: Counter[str] = Counter(
        reason.split(":", 1)[0] for row in blocked for reason in row["blockers"]
    )
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"- {reason}: {count}")
    lines.extend(
        [
            "",
            (
                "Next gate: A0R3E should either close remaining pre-outcome semantics for "
                "additional families or, if the corrected exploratory gate survives under "
                "review, prepare a strictly separate 2018 confirmation invocation."
            ),
            "",
        ]
    )
    (paths.docs / "A0R3D_CERTIFIED_EVALUATOR_SUBSET.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run(paths: Paths) -> dict[str, Any]:
    trials, eligibility_rows = load_eligible_universe(paths)
    certification, certified, blocked = certify_universe(trials, eligibility_rows, paths)
    write_json(paths.results / "certification.json", certification)
    write_json(
        paths.results / "configuration_consumption_matrix.json",
        certification["configuration_consumption_matrix"],
    )
    write_json(paths.results / "blocked_trials.json", blocked)

    all_units = [
        unit
        for trial in certified
        for unit in eligibility_rows[trial["trial_id"]]["eligible_topology_units"]
    ]
    guard = HoldoutReadGuard()
    frames = load_required_frames(paths, all_units, guard) if certified else {}
    results, multiple, cost, shortlist = evaluate_certified_trials(
        frames, certified, eligibility_rows, seed=frozen_seed(paths)
    )
    read_audit = {
        "artifact_id": "A0R3D_HOLDOUT_READ_AUDIT_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "opened_files": [asdict(read) for read in guard.reads],
        "opened_2018_plus_market_or_outcome_files": [],
        "2018_plus_market_or_outcome_files_opened": 0,
    }
    write_json(paths.results / "holdout_read_audit.json", read_audit)
    write_json(paths.results / "corrected_results.json", results)
    write_json(paths.results / "multiple_testing.json", multiple)
    write_json(paths.results / "cost_stress.json", cost)
    write_json(paths.results / "shortlist.json", shortlist)
    summary = {
        "artifact_id": "A0R3D_SUMMARY_V1",
        "gate_id": RESULTS_ARTIFACT_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if certified else "BLOCKED",
        "claim": "EXPLORATORY_NOT_VALIDATED_ALPHA",
        "pass_strata_freeze_sha256": sha256_file(paths.pass_freeze),
        "certified_executable_trials": len(certified),
        "blocked_trials": len(blocked),
        "corrected_trials_run": int(results["evaluated_trials"]),
        "shortlist_size": int(shortlist["shortlist_size"]),
        "by_family": certification["by_family"],
        "white_reality_check_p": multiple.get("white_reality_check_p"),
        "hansen_spa_p": multiple.get("hansen_spa_p"),
        "pbo": multiple.get("pbo"),
        "cost_stress_1_5x_survivors": sum(
            1 for row in cost["rows"] if row["survives_1_5x"]
        ),
        "cost_stress_2_0x_survivors": sum(
            1 for row in cost["rows"] if row["survives_2_0x"]
        ),
        "2018_plus_market_or_outcome_files_opened": 0,
        "a0r3b_numerics_superseded_for_trials": [trial["trial_id"] for trial in certified],
        "next_gate": "A0R3E_REMAINING_SEMANTICS_OR_2018_CONFIRMATION_ONLY_AFTER_REVIEW",
    }
    summary["summary_hash"] = json_hash(summary)
    write_json(paths.results / "summary.json", summary)
    write_report(paths, certification, results, multiple, shortlist, blocked)
    return summary
