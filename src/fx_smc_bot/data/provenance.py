"""Data source provenance and integrity tracking.

Records metadata about data origin, quality, and transformations applied,
enabling reproducible research with auditable data lineage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.data.models import BarSeries


@dataclass(frozen=True, slots=True)
class DataProvenance:
    """Immutable record of a dataset's origin and quality status."""

    source: str
    instrument: str
    resolution: str
    price_type: Literal["bid_ask", "mid", "unknown"]
    spread_source: Literal["historical", "synthetic", "none"]
    timezone: str
    download_date: str
    checksum_sha256: str
    start_date: str
    end_date: str
    bar_count: int
    missing_intervals: list[tuple[str, str]] = field(default_factory=list)
    duplicate_count: int = 0
    weekend_bars_removed: int = 0
    outliers_flagged: int = 0
    dst_transitions_verified: bool = False
    normalization_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> DataProvenance:
        raw = json.loads(path.read_text())
        raw["missing_intervals"] = [
            tuple(iv) for iv in raw.get("missing_intervals", [])
        ]
        return cls(**raw)


def compute_file_checksum(path: Path, algorithm: str = "sha256") -> str:
    """Compute hex digest of a file."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_series_checksum(series: BarSeries) -> str:
    """Compute a SHA-256 checksum of a BarSeries for reproducibility."""
    h = hashlib.sha256()
    h.update(series.timestamps.tobytes())
    h.update(series.open.tobytes())
    h.update(series.high.tobytes())
    h.update(series.low.tobytes())
    h.update(series.close.tobytes())
    return h.hexdigest()


def detect_missing_intervals(
    timestamps: NDArray[np.datetime64],
    expected_minutes: int,
    max_gap_multiple: float = 3.0,
) -> list[tuple[str, str]]:
    """Find gaps in timestamp sequence that exceed the expected interval."""
    if len(timestamps) < 2:
        return []

    expected_delta = np.timedelta64(expected_minutes, "m")
    max_gap = expected_delta * max_gap_multiple
    gaps: list[tuple[str, str]] = []

    diffs = np.diff(timestamps)
    for i, d in enumerate(diffs):
        if d > max_gap:
            start = str(timestamps[i].astype("datetime64[us]"))
            end = str(timestamps[i + 1].astype("datetime64[us]"))
            gaps.append((start, end))

    return gaps


def detect_duplicate_timestamps(
    timestamps: NDArray[np.datetime64],
) -> int:
    """Count duplicate timestamps in the series."""
    _, counts = np.unique(timestamps, return_counts=True)
    return int(np.sum(counts[counts > 1]) - np.sum(counts > 1))


def build_provenance(
    series: BarSeries,
    source: str,
    price_type: Literal["bid_ask", "mid", "unknown"] = "unknown",
    spread_source: Literal["historical", "synthetic", "none"] = "none",
    download_date: date | None = None,
    expected_minutes: int | None = None,
    file_path: Path | None = None,
    normalization_applied: list[str] | None = None,
) -> DataProvenance:
    """Build a DataProvenance record from a BarSeries."""
    from fx_smc_bot.config import TIMEFRAME_MINUTES

    tf_minutes = expected_minutes or TIMEFRAME_MINUTES.get(series.timeframe, 15)
    checksum = (
        compute_file_checksum(file_path)
        if file_path and file_path.exists()
        else compute_series_checksum(series)
    )

    missing = detect_missing_intervals(series.timestamps, tf_minutes)
    duplicates = detect_duplicate_timestamps(series.timestamps)

    start_str = str(series.timestamps[0].astype("datetime64[us]"))
    end_str = str(series.timestamps[-1].astype("datetime64[us]"))

    return DataProvenance(
        source=source,
        instrument=series.pair.value,
        resolution=series.timeframe.value,
        price_type=price_type,
        spread_source=spread_source,
        timezone="UTC",
        download_date=(download_date or date.today()).isoformat(),
        checksum_sha256=checksum,
        start_date=start_str,
        end_date=end_str,
        bar_count=len(series),
        missing_intervals=missing,
        duplicate_count=duplicates,
        normalization_applied=normalization_applied or [],
    )
