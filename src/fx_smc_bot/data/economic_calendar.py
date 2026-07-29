"""Provider-neutral economic calendar adapter.

Loads high-impact news events from CSV or Parquet files and provides
time-window queries for news filtering.  The research pipeline must
NOT depend on a commercial API — this adapter works with any tabular
source that has timestamp, currency, event_name, and impact_level columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    """A single economic calendar entry."""

    timestamp: datetime
    currency: str
    event_name: str
    impact: Literal["high", "medium", "low"]
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None


@dataclass(slots=True)
class EconomicCalendar:
    """In-memory calendar of economic events with time-window queries."""

    events: list[EconomicEvent] = field(default_factory=list)
    _by_date: dict[str, list[EconomicEvent]] = field(
        default_factory=dict, repr=False,
    )

    def _index(self) -> None:
        self._by_date.clear()
        for ev in self.events:
            key = ev.timestamp.strftime("%Y-%m-%d")
            self._by_date.setdefault(key, []).append(ev)

    @classmethod
    def from_csv(cls, path: Path, **kwargs) -> EconomicCalendar:
        """Load events from a CSV file.

        Expected columns: timestamp, currency, event_name, impact
        Optional columns: actual, forecast, previous
        """
        df = pd.read_csv(path, **kwargs)
        return cls._from_dataframe(df)

    @classmethod
    def from_parquet(cls, path: Path) -> EconomicCalendar:
        """Load events from a Parquet file."""
        df = pd.read_parquet(path)
        return cls._from_dataframe(df)

    @classmethod
    def _from_dataframe(cls, df: pd.DataFrame) -> EconomicCalendar:
        df.columns = [c.lower().strip() for c in df.columns]
        required = {"timestamp", "currency", "event_name", "impact"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)

        events: list[EconomicEvent] = []
        for _, row in df.iterrows():
            impact = str(row["impact"]).lower().strip()
            if impact not in ("high", "medium", "low"):
                impact = "low"
            events.append(EconomicEvent(
                timestamp=row["timestamp"].to_pydatetime(),
                currency=str(row["currency"]).upper().strip(),
                event_name=str(row["event_name"]).strip(),
                impact=impact,  # type: ignore[arg-type]
                actual=_safe_float(row.get("actual")),
                forecast=_safe_float(row.get("forecast")),
                previous=_safe_float(row.get("previous")),
            ))

        cal = cls(events=sorted(events, key=lambda e: e.timestamp))
        cal._index()
        return cal

    def events_in_window(
        self,
        start: datetime,
        end: datetime,
        currencies: list[str] | None = None,
        min_impact: Literal["high", "medium", "low"] = "high",
    ) -> list[EconomicEvent]:
        """Return events within [start, end] matching criteria."""
        impact_rank = {"high": 3, "medium": 2, "low": 1}
        min_rank = impact_rank.get(min_impact, 3)

        results: list[EconomicEvent] = []
        current = start.date()
        end_date = end.date()
        delta = timedelta(days=1)

        while current <= end_date:
            key = current.strftime("%Y-%m-%d")
            for ev in self._by_date.get(key, []):
                if ev.timestamp < start or ev.timestamp > end:
                    continue
                if impact_rank.get(ev.impact, 0) < min_rank:
                    continue
                if currencies and ev.currency not in currencies:
                    continue
                results.append(ev)
            current += delta

        return results

    def is_high_impact_window(
        self,
        timestamp: datetime,
        minutes_before: int = 15,
        minutes_after: int = 15,
        currencies: list[str] | None = None,
    ) -> bool:
        """Check if timestamp falls within a high-impact event window."""
        start = timestamp - timedelta(minutes=minutes_before)
        end = timestamp + timedelta(minutes=minutes_after)
        return len(self.events_in_window(start, end, currencies, "high")) > 0

    def high_impact_windows(
        self,
        date_start: datetime,
        date_end: datetime,
        minutes_before: int = 15,
        minutes_after: int = 15,
        currencies: list[str] | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """Return all high-impact exclusion windows in a date range."""
        events = self.events_in_window(date_start, date_end, currencies, "high")
        return [
            (
                ev.timestamp - timedelta(minutes=minutes_before),
                ev.timestamp + timedelta(minutes=minutes_after),
            )
            for ev in events
        ]


def _safe_float(val) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
