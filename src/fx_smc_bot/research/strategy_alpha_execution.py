"""Gate P0-R execution coverage and funnel helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from fx_smc_bot.alpha.intraday.factory import create_runtime, resolve_runtime_config
from fx_smc_bot.alpha.intraday.runtime import (
    CausalBarContext,
    OrderAcceptedEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderIntent,
    PositionClosedEvent,
    StatefulStrategyRuntime,
)
from fx_smc_bot.backtesting.intraday_engine import IntradayExecutionPolicy
from fx_smc_bot.config import SessionConfig, StructureConfig, Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    LiquidityLevelType,
    SessionName,
    SessionWindow,
    StructureSnapshot,
)
from fx_smc_bot.research.strategy_alpha import HISTORICAL_WINDOWS, CandidateSpec
from fx_smc_bot.research.strategy_alpha_data import (
    ALLOWED_END,
    ALLOWED_START,
    AUTHORIZED_STRATEGY_INSTRUMENTS,
    SESSION_CONTRACTS,
    WARMUP_M5_BARS,
    session_bounds_utc,
)
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.structure.liquidity import detect_session_levels, detect_sweeps


@dataclass(frozen=True, slots=True)
class CandidateCoverageRecord:
    candidate_id: str
    instrument: str
    window: str
    required_date_range: tuple[str, str]
    required_resolution: str
    required_bid_ask_fields: list[str]
    manifest_path: str | None
    provider: str | None
    certification_status: str
    available_partitions: int
    missing_partitions: int
    zero_row_partitions: int
    duplicate_timestamps: str
    missing_intervals: str
    spread_availability: str
    timezone_dst_certification: str
    tick_or_m1_provenance: str
    coverage_classification: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CandidateFunnel:
    candidate_id: str
    eligible_market_bars: int
    candidate_detection_opportunities: int
    raw_signals: int
    causally_valid_signals: int
    orders_created: int
    orders_eligible_for_execution: int
    orders_filled: int
    positions_opened: int
    positions_closed: int
    trades_accepted_into_aggregate_sample: int
    rejection_counts: dict[str, int]
    root_causes: list[str]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


REJECTION_REASONS = [
    "missing_data",
    "uncertified_partition",
    "outside_session",
    "invalid_signal",
    "expired_order",
    "unreachable_limit",
    "position_overlap",
    "missing_spread",
    "missing_cost_inputs",
    "missing_exit",
    "runtime_error",
]


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    candidate_id: str
    instrument: str
    session: str
    family: str
    config_hash: str
    runtime: StatefulStrategyRuntime


class AmendedSessionRuntime:
    """Restrict a frozen runtime to one amended local session and trading day."""

    def __init__(self, runtime: StatefulStrategyRuntime) -> None:
        self._runtime = runtime
        self.family = runtime.family
        self.pair = runtime.pair
        self.session = runtime.session
        self._active_local_day: date | None = None

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
        local_day = _session_local_day(ctx.timestamp, self.session)
        if local_day != self._active_local_day:
            self._runtime.reset()
            self._active_local_day = local_day
        return self._runtime.on_bar(ctx)

    def on_order_accepted(self, event: OrderAcceptedEvent) -> None:
        self._runtime.on_order_accepted(event)

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        self._runtime.on_order_filled(event)

    def on_order_cancelled(self, event: OrderCancelledEvent) -> None:
        self._runtime.on_order_cancelled(event)

    def on_position_closed(self, event: PositionClosedEvent) -> None:
        self._runtime.on_position_closed(event)

    def snapshot_state(self) -> dict:
        return self._runtime.snapshot_state()

    def reset(self) -> None:
        self._runtime.reset()
        self._active_local_day = None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _session_local_day(value: datetime, session: str) -> date:
    try:
        zone = ZoneInfo(SESSION_CONTRACTS[session]["timezone"])
    except KeyError as exc:
        raise ValueError(f"unknown amended session: {session}") from exc
    return _as_utc(value).astimezone(zone).date()


def amended_session_cutoff(value: datetime, session: str) -> datetime:
    """Resolve the originating session's 11:00 local cutoff in UTC."""
    _, cutoff = session_bounds_utc(_session_local_day(value, session), session)
    return cutoff if value.tzinfo is not None else cutoff.replace(tzinfo=None)


def amended_fx_week_close(value: datetime) -> datetime:
    """Resolve the current permitted FX week's Friday 17:00 New York close."""
    local = _as_utc(value).astimezone(ZoneInfo("America/New_York"))
    close_day = local.date() + timedelta(days=(4 - local.weekday()) % 7)
    close = datetime.combine(
        close_day,
        time(17, 0),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)
    return close if value.tzinfo is not None else close.replace(tzinfo=None)


def is_amended_session_bar(value: datetime, session: str) -> bool:
    local_day = _session_local_day(value, session)
    start, end = session_bounds_utc(local_day, session)
    return start <= _as_utc(value) < end


