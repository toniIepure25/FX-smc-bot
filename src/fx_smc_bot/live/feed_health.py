"""Feed-level health monitoring for live data ingestion.

Tracks bar arrival timing, detects stale/duplicate/out-of-order/missing
bars, and produces a feed quality score used by the forward runner and
safety controller to decide whether trading should continue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fx_smc_bot.data.market_calendar import expected_bar_interval, is_market_open
from fx_smc_bot.domain import MarketBar

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeedQualityReport:
    """Cumulative feed quality metrics."""
    total_bars_received: int = 0
    duplicate_bars_rejected: int = 0
    out_of_order_bars_rejected: int = 0
    gaps_detected: int = 0
    max_gap_seconds: float = 0.0
    stale_alerts_fired: int = 0
    last_bar_time: datetime | None = None
    last_heartbeat_time: datetime | None = None
    completeness_pct: float = 100.0
    freshness_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bars_received": self.total_bars_received,
            "duplicate_bars_rejected": self.duplicate_bars_rejected,
            "out_of_order_bars_rejected": self.out_of_order_bars_rejected,
            "gaps_detected": self.gaps_detected,
            "max_gap_seconds": round(self.max_gap_seconds, 1),
            "stale_alerts_fired": self.stale_alerts_fired,
            "last_bar_time": self.last_bar_time.isoformat() if self.last_bar_time else None,
            "completeness_pct": round(self.completeness_pct, 2),
            "freshness_score": round(self.freshness_score, 3),
        }


class FeedHealthMonitor:
    """Validates incoming bars and tracks feed reliability metrics.

    The monitor is designed to sit between the LiveFeedProvider and the
    ForwardPaperRunner: each new bar is passed through ``validate_bar``
    before being accepted into the BarBuffer.
    """

    def __init__(
        self,
        bar_interval_minutes: int = 60,
        stale_timeout_minutes: int = 180,
        gap_tolerance_factor: float = 1.5,
    ) -> None:
        self._expected_interval = expected_bar_interval(bar_interval_minutes)
        self._stale_timeout = timedelta(minutes=stale_timeout_minutes)
        self._gap_tolerance = timedelta(
            seconds=self._expected_interval.total_seconds() * gap_tolerance_factor
        )

        self._seen_timestamps: set[datetime] = set()
        self._last_accepted_time: datetime | None = None
        self._expected_bars: int = 0
        self._report = FeedQualityReport()

    @property
    def report(self) -> FeedQualityReport:
        return self._report

    def validate_bar(self, bar: MarketBar) -> tuple[bool, str]:
        """Validate a bar for ingestion. Returns (accepted, reason)."""
        ts = bar.timestamp

        # Duplicate detection
        if ts in self._seen_timestamps:
            self._report.duplicate_bars_rejected += 1
            return False, "duplicate_timestamp"

        # Out-of-order detection
        if self._last_accepted_time is not None and ts <= self._last_accepted_time:
            self._report.out_of_order_bars_rejected += 1
            return False, "out_of_order"

        # Gap detection (only when market is expected to be open)
        if self._last_accepted_time is not None:
            gap = ts - self._last_accepted_time
            if gap > self._gap_tolerance and is_market_open(self._last_accepted_time):
                self._report.gaps_detected += 1
                gap_sec = gap.total_seconds()
                if gap_sec > self._report.max_gap_seconds:
                    self._report.max_gap_seconds = gap_sec
                logger.warning(
                    "Feed gap: %.0fs between %s and %s",
                    gap_sec, self._last_accepted_time, ts,
                )

        # Accept bar
        self._seen_timestamps.add(ts)
        self._last_accepted_time = ts
        self._report.total_bars_received += 1
        self._report.last_bar_time = ts
        self._expected_bars += 1

        # Keep the seen-set bounded (no need to remember bars older than 7 days)
        if len(self._seen_timestamps) > 10_000:
            cutoff = ts - timedelta(days=7)
            self._seen_timestamps = {t for t in self._seen_timestamps if t > cutoff}

        return True, "accepted"

    def check_staleness(self, wall_clock: datetime) -> bool:
        """Return True if the feed appears stale relative to wall clock."""
        if self._last_accepted_time is None:
            return False
        if not is_market_open(wall_clock):
            return False
        age = wall_clock - self._last_accepted_time
        if age > self._stale_timeout:
            self._report.stale_alerts_fired += 1
            return True
        return False

    def record_heartbeat(self, wall_clock: datetime) -> None:
        self._report.last_heartbeat_time = wall_clock

    def update_quality_scores(self) -> None:
        """Recompute completeness and freshness scores."""
        r = self._report
        total_attempted = r.total_bars_received + r.duplicate_bars_rejected + r.out_of_order_bars_rejected
        if total_attempted > 0:
            r.completeness_pct = (r.total_bars_received / total_attempted) * 100.0
        else:
            r.completeness_pct = 100.0

        gap_penalty = min(1.0, r.gaps_detected * 0.02)
        stale_penalty = min(1.0, r.stale_alerts_fired * 0.1)
        r.freshness_score = max(0.0, 1.0 - gap_penalty - stale_penalty)
