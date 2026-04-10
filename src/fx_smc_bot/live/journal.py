"""Event journal: append-only JSONL audit log for paper/live trading.

Records signals, orders, fills, state transitions, and alerts as
immutable events with timestamps and run/session IDs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JournalEvent:
    event_type: str
    timestamp: str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> JournalEvent:
        d = json.loads(line)
        return cls(**d)


class EventJournal:
    """Append-only JSONL journal for audit trail."""

    def __init__(self, path: Path | str, run_id: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id
        self._count = 0

    @property
    def event_count(self) -> int:
        return self._count

    def log(self, event_type: str, data: dict[str, Any] | None = None, bar_time: datetime | None = None) -> None:
        ts = bar_time.isoformat() if bar_time else datetime.utcnow().isoformat()
        event = JournalEvent(
            event_type=event_type,
            timestamp=ts,
            run_id=self._run_id,
            data=data or {},
        )
        with open(self._path, "a") as f:
            f.write(event.to_json() + "\n")
        self._count += 1

    def log_signal(self, pair: str, direction: str, family: str, score: float,
                   bar_time: datetime | None = None, **extra: Any) -> None:
        self.log("signal", {"pair": pair, "direction": direction, "family": family, "score": score, **extra},
                 bar_time=bar_time)

    def log_order(self, order_id: str, pair: str, direction: str, order_type: str, units: float,
                  bar_time: datetime | None = None, **extra: Any) -> None:
        self.log("order", {"order_id": order_id, "pair": pair, "direction": direction,
                           "type": order_type, "units": units, **extra}, bar_time=bar_time)

    def log_fill(self, order_id: str, fill_price: float, units: float, reason: str,
                 bar_time: datetime | None = None, **extra: Any) -> None:
        self.log("fill", {"order_id": order_id, "fill_price": fill_price, "units": units,
                          "reason": reason, **extra}, bar_time=bar_time)

    def log_state_transition(self, old_state: str, new_state: str, reason: str = "",
                             bar_time: datetime | None = None) -> None:
        self.log("state_transition", {"old": old_state, "new": new_state, "reason": reason}, bar_time=bar_time)

    def log_alert(self, level: str, message: str, bar_time: datetime | None = None, **extra: Any) -> None:
        self.log("alert", {"level": level, "message": message, **extra}, bar_time=bar_time)

    def read_events(self, event_type: str | None = None) -> list[JournalEvent]:
        """Read all events, optionally filtered by type."""
        events = []
        if not self._path.exists():
            return events
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                evt = JournalEvent.from_json(line)
                if event_type is None or evt.event_type == event_type:
                    events.append(evt)
        return events