def amended_session_windows(series: BarSeries) -> list[SessionWindow]:
    """Track both named sessions with IANA DST conversion."""
    windows: list[SessionWindow] = []
    for session, contract in SESSION_CONTRACTS.items():
        zone = ZoneInfo(contract["timezone"])
        start_h, start_m = (int(item) for item in contract["start_local"].split(":"))
        end_h, end_m = (int(item) for item in contract["end_local"].split(":"))
        start_local = time(start_h, start_m)
        end_local = time(end_h, end_m)
        grouped: dict[date, dict[str, Any]] = {}
        for idx, stamp in enumerate(series.timestamps):
            utc_value = stamp.astype("datetime64[us]").astype(datetime).replace(tzinfo=UTC)
            local = utc_value.astimezone(zone)
            if not start_local <= local.time() < end_local:
                continue
            naive_utc = utc_value.replace(tzinfo=None)
            row = grouped.setdefault(
                local.date(),
                {
                    "date": naive_utc,
                    "open": naive_utc,
                    "close": naive_utc,
                    "high": float(series.high[idx]),
                    "low": float(series.low[idx]),
                    "high_idx": idx,
                    "low_idx": idx,
                },
            )
            row["close"] = naive_utc
            if float(series.high[idx]) > row["high"]:
                row["high"] = float(series.high[idx])
                row["high_idx"] = idx
            if float(series.low[idx]) < row["low"]:
                row["low"] = float(series.low[idx])
                row["low_idx"] = idx
        for _, row in sorted(grouped.items()):
            windows.append(SessionWindow(
                session_name=SessionName(session),
                date=row["date"],
                open_time=row["open"],
                close_time=row["close"],
                high=row["high"],
                low=row["low"],
                high_index=row["high_idx"],
                low_index=row["low_idx"],
            ))
    return sorted(windows, key=lambda item: (item.open_time, item.session_name.value))


def build_amended_structure_snapshot(
    series: BarSeries,
    structure_cfg: StructureConfig,
    session_cfg: SessionConfig,
) -> StructureSnapshot:
    """Build the frozen structure snapshot with amended named-session levels."""
    snapshot = build_structure_snapshot(series, structure_cfg, session_cfg)
    windows = amended_session_windows(series)
    non_session = [
        item
        for item in snapshot.liquidity_levels
        if item.level_type
        not in {LiquidityLevelType.SESSION_HIGH, LiquidityLevelType.SESSION_LOW}
    ]
    snapshot.liquidity_levels = detect_sweeps(
        non_session + detect_session_levels(windows, len(series) - 1),
        series.high,
        series.low,
        series.close,
        series.timestamps,
    )
    snapshot.session_windows = windows
    return snapshot


def amended_execution_policy() -> IntradayExecutionPolicy:
    return IntradayExecutionPolicy(
        warmup_bars=WARMUP_M5_BARS,
        close_at_session_cutoff=True,
        close_at_fx_week_end=True,
        close_at_final_bar=True,
        single_position_per_pair=True,
        apply_swap=False,
        structure_lookback_bars=WARMUP_M5_BARS,
        session_cutoff_resolver=amended_session_cutoff,
        fx_week_close_resolver=amended_fx_week_close,
        runtime_bar_filter=is_amended_session_bar,
        snapshot_builder=build_amended_structure_snapshot,
    )


def build_candidate_runtime_bindings(
    repo: Path,
    candidate: CandidateSpec,
) -> list[RuntimeBinding]:
    bindings: list[RuntimeBinding] = []
    config_path = repo / candidate.config_path
    for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS):
        pair = TradingPair(instrument)
        for session in candidate.sessions:
            resolved = resolve_runtime_config(
                candidate.strategy_family,
                pair,
                session,
                config_path,
            )
            if not resolved.config:
                raise ValueError(
                    f"empty frozen runtime config for {candidate.candidate_id}/{session}"
                )
            runtime = AmendedSessionRuntime(create_runtime(
                candidate.strategy_family,
                pair,
                session,
                resolved.config,
            ))
            bindings.append(RuntimeBinding(
                candidate_id=candidate.candidate_id,
                instrument=instrument,
                session=session,
                family=candidate.strategy_family,
                config_hash=resolved.config_hash,
                runtime=runtime,
            ))
    return bindings


