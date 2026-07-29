"""Permitted-data provenance and provider guards for Gate P0-R-DCR.

This module deliberately performs no filesystem discovery and no provider I/O.
It reconstructs requirements from compact frozen artifacts and validates a
request completely before an acquisition caller may touch storage or network.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

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
