"""Permitted-data provenance and provider guards for Gate P0-R-DCR.

This module deliberately performs no filesystem discovery and no provider I/O.
It reconstructs requirements from compact frozen artifacts and validates a
request completely before an acquisition caller may touch storage or network.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

ALLOWED_START = date(2015, 1, 1)
ALLOWED_END = date(2022, 12, 31)
FORBIDDEN_START = date(2023, 1, 1)
REQUIRED_BID_ASK_FIELDS = (
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)
REQUIREMENT_CLASSES = {
    "STRATEGY_REQUIRED",
    "BENCHMARK_REQUIRED",
    "OPTIONAL_DIAGNOSTIC",
    "NOT_REQUIRED",
}
AMENDMENT_ID = "P0RDCR_DATA_REQUIREMENT_AMENDMENT_V1"
AUTHORIZED_STRATEGY_INSTRUMENTS = frozenset({"EURUSD", "GBPUSD"})
INSTRUMENT_ROLES = {
    "EURUSD": "STRATEGY_REQUIRED",
    "GBPUSD": "STRATEGY_REQUIRED",
    "USDJPY": "OPTIONAL_DIAGNOSTIC",
}
SESSION_CONTRACTS = {
    "london": {
        "timezone": "Europe/London",
        "start_local": "08:00",
        "end_local": "11:00",
    },
    "new_york": {
        "timezone": "America/New_York",
        "start_local": "08:00",
        "end_local": "11:00",
    },
}
MAX_EXPLICIT_INDICATOR_LOOKBACK_M5 = 20
ATR_LOOKBACK_M5 = 14
MAX_STATE_MACHINE_LOOKBACK_M5 = 46
PRIOR_DAY_DEPENDENCY_M5 = 288
WARMUP_M5_BARS = max(
    500,
    MAX_STATE_MACHINE_LOOKBACK_M5 + PRIOR_DAY_DEPENDENCY_M5,
)


@dataclass(frozen=True, slots=True)
class RecoveryPartition:
    instrument: str
    year: int
    month: int
    side: str
    resolution: str = "M1"

    @property
    def partition_id(self) -> str:
        return (
            f"{self.instrument.upper()}:{self.year:04d}-{self.month:02d}:"
            f"{self.side.upper()}:{self.resolution.upper()}"
        )


def validate_provider_request(
    *,
    requested_start: str,
    requested_end: str,
    instrument: str,
    partition: RecoveryPartition,
    required_instruments: Collection[str],
    planned_partition_ids: Collection[str],
) -> None:
    """Fail a provider request before any filesystem or network operation."""
    start = date.fromisoformat(requested_start)
    end = date.fromisoformat(requested_end)
    normalized_instrument = instrument.upper()
    frozen_instruments = {item.upper() for item in required_instruments}
    frozen_partitions = set(planned_partition_ids)

    if start < ALLOWED_START:
        raise ValueError("requested_start precedes the permitted historical boundary")
    if end > ALLOWED_END or end >= FORBIDDEN_START:
        raise ValueError("requested_end reaches the sealed holdout boundary")
    if end < start:
        raise ValueError("requested_end precedes requested_start")
    if normalized_instrument not in frozen_instruments:
        raise ValueError("instrument is not in the frozen recovery protocol")
    if partition.instrument.upper() != normalized_instrument:
        raise ValueError("partition instrument does not match request instrument")
    if partition.year < ALLOWED_START.year or partition.year > ALLOWED_END.year:
        raise ValueError("partition year is outside the permitted historical boundary")
    if partition.month < 1 or partition.month > 12:
        raise ValueError("partition month is invalid")
    if partition.partition_id not in frozen_partitions:
        raise ValueError("partition is not in the frozen recovery plan")


def validate_amended_provider_request(
    *,
    requested_start: str,
    requested_end: str,
    instrument: str,
    partition: RecoveryPartition,
    planned_partition_ids: Collection[str],
) -> None:
    validate_provider_request(
        requested_start=requested_start,
        requested_end=requested_end,
        instrument=instrument,
        partition=partition,
        required_instruments=AUTHORIZED_STRATEGY_INSTRUMENTS,
        planned_partition_ids=planned_partition_ids,
    )


def session_bounds_utc(local_day: date, session: str) -> tuple[datetime, datetime]:
    """Return amended session bounds using timezone-aware IANA conversion."""
    try:
        contract = SESSION_CONTRACTS[session]
    except KeyError as exc:
        raise ValueError(f"Unknown amended session: {session}") from exc
    zone = ZoneInfo(contract["timezone"])
    start_hour, start_minute = (
        int(part) for part in contract["start_local"].split(":")
    )
    end_hour, end_minute = (
        int(part) for part in contract["end_local"].split(":")
    )
    start = datetime.combine(
        local_day,
        time(start_hour, start_minute),
        tzinfo=zone,
    ).astimezone(UTC)
    end = datetime.combine(
        local_day,
        time(end_hour, end_minute),
        tzinfo=zone,
    ).astimezone(UTC)
    return start, end


def fx_week_boundary_utc(local_day: date, boundary: str) -> datetime:
    """Convert the Sunday/Friday 17:00 New York FX-week boundary to UTC."""
    expected_weekday = {"open": 6, "close": 4}
    if boundary not in expected_weekday:
        raise ValueError("boundary must be open or close")
    if local_day.weekday() != expected_weekday[boundary]:
        raise ValueError(f"{boundary} boundary has the wrong local weekday")
    local = datetime.combine(
        local_day,
        time(17, 0),
        tzinfo=ZoneInfo("America/New_York"),
    )
    return local.astimezone(UTC)


def amended_requirement_contract() -> dict[str, Any]:
    """Return the complete outcome-blind Stage 1 requirement amendment."""
    return {
        "amendment_id": AMENDMENT_ID,
        "source_resolution": {
            "provider": "Dukascopy",
            "raw_source": "DUKASCOPY_TICK_BI5_BID_ASK",
            "canonical_intermediate": "UTC_M1_BID_ASK_OHLC",
            "execution_bars": "DETERMINISTIC_M5_BID_ASK_OHLC_FROM_M1",
            "primary_intrabar_execution": "M5_ADVERSE_FIRST",
            "favorable_tick_ordering_used": False,
            "reuse_requires_same_source_provenance_and_exact_canonical_parity": True,
        },
        "warm_up": {
            "maximum_explicit_candidate_indicator_lookback_m5_bars": (
                MAX_EXPLICIT_INDICATOR_LOOKBACK_M5
            ),
            "atr_dependency_m5_bars": ATR_LOOKBACK_M5,
            "maximum_state_machine_lookback_m5_bars": MAX_STATE_MACHINE_LOOKBACK_M5,
            "prior_day_dependency_m5_bars": PRIOR_DAY_DEPENDENCY_M5,
            "mandatory_htf_dependency_m5_bars": 0,
            "formula": "max(500, 46 + 288)",
            "warmup_m5_bars": WARMUP_M5_BARS,
            "provider_request_before_2015_permitted": False,
            "trades_before_warmup_completion_permitted": False,
        },
        "exit_horizon": {
            "priority": [
                "STOP_LOSS",
                "TAKE_PROFIT",
                "ORIGINATING_SESSION_CUTOFF",
                "FX_WEEK_SAFETY_CLOSE",
                "FINAL_AVAILABLE_CERTIFIED_BAR",
            ],
            "opening_range_cutoff": "11:00_LOCAL_SESSION_TIMEZONE",
            "sweep_and_acceptance_cutoff": "END_OF_ORIGINATING_FROZEN_SESSION",
            "overnight_carry": False,
            "rollover_carry": False,
            "weekend_carry": False,
            "friday_safety_exit": "FINAL_EXECUTABLE_QUOTE_BEFORE_17:00_AMERICA_NEW_YORK",
            "missing_cutoff_bar": "FINAL_EXECUTABLE_QUOTE_BEFORE_CUTOFF",
            "missing_executable_quote": "EXECUTION_DATA_MISSING_EXCLUDE_FROM_ACCEPTED_SAMPLE",
            "order_expiry_changed": False,
        },
        "session_calendar": {
            "sessions": SESSION_CONTRACTS,
            "fx_week_open": "SUNDAY_17:00_AMERICA_NEW_YORK",
            "fx_week_close": "FRIDAY_17:00_AMERICA_NEW_YORK",
            "weekends": "EXCLUDED",
            "bank_holiday_synthetic_closure": False,
            "provider_closed_holiday_intervals": "MISSING_OR_MARKET_CLOSED_METADATA",
            "missing_session": "NO_INTERPOLATION",
            "duplicate_utc_timestamp": "FAIL_UNLESS_DETERMINISTICALLY_IDENTICAL",
            "dst_resolution": "IANA_TIMEZONE_AWARE_UTC_CONVERSION_ONLY",
        },
        "instrument_roles": INSTRUMENT_ROLES,
        "usdjpy_required_for_candidate_execution": False,
        "usdjpy_required_for_candidate_certification": False,
        "usdjpy_required_for_frozen_benchmarks": False,
        "usdjpy_required_for_tier_or_ranking": False,
    }


def _instrument_roles(config: dict[str, Any], frozen: list[str]) -> list[dict[str, Any]]:
    configured = config.get("instruments", {})
    primary = {str(item) for item in configured.get("primary", [])}
    control = {str(item) for item in configured.get("control", [])}
    rows: list[dict[str, Any]] = []
    for instrument in frozen:
        if instrument in primary:
            classification = "STRATEGY_REQUIRED"
            provenance_status = "RESOLVED"
            conflict = None
        elif instrument in control:
            classification = "OPTIONAL_DIAGNOSTIC"
            provenance_status = "UNRESOLVED"
            conflict = (
                "The source YAML labels this instrument as control, while the P0 "
                "candidate freeze flattens primary and control instruments into one list. "
                "The benchmark freeze does not resolve whether control data are mandatory."
            )
        else:
            classification = "NOT_REQUIRED"
            provenance_status = "UNRESOLVED"
            conflict = "The frozen candidate lists an instrument absent from its source YAML."
        if classification not in REQUIREMENT_CLASSES:
            raise AssertionError("invalid requirement classification")
        rows.append(
            {
                "instrument": instrument,
                "classification": classification,
                "provenance_status": provenance_status,
                "provenance_conflict": conflict,
            }
        )
    return rows


def reconstruct_data_requirements(
    *,
    candidate_freeze: dict[str, Any],
    candidate_configs: dict[str, dict[str, Any]],
    p0r_coverage: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct exact requirements and expose every unresolved frozen field."""
    coverage_resolution_values = sorted(
        {
            str(record.get("required_resolution"))
            for record in p0r_coverage.get("coverage_records", [])
        }
    )
    candidate_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []

    for frozen in candidate_freeze.get("candidates", []):
        candidate_id = str(frozen["candidate_id"])
        config_path = str(frozen["config_path"])
        config = candidate_configs[config_path]
        roles = _instrument_roles(config, list(frozen.get("instruments", [])))
        if any(row["provenance_status"] == "UNRESOLVED" for row in roles):
            unresolved.append(
                {
                    "candidate_id": candidate_id,
                    "field": "instrument_role.USDJPY",
                    "reason": "P0 does not freeze whether the YAML control instrument is required.",
                }
            )

        session_timezones: dict[str, str | None] = {}
        for session in frozen.get("sessions", []):
            section = config.get(f"opening_range_{session}", {})
            session_timezones[str(session)] = section.get("tz_name")
            if not section.get("tz_name"):
                unresolved.append(
                    {
                        "candidate_id": candidate_id,
                        "field": f"timezone.{session}",
                        "reason": "No timezone identifier is frozen for this session.",
                    }
                )

        for field, reason in (
            (
                "source_resolution",
                "P0-R records M1/tick as alternatives and does not select one exact source.",
            ),
            (
                "warm_up_duration",
                "No exact duration is frozen; detector and ATR history needs are not quantified.",
            ),
            (
                "exit_horizon",
                "P0 explicitly records maximum holding/session cutoff implementation as PARTIAL.",
            ),
            (
                "session_calendar_coverage",
                "No complete holiday, weekend, and DST calendar contract is frozen.",
            ),
        ):
            unresolved.append(
                {"candidate_id": candidate_id, "field": field, "reason": reason}
            )

        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "config_path": config_path,
                "instrument_requirements": roles,
                "required_sessions": frozen.get("sessions", []),
                "required_bar_resolution": "M5",
                "required_source_resolution": None,
                "source_resolution_evidence": coverage_resolution_values,
                "required_bid_ask_fields": list(REQUIRED_BID_ASK_FIELDS),
                "required_spread_fields": [
                    "ask_open_minus_bid_open",
                    "ask_high_minus_bid_high",
                    "ask_low_minus_bid_low",
                    "ask_close_minus_bid_close",
                ],
                "required_timezone_fields": session_timezones,
                "required_warm_up_duration": None,
                "required_start_date": "2015-01-01",
                "required_end_date": "2022-12-31",
                "required_exit_horizon": None,
                "required_session_calendar_coverage": None,
                "provenance_status": "UNRESOLVED",
            }
        )

    status = "PASS" if not unresolved else "FAIL"
    return {
        "program_id": candidate_freeze.get("program_id"),
        "lineage_id": candidate_freeze.get("lineage_id"),
        "overlay_id": overlay.get("overlay_id"),
        "overlay_hash": overlay.get("overlay_hash"),
        "candidate_count": len(candidate_rows),
        "candidates": candidate_rows,
        "unresolved_requirements": unresolved,
        "part_a_permitted_to_continue": status == "PASS",
        "status": status,
    }


def recovery_partition_record(partition: RecoveryPartition) -> dict[str, Any]:
    record = asdict(partition)
    record["partition_id"] = partition.partition_id
    return record
