"""Development-data planning for Gate Q.0 with explicit-path-only inventory."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fx_smc_bot.research.quant_polarity import (
    DEVELOPMENT_INSTRUMENTS,
    PROGRAM_ID,
    authorize_explicit_path,
    canonical_json_sha256,
)

DEVELOPMENT_YEARS = tuple(range(2015, 2020))
MONTHS = tuple(range(1, 13))
SIDES = ("bid", "ask")
RAW_ROOTS = (
    "data/raw/gate_q0/dukascopy-node",
    "data/real/raw/dukascopy-node",
    "data/raw/dukascopy-node",
    "data/raw/p0rdcra1a/dukascopy-node",
)
CANONICAL_ROOTS = (
    "data/canonical/gate_q0",
    "data/canonical/dukascopy",
    "data/canonical/p0rdcra1a",
)


@dataclass(frozen=True)
class DevelopmentPartition:
    instrument: str
    year: int
    month: int
    side: str

    @property
    def partition_id(self) -> str:
        return f"{self.instrument}:{self.side}:{self.year:04d}-{self.month:02d}"


def development_partitions() -> tuple[DevelopmentPartition, ...]:
    return tuple(
        DevelopmentPartition(instrument, year, month, side)
        for instrument in DEVELOPMENT_INSTRUMENTS
        for year in DEVELOPMENT_YEARS
        for month in MONTHS
        for side in SIDES
    )


def _explicit_file_record(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    authorize_explicit_path(path.as_posix(), "development")
    exists = path.is_file()
    return {
        "path": path.relative_to(root).as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
    }


def explicit_development_inventory(root: Path) -> dict[str, Any]:
    """Inspect only fully specified files; never enumerate a directory."""
    root_counts: dict[str, dict[str, int]] = {}
    total_present_bytes = 0
    total_present_files = 0
    pair_month_presence: dict[str, dict[str, bool]] = {}
    for instrument in DEVELOPMENT_INSTRUMENTS:
        for year in DEVELOPMENT_YEARS:
            for month in MONTHS:
                key = f"{instrument}:{year:04d}-{month:02d}"
                pair_month_presence[key] = {"raw": False, "m1": False, "m5": False}
                for raw_root in RAW_ROOTS:
                    for side in SIDES:
                        base = Path(raw_root) / instrument / f"price={side}"
                        base = base / f"year={year}" / f"month={month:02d}"
                        for filename in ("data.json", "manifest.json"):
                            record = _explicit_file_record(root, base / filename)
                            counts = root_counts.setdefault(
                                raw_root, {"present_files": 0, "present_bytes": 0}
                            )
                            if record["exists"]:
                                counts["present_files"] += 1
                                counts["present_bytes"] += int(record["size_bytes"])
                                total_present_files += 1
                                total_present_bytes += int(record["size_bytes"])
                                pair_month_presence[key]["raw"] = True
                for canonical_root in CANONICAL_ROOTS:
                    for timeframe in ("M1", "M5"):
                        relative = (
                            Path(canonical_root)
                            / instrument
                            / f"timeframe={timeframe}"
                            / f"year={year}"
                            / f"month={month:02d}"
                            / "part.parquet"
                        )
                        record = _explicit_file_record(root, relative)
                        counts = root_counts.setdefault(
                            canonical_root, {"present_files": 0, "present_bytes": 0}
                        )
                        if record["exists"]:
                            counts["present_files"] += 1
                            counts["present_bytes"] += int(record["size_bytes"])
                            total_present_files += 1
                            total_present_bytes += int(record["size_bytes"])
                            pair_month_presence[key][timeframe.lower()] = True

    classifications = {
        "COMPLETE_REQUIRES_RECERTIFICATION": 0,
        "PARTIAL_REQUIRES_RECOVERY": 0,
        "MISSING": 0,
    }
    for presence in pair_month_presence.values():
        if all(presence.values()):
            classifications["COMPLETE_REQUIRES_RECERTIFICATION"] += 1
        elif any(presence.values()):
            classifications["PARTIAL_REQUIRES_RECOVERY"] += 1
        else:
            classifications["MISSING"] += 1
    return {
        "authorized_instruments": list(DEVELOPMENT_INSTRUMENTS),
        "authorized_years": list(DEVELOPMENT_YEARS),
        "pair_month_count": len(pair_month_presence),
        "side_month_count": len(development_partitions()),
        "classification_counts": classifications,
        "root_summaries": root_counts,
        "present_file_count": total_present_files,
        "present_bytes": total_present_bytes,
        "parent_directories_enumerated": False,
        "holdout_paths_constructed_or_tested": False,
        "replication_paths_constructed_or_tested": False,
        "status": "PASS",
    }


def development_storage_budget(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    usage = shutil.disk_usage(root)
    pair_months = len(DEVELOPMENT_INSTRUMENTS) * len(DEVELOPMENT_YEARS) * len(MONTHS)
    missing_pair_months = int(inventory["classification_counts"]["MISSING"])
    partial_pair_months = int(inventory["classification_counts"]["PARTIAL_REQUIRES_RECOVERY"])
    estimated_raw = (missing_pair_months * 2 + partial_pair_months) * 8 * 1024**2
    estimated_m1 = pair_months * 4 * 1024**2
    estimated_m5 = pair_months * 1 * 1024**2
    scratch = (estimated_m1 + estimated_m5) // 2
    peak = estimated_raw + estimated_m1 + estimated_m5 + scratch
    safety_margin = min(10 * 1024**3, int(usage.total * 0.20))
    remaining = usage.free - peak
    return {
        "filesystem_total_bytes": usage.total,
        "current_free_bytes": usage.free,
        "estimated_missing_raw_bytes": estimated_raw,
        "estimated_m1_canonical_bytes": estimated_m1,
        "estimated_m5_canonical_bytes": estimated_m5,
        "certification_scratch_bytes": scratch,
        "estimated_temporary_peak_bytes": peak,
        "estimated_remaining_after_peak_bytes": remaining,
        "required_safety_margin_bytes": safety_margin,
        "status": "PASS" if remaining >= safety_margin else "FAIL",
    }


def development_recovery_protocol(root: Path, preregistration_sha: str) -> dict[str, Any]:
    inventory = explicit_development_inventory(root)
    budget = development_storage_budget(root, inventory)
    partitions = development_partitions()
    payload: dict[str, Any] = {
        "program_id": PROGRAM_ID,
        "protocol_id": "Q0_DEVELOPMENT_DATA_RECOVERY_V1",
        "preregistration_sha": preregistration_sha,
        "instruments": list(DEVELOPMENT_INSTRUMENTS),
        "start": "2015-01-01",
        "end": "2019-12-31",
        "pair_month_count": 240,
        "side_month_count": 480,
        "planned_partition_ids": [partition.partition_id for partition in partitions],
        "primary_provider": "dukascopy-node@1.46.4",
        "fallback_provider": "native Dukascopy BI5 parity-certified transport",
        "raw_source": "DUKASCOPY_TICK_BI5_BID_ASK",
        "canonical_hierarchy": ["UTC_M1_BID_ASK_OHLC", "M5_BID_ASK_OHLC"],
        "inventory": inventory,
        "storage_budget": budget,
        "retry_policy": {
            "maximum_attempts_per_unit": 5,
            "backoff": "bounded exponential",
            "http_429": "honor Retry-After",
        },
        "concurrency": {
            "maximum_workers": 8,
            "worker_unit": "instrument-side-month",
            "adaptive_reduction_on_rate_limit": True,
        },
        "certification": {
            "all_pair_months_required": True,
            "zero_unresolved_partitions_required": True,
            "zero_certified_zero_row_partitions_required": True,
            "positive_finite_spread_required": True,
            "deterministic_canonicalization_runs": 3,
        },
        "guards": {
            "authorize_before_path_or_provider_access": True,
            "development_mode_only": True,
            "request_end_lte": "2019-12-31",
            "replication_access": False,
            "holdout_access": False,
        },
        "local_storage": {
            "raw": "data/raw/gate_q0/dukascopy-node",
            "canonical": "data/canonical/gate_q0",
            "state": "data/acquisition_state/gate_q0",
            "logs": "logs/gate_q0",
        },
        "raw_or_canonical_git_commit_permitted": False,
        "status": "FROZEN_BEFORE_PROVIDER_ACCESS"
        if budget["status"] == "PASS" and inventory["status"] == "PASS"
        else "BLOCKED_BY_STORAGE_BUDGET",
    }
    payload["protocol_hash"] = canonical_json_sha256(payload)
    return payload
