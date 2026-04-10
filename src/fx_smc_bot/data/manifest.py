"""Dataset manifest: track what data is available, its quality, and lineage.

A manifest is a JSON file that records per-pair, per-timeframe metadata
including date ranges, bar counts, source info, and quality scores.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DatasetEntry:
    pair: str
    timeframe: str
    source: str
    file_path: str
    bar_count: int
    start_date: str
    end_date: str
    gaps: int = 0
    duplicate_bars: int = 0
    quality_score: float = 1.0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


@dataclass(slots=True)
class DataManifest:
    name: str = "fx_dataset"
    description: str = ""
    entries: list[DatasetEntry] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

    def add_entry(self, entry: DatasetEntry) -> None:
        # Replace existing entry for same pair/tf
        self.entries = [
            e for e in self.entries
            if not (e.pair == entry.pair and e.timeframe == entry.timeframe)
        ]
        self.entries.append(entry)

    def get_entry(self, pair: str, timeframe: str) -> DatasetEntry | None:
        for e in self.entries:
            if e.pair == pair and e.timeframe == timeframe:
                return e
        return None

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "entries": [asdict(e) for e in self.entries],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Manifest saved to %s", path)

    @classmethod
    def load(cls, path: Path | str) -> DataManifest:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        entries = [DatasetEntry(**e) for e in data.get("entries", [])]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            entries=entries,
            created_at=data.get("created_at", ""),
        )

    def summary(self) -> str:
        lines = [f"Dataset: {self.name}", f"Entries: {len(self.entries)}"]
        for e in sorted(self.entries, key=lambda x: (x.pair, x.timeframe)):
            lines.append(
                f"  {e.pair:8s} {e.timeframe:4s}  "
                f"bars={e.bar_count:>8,d}  {e.start_date} -> {e.end_date}  "
                f"quality={e.quality_score:.2f}"
            )
        return "\n".join(lines)
