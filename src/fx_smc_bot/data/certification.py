"""Scope-aware dataset certification for FX research data.

Certification is never inherited — each scope level (partition, pair-year,
split, dataset) must independently satisfy its own gates. A holdout partition
may receive structural quality inspection but must never be labeled as
development data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fx_smc_bot.data.holdout_access import SPLIT_BOUNDARIES


class PartitionCertification(str, Enum):
    STRUCTURALLY_VALIDATED = "PARTITION_STRUCTURALLY_VALIDATED"
    EXPLORATORY_ONLY = "PARTITION_EXPLORATORY_ONLY"
    REJECTED = "PARTITION_REJECTED"


class DatasetCertification(str, Enum):
    CERTIFIED_FOR_DEVELOPMENT = "DATASET_CERTIFIED_FOR_DEVELOPMENT"
    CERTIFIED_FOR_VALIDATION = "DATASET_CERTIFIED_FOR_VALIDATION"
    HOLDOUT_QUALITY_INSPECTED = "HOLDOUT_QUALITY_INSPECTED_ONLY"
    REJECTED = "DATASET_REJECTED"


PARTITION_ALIGNMENT_THRESHOLD = 0.80
PAIR_YEAR_MIN_MONTHS = 11
PAIR_YEAR_SESSION_COVERAGE_THRESHOLD = 0.70
PAIR_YEAR_MAX_UNPAIRED_RATIO = 0.20
DEVELOPMENT_YEARS = range(2015, 2020)
DEVELOPMENT_MIN_PAIR_YEAR_COVERAGE = 0.85


def _is_holdout_period(year: int, month: int) -> bool:
    start_str, end_str = SPLIT_BOUNDARIES["holdout"]
    start_year = int(start_str[:4])
    end_year = int(end_str[:4])
    return start_year <= year <= end_year


def _get_split_for_year(year: int) -> str | None:
    for split_name, (start_str, end_str) in SPLIT_BOUNDARIES.items():
        if int(start_str[:4]) <= year <= int(end_str[:4]):
            return split_name
    return None


@dataclass(frozen=True, slots=True)
class PartitionQuality:
    """Quality metrics for a single pair/year/month partition."""
    pair: str
    year: int
    month: int
    bid_rows: int = 0
    ask_rows: int = 0
    joined_rows: int = 0
    bid_only: int = 0
    ask_only: int = 0
    negative_spread_count: int = 0
    invalid_ohlc_count: int = 0
    duplicate_count: int = 0
    parquet_roundtrip_ok: bool = False
    resample_ok: bool = False
    checksum: str = ""


@dataclass(slots=True)
class PartitionCertResult:
    """Certification result for a single partition."""
    quality: PartitionQuality
    certification: PartitionCertification
    scope: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pair": self.quality.pair,
            "year": self.quality.year,
            "month": self.quality.month,
            "certification": self.certification.value,
            "scope": self.scope,
            "reasons": self.reasons,
            "bid_rows": self.quality.bid_rows,
            "ask_rows": self.quality.ask_rows,
            "joined_rows": self.quality.joined_rows,
            "bid_only": self.quality.bid_only,
            "ask_only": self.quality.ask_only,
            "negative_spread_count": self.quality.negative_spread_count,
        }


def certify_partition(quality: PartitionQuality) -> PartitionCertResult:
    """Certify a single partition against the structural gate."""
    reasons: list[str] = []
    split = _get_split_for_year(quality.year)
    scope = f"{quality.pair}/{quality.year}-{quality.month:02d}"

    if quality.bid_rows == 0 and quality.ask_rows == 0:
        return PartitionCertResult(
            quality=quality,
            certification=PartitionCertification.EXPLORATORY_ONLY,
            scope=f"{split}:{scope}" if split else scope,
            reasons=["no data on either side"],
        )

    if quality.bid_rows == 0:
        reasons.append("no bid data")
    if quality.ask_rows == 0:
        reasons.append("no ask data")
    if quality.joined_rows == 0 and quality.bid_rows > 0 and quality.ask_rows > 0:
        reasons.append("zero aligned rows despite both sides present")

    total = quality.bid_rows + quality.ask_rows
    if total > 0:
        max_side = max(quality.bid_rows, quality.ask_rows)
        alignment = quality.joined_rows / max_side if max_side > 0 else 0
        if alignment < PARTITION_ALIGNMENT_THRESHOLD:
            reasons.append(
                f"alignment {alignment:.1%} < threshold {PARTITION_ALIGNMENT_THRESHOLD:.0%}"
            )

    if quality.negative_spread_count > 0:
        reasons.append(f"{quality.negative_spread_count} negative spreads")
    if quality.invalid_ohlc_count > 0:
        reasons.append(f"{quality.invalid_ohlc_count} invalid OHLC bars")
    if quality.duplicate_count > 0:
        reasons.append(f"{quality.duplicate_count} duplicate timestamps")

    if not quality.parquet_roundtrip_ok and quality.joined_rows > 0:
        reasons.append("Parquet roundtrip failed")
    if not quality.resample_ok and quality.joined_rows > 0:
        reasons.append("bid/ask resampling failed")

    if reasons:
        cert = PartitionCertification.REJECTED
    elif quality.joined_rows == 0:
        cert = PartitionCertification.EXPLORATORY_ONLY
    else:
        cert = PartitionCertification.STRUCTURALLY_VALIDATED

    if _is_holdout_period(quality.year, quality.month):
        scope = f"holdout:{scope}"
    elif split:
        scope = f"{split}:{scope}"

    return PartitionCertResult(
        quality=quality, certification=cert,
        scope=scope, reasons=reasons,
    )


@dataclass(slots=True)
class PairYearCertResult:
    """Certification result for a pair-year."""
    pair: str
    year: int
    months_valid: int = 0
    months_total: int = 0
    total_joined: int = 0
    session_coverage: float = 0.0
    unpaired_ratio: float = 0.0
    passed: bool = False
    reasons: list[str] = field(default_factory=list)
    partition_results: list[PartitionCertResult] = field(
        default_factory=list,
    )

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "year": self.year,
            "months_valid": self.months_valid,
            "months_total": self.months_total,
            "total_joined": self.total_joined,
            "session_coverage": round(self.session_coverage, 4),
            "unpaired_ratio": round(self.unpaired_ratio, 4),
            "passed": self.passed,
            "reasons": self.reasons,
        }


def certify_pair_year(
    pair: str,
    year: int,
    partition_results: list[PartitionCertResult],
) -> PairYearCertResult:
    """Certify a pair-year against the pair-year gate."""
    result = PairYearCertResult(
        pair=pair, year=year,
        partition_results=partition_results,
    )

    valid = [
        p for p in partition_results
        if p.certification == PartitionCertification.STRUCTURALLY_VALIDATED
    ]
    result.months_valid = len(valid)
    result.months_total = len(partition_results)
    result.total_joined = sum(p.quality.joined_rows for p in partition_results)

    total_unpaired = sum(
        p.quality.bid_only + p.quality.ask_only for p in partition_results
    )
    total_all = result.total_joined + total_unpaired
    result.unpaired_ratio = total_unpaired / total_all if total_all > 0 else 1.0

    if result.months_valid < PAIR_YEAR_MIN_MONTHS:
        result.reasons.append(
            f"only {result.months_valid}/{PAIR_YEAR_MIN_MONTHS} valid months"
        )

    if result.unpaired_ratio > PAIR_YEAR_MAX_UNPAIRED_RATIO:
        result.reasons.append(
            f"unpaired ratio {result.unpaired_ratio:.1%} "
            f"> {PAIR_YEAR_MAX_UNPAIRED_RATIO:.0%}"
        )

    result.passed = len(result.reasons) == 0
    return result


@dataclass(slots=True)
class DevelopmentDatasetCertResult:
    """Certification result for the full development dataset."""
    certification: DatasetCertification
    pair_year_results: dict[str, list[PairYearCertResult]] = field(
        default_factory=dict,
    )
    reasons: list[str] = field(default_factory=list)
    years_covered: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "certification": self.certification.value,
            "years_covered": self.years_covered,
            "reasons": self.reasons,
            "pair_summaries": {
                pair: [r.to_dict() for r in results]
                for pair, results in self.pair_year_results.items()
            },
        }


def certify_development_dataset(
    pair_year_results: dict[str, list[PairYearCertResult]],
) -> DevelopmentDatasetCertResult:
    """Certify the full development dataset (2015-2019)."""
    result = DevelopmentDatasetCertResult(
        certification=DatasetCertification.REJECTED,
        pair_year_results=pair_year_results,
    )

    all_years = set()
    for _pair, year_results in pair_year_results.items():
        for yr in year_results:
            all_years.add(yr.year)

    result.years_covered = sorted(all_years)

    for dev_year in DEVELOPMENT_YEARS:
        if dev_year not in all_years:
            result.reasons.append(f"year {dev_year} missing entirely")

    for pair, year_results in pair_year_results.items():
        passed_years = sum(1 for r in year_results if r.passed)
        total_years = len(year_results)
        if total_years == 0:
            result.reasons.append(f"{pair}: no data at all")
        elif passed_years / total_years < DEVELOPMENT_MIN_PAIR_YEAR_COVERAGE:
            result.reasons.append(
                f"{pair}: only {passed_years}/{total_years} pair-years pass"
            )

    if not result.reasons:
        result.certification = DatasetCertification.CERTIFIED_FOR_DEVELOPMENT

    return result
