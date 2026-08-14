"""Durable, resumable bulk-acquisition state machine.

Every acquisition unit (instrument x date) carries an immutable-progression status. State is
persisted atomically after each transition so a killed process resumes without repeating
certified work, and a certified canonical unit is never silently overwritten. Source and
canonical checksums are tracked independently.

"Market closed" is NEVER inferred from provider silence: a unit becomes TERMINAL_DATA_ABSENT
only through the deterministic pre-outcome calendar rule (weekends), never from a 503/timeout
(those are RETRYABLE). Weekday provider-silence is surfaced, not silently excluded.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from fx_smc_bot.research.v3.fx_calendar import is_market_closed_calendar


class UnitStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    CERTIFIED_NATIVE = "CERTIFIED_NATIVE"
    CERTIFIED_TICK_FALLBACK = "CERTIFIED_TICK_FALLBACK"
    RETRYABLE = "RETRYABLE"
    TERMINAL_DATA_ABSENT = "TERMINAL_DATA_ABSENT"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


class Transport(str, Enum):
    NATIVE_M1 = "NATIVE_M1"
    TICK_AGGREGATED_M1 = "TICK_AGGREGATED_M1"


CERTIFIED = (UnitStatus.CERTIFIED_NATIVE, UnitStatus.CERTIFIED_TICK_FALLBACK)
TERMINAL = (*CERTIFIED, UnitStatus.TERMINAL_DATA_ABSENT)

# Allowed transitions. Certified/absent are terminal-ish: never regress to a pending status.
_ALLOWED: dict[UnitStatus, set[UnitStatus]] = {
    UnitStatus.PLANNED: {UnitStatus.IN_PROGRESS, UnitStatus.TERMINAL_DATA_ABSENT},
    UnitStatus.IN_PROGRESS: {
        UnitStatus.CERTIFIED_NATIVE, UnitStatus.CERTIFIED_TICK_FALLBACK,
        UnitStatus.RETRYABLE, UnitStatus.INTEGRITY_FAILURE, UnitStatus.TERMINAL_DATA_ABSENT,
    },
    UnitStatus.RETRYABLE: {
        UnitStatus.IN_PROGRESS, UnitStatus.CERTIFIED_NATIVE,
        UnitStatus.CERTIFIED_TICK_FALLBACK, UnitStatus.INTEGRITY_FAILURE,
    },
    UnitStatus.INTEGRITY_FAILURE: {UnitStatus.IN_PROGRESS, UnitStatus.RETRYABLE},
    UnitStatus.CERTIFIED_NATIVE: set(),
    UnitStatus.CERTIFIED_TICK_FALLBACK: set(),
    UnitStatus.TERMINAL_DATA_ABSENT: set(),
}


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=Sat, 6=Sun


@dataclass(slots=True)
class UnitRecord:
    instrument: str
    day: str                       # ISO date
    status: str = UnitStatus.PLANNED.value
    transport: str | None = None
    fallback_reason: str | None = None
    source_checksum: str | None = None
    canonical_checksum: str | None = None
    source_bytes: int = 0
    canonical_rows: int = 0
    attempts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StateStore:
    path: Path
    units: dict[str, UnitRecord] = field(default_factory=dict)

    @staticmethod
    def key(instrument: str, d: date | str) -> str:
        iso = d.isoformat() if isinstance(d, date) else d
        return f"{instrument}:{iso}"

    def load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self.units = {k: UnitRecord(**v) for k, v in raw.items()}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: r.as_dict() for k, r in sorted(self.units.items())}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=0, sort_keys=True)
        os.replace(tmp, str(self.path))  # atomic

    def plan(self, instrument: str, d: date) -> None:
        k = self.key(instrument, d)
        if k in self.units:
            return
        # Deterministic FX weekly-session calendar: ONLY Saturday is fully closed. Sunday is a
        # legitimate (partial) trading date; Friday is a partial-close trading date. Closure is
        # never inferred from provider silence.
        closed = is_market_closed_calendar(d)
        status = UnitStatus.TERMINAL_DATA_ABSENT if closed else UnitStatus.PLANNED
        self.units[k] = UnitRecord(
            instrument=instrument, day=d.isoformat(), status=status.value,
            transport=None,
            fallback_reason="saturday_calendar_closure" if closed else None,
        )

    def transition(self, instrument: str, d: date | str, new: UnitStatus, **fields: Any) -> None:
        k = self.key(instrument, d)
        rec = self.units[k]
        cur = UnitStatus(rec.status)
        if cur in CERTIFIED and new not in CERTIFIED:
            raise ValueError(f"refusing to overwrite certified unit {k} with {new.value}")
        if new != cur and new not in _ALLOWED[cur]:
            raise ValueError(f"illegal transition {cur.value} -> {new.value} for {k}")
        rec.status = new.value
        for f, v in fields.items():
            setattr(rec, f, v)
        self._persist()

    def pending_keys(self) -> list[str]:
        return [k for k, r in sorted(self.units.items())
                if UnitStatus(r.status) in (UnitStatus.PLANNED, UnitStatus.RETRYABLE,
                                            UnitStatus.INTEGRITY_FAILURE)]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        native = tick = 0
        for r in self.units.values():
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status == UnitStatus.CERTIFIED_NATIVE.value:
                native += 1
            elif r.status == UnitStatus.CERTIFIED_TICK_FALLBACK.value:
                tick += 1
        total = len(self.units)
        certified = native + tick
        return {
            "total_units": total,
            "counts_by_status": counts,
            "certified_units": certified,
            "certified_native": native,
            "certified_tick_fallback": tick,
            "pending_units": len(self.pending_keys()),
            "coverage_complete": all(
                UnitStatus(r.status) in TERMINAL for r in self.units.values()
            ) and total > 0,
        }
