"""Gate P0-R execution coverage and funnel helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fx_smc_bot.research.strategy_alpha import HISTORICAL_WINDOWS, CandidateSpec


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