def _month_sequence(start: date, end: date) -> Sequence[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def load_certified_m5_window(
    repo: Path,
    instrument: str,
    start: date,
    end: date,
) -> BidAskBarSeries:
    """Load only explicit certified A1A M5 paths within the permitted boundary."""
    import pandas as pd  # type: ignore[import-untyped]

    if instrument not in AUTHORIZED_STRATEGY_INSTRUMENTS:
        raise ValueError("instrument is outside the amended execution set")
    if start < ALLOWED_START or end > ALLOWED_END or end < start:
        raise ValueError("execution window is outside 2015-01-01..2022-12-31")
    fields = (
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    )
    timestamps: list[np.ndarray] = []
    values: dict[str, list[np.ndarray]] = {field: [] for field in fields}
    start_ns = np.datetime64(start.isoformat(), "ns")
    end_ns = np.datetime64((end + timedelta(days=1)).isoformat(), "ns")
    for year, month in _month_sequence(start, end):
        path = (
            repo
            / "data"
            / "canonical"
            / "p0rdcra1a"
            / instrument
            / "timeframe=M5"
            / f"year={year}"
            / f"month={month:02d}"
            / "part.parquet"
        )
        if not path.is_file():
            raise FileNotFoundError(f"certified M5 partition missing: {path}")
        frame = pd.read_parquet(path, columns=["timestamp", *fields])
        stamp = frame["timestamp"].to_numpy(dtype="datetime64[ns]")
        mask = (stamp >= start_ns) & (stamp < end_ns)
        if not np.any(mask):
            continue
        timestamps.append(stamp[mask])
        for field in fields:
            values[field].append(frame[field].to_numpy(dtype=np.float64)[mask])
    if not timestamps:
        raise ValueError("zero-row certified execution window")
    joined_ts = np.concatenate(timestamps)
    if np.any(joined_ts[1:] <= joined_ts[:-1]):
        raise ValueError("certified execution timestamps are not strictly increasing")
    series = BidAskBarSeries(
        pair=TradingPair(instrument),
        timeframe=Timeframe.M5,
        timestamps=joined_ts,
        **{field: np.concatenate(parts) for field, parts in values.items()},
    )
    violations = series.validate_invariants()
    if violations:
        raise ValueError(f"certified M5 invariant failure: {violations}")
    return series


def zero_trade_funnels(candidates: list[CandidateSpec]) -> list[CandidateFunnel]:
    """Reconstruct why P0 could not emit trades without opening market storage."""
    return [
        CandidateFunnel(
            candidate_id=candidate.candidate_id,
            eligible_market_bars=0,
            candidate_detection_opportunities=0,
            raw_signals=0,
            causally_valid_signals=0,
            orders_created=0,
            orders_eligible_for_execution=0,
            orders_filled=0,
            positions_opened=0,
            positions_closed=0,
            trades_accepted_into_aggregate_sample=0,
            rejection_counts={
                reason: (1 if reason in {"missing_data", "uncertified_partition"} else 0)
                for reason in REJECTION_REASONS
            },
            root_causes=[
                "NO_DATA_DISCOVERED",
                "DATA_PRESENT_NOT_CERTIFIED",
                "STRATEGY_RUNTIME_NOT_CONNECTED",
                "EXECUTION_OUTPUT_NOT_CONNECTED_TO_AGGREGATOR",
            ],
        )
        for candidate in candidates
    ]


def permitted_coverage_records(candidates: list[CandidateSpec]) -> list[CandidateCoverageRecord]:
    """Build candidate/instrument/window coverage records from committed certifications only."""
    records = []
    for candidate in candidates:
        for instrument in candidate.instruments:
            for window, required_range in HISTORICAL_WINDOWS.items():
                # Existing committed lineage certifies only fragments, not complete
                # candidate-level 2015-2022 bid/ask coverage for every instrument.
                certification_status = (
                    "PARTIAL_COMMITTED_CERTIFICATION"
                    if instrument == "USDJPY" and window in {"historical_stress", "combined"}
                    else "MISSING_CANDIDATE_LEVEL_CERTIFICATION"
                )
                classification = (
                    "PARTIALLY_COVERED" if "PARTIAL" in certification_status else "NOT_COVERED"
                )
                records.append(
                    CandidateCoverageRecord(
                        candidate_id=candidate.candidate_id,
                        instrument=instrument,
                        window=window,
                        required_date_range=required_range,
                        required_resolution="M5 execution bars derived from M1/tick bid/ask",
                        required_bid_ask_fields=[
                            "bid_open",
                            "bid_high",
                            "bid_low",
                            "bid_close",
                            "ask_open",
                            "ask_high",
                            "ask_low",
                            "ask_close",
                        ],
                        manifest_path=(
                            "results/gate_c5adqr/validation_dataset_freeze.json"
                            if instrument == "USDJPY" and window == "historical_stress"
                            else None
                        ),
                        provider="Dukascopy"
                        if instrument == "USDJPY" and window == "historical_stress"
                        else None,
                        certification_status=certification_status,
                        available_partitions=0,
                        missing_partitions=1,
                        zero_row_partitions=0,
                        duplicate_timestamps="NOT_CERTIFIED_FOR_P0R",
                        missing_intervals="NOT_CERTIFIED_FOR_P0R",
                        spread_availability="NOT_CERTIFIED_FOR_P0R",
                        timezone_dst_certification="NOT_CERTIFIED_FOR_P0R",
                        tick_or_m1_provenance="NOT_CERTIFIED_FOR_P0R",
                        coverage_classification=classification,
                    )
                )
    return records


def candidate_coverage_classification(records: list[CandidateCoverageRecord]) -> dict[str, str]:
    by_candidate: dict[str, list[str]] = {}
    for record in records:
        by_candidate.setdefault(record.candidate_id, []).append(record.coverage_classification)
    classifications = {}
    for candidate_id, values in by_candidate.items():
        if all(value == "FULLY_COVERED" for value in values):
            classifications[candidate_id] = "FULLY_COVERED"
        elif any(value != "NOT_COVERED" for value in values):
            classifications[candidate_id] = "PARTIALLY_COVERED"
        else:
            classifications[candidate_id] = "NOT_COVERED"
    return classifications
