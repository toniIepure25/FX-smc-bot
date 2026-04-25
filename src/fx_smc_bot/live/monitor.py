"""Real-time monitoring aggregator for the forward paper runner.

Tracks entries/day, lockouts, throttles, CB recoveries, drawdown
watermarks, loss streaks, signal funnel health, inactivity, and
anomaly conditions.  Produces daily/weekly summary dicts suitable
for JSON serialization into review artifacts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(slots=True)
class DailyStats:
    date: str = ""
    entries: int = 0
    exits: int = 0
    candidates_generated: int = 0
    candidates_accepted: int = 0
    candidates_filled: int = 0
    pnl: float = 0.0
    max_dd_pct: float = 0.0
    lockouts: int = 0
    throttles: int = 0
    cb_fires: int = 0
    cb_recoveries: int = 0
    bars_processed: int = 0


class LiveMonitor:
    """Aggregates forward-paper operational metrics in real time."""

    def __init__(
        self,
        signal_drought_threshold_bars: int = 48,
        anomaly_win_rate_band: float = 0.15,
        anomaly_rr_band: float = 0.5,
    ) -> None:
        self._drought_threshold = signal_drought_threshold_bars
        self._wr_band = anomaly_win_rate_band
        self._rr_band = anomaly_rr_band

        self._daily: dict[str, DailyStats] = {}
        self._current_day: str = ""
        self._bars_since_last_candidate = 0
        self._bars_since_last_fill = 0

        # Rolling trade log for drift / anomaly detection
        self._trade_pnls: list[float] = []
        self._trade_rrs: list[float] = []
        self._trade_timestamps: list[datetime] = []

        # Watermarks
        self._peak_equity: float = 0.0
        self._trailing_dd_pct: float = 0.0
        self._absolute_dd_pct: float = 0.0
        self._initial_equity: float = 0.0

        # Streak tracking
        self._current_loss_streak: int = 0
        self._max_loss_streak: int = 0
        self._current_win_streak: int = 0

        # Risk-state event counters
        self._total_lockouts: int = 0
        self._total_throttles: int = 0
        self._total_cb_fires: int = 0
        self._total_cb_recoveries: int = 0

    # ------------------------------------------------------------------
    # Bar-level hooks
    # ------------------------------------------------------------------

    def on_bar(self, timestamp: datetime, equity: float) -> None:
        day_key = timestamp.strftime("%Y-%m-%d")
        if day_key != self._current_day:
            self._current_day = day_key
            self._daily.setdefault(day_key, DailyStats(date=day_key))

        self._daily[day_key].bars_processed += 1
        self._bars_since_last_candidate += 1
        self._bars_since_last_fill += 1

        if self._initial_equity == 0.0:
            self._initial_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            self._trailing_dd_pct = max(0.0, (self._peak_equity - equity) / self._peak_equity)
        if self._initial_equity > 0:
            self._absolute_dd_pct = max(0.0, (self._initial_equity - equity) / self._initial_equity)

        stats = self._daily[day_key]
        stats.max_dd_pct = max(stats.max_dd_pct, self._trailing_dd_pct)

    def on_candidates(self, count: int, accepted: int, timestamp: datetime) -> None:
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.candidates_generated += count
        stats.candidates_accepted += accepted
        if count > 0:
            self._bars_since_last_candidate = 0

    def on_fill(self, timestamp: datetime, is_entry: bool) -> None:
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        if is_entry:
            stats.entries += 1
            stats.candidates_filled += 1
            self._bars_since_last_fill = 0
        else:
            stats.exits += 1

    def on_trade_close(self, pnl: float, rr: float, timestamp: datetime) -> None:
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.pnl += pnl

        self._trade_pnls.append(pnl)
        self._trade_rrs.append(rr)
        self._trade_timestamps.append(timestamp)

        if pnl >= 0:
            self._current_win_streak += 1
            self._current_loss_streak = 0
        else:
            self._current_loss_streak += 1
            self._current_win_streak = 0
            self._max_loss_streak = max(self._max_loss_streak, self._current_loss_streak)

    # ------------------------------------------------------------------
    # Risk-state hooks
    # ------------------------------------------------------------------

    def on_lockout(self, timestamp: datetime) -> None:
        self._total_lockouts += 1
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.lockouts += 1

    def on_throttle(self, timestamp: datetime) -> None:
        self._total_throttles += 1
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.throttles += 1

    def on_cb_fire(self, timestamp: datetime) -> None:
        self._total_cb_fires += 1
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.cb_fires += 1

    def on_cb_recovery(self, timestamp: datetime) -> None:
        self._total_cb_recoveries += 1
        day_key = timestamp.strftime("%Y-%m-%d")
        stats = self._daily.setdefault(day_key, DailyStats(date=day_key))
        stats.cb_recoveries += 1

    # ------------------------------------------------------------------
    # Anomaly / drought detection
    # ------------------------------------------------------------------

    @property
    def is_signal_drought(self) -> bool:
        return self._bars_since_last_candidate >= self._drought_threshold

    @property
    def bars_since_last_signal(self) -> int:
        return self._bars_since_last_candidate

    def check_anomalies(self, baseline_win_rate: float, baseline_avg_rr: float) -> list[str]:
        """Compare recent rolling stats against baseline and return anomaly descriptions."""
        anomalies: list[str] = []
        if len(self._trade_pnls) < 10:
            return anomalies

        recent = self._trade_pnls[-20:]
        wins = sum(1 for p in recent if p >= 0)
        wr = wins / len(recent)
        if abs(wr - baseline_win_rate) > self._wr_band:
            anomalies.append(f"win_rate_drift: rolling={wr:.2%} baseline={baseline_win_rate:.2%}")

        recent_rr = self._trade_rrs[-20:]
        avg_rr = sum(recent_rr) / len(recent_rr)
        if abs(avg_rr - baseline_avg_rr) > self._rr_band:
            anomalies.append(f"rr_drift: rolling_avg={avg_rr:.2f} baseline={baseline_avg_rr:.2f}")

        if self._current_loss_streak >= 6:
            anomalies.append(f"extended_loss_streak: {self._current_loss_streak}")

        if self.is_signal_drought:
            anomalies.append(f"signal_drought: {self._bars_since_last_candidate} bars")

        return anomalies

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    def daily_summary(self, day_key: str | None = None) -> dict[str, Any]:
        key = day_key or self._current_day
        stats = self._daily.get(key)
        if not stats:
            return {"day": key, "status": "no_data"}
        return {
            "day": stats.date,
            "entries": stats.entries,
            "exits": stats.exits,
            "candidates_generated": stats.candidates_generated,
            "candidates_accepted": stats.candidates_accepted,
            "candidates_filled": stats.candidates_filled,
            "pnl": round(stats.pnl, 2),
            "max_dd_pct": round(stats.max_dd_pct, 4),
            "lockouts": stats.lockouts,
            "throttles": stats.throttles,
            "cb_fires": stats.cb_fires,
            "cb_recoveries": stats.cb_recoveries,
            "bars_processed": stats.bars_processed,
        }

    def weekly_summary(self) -> dict[str, Any]:
        total_trades = len(self._trade_pnls)
        wins = sum(1 for p in self._trade_pnls if p >= 0)
        total_pnl = sum(self._trade_pnls)
        return {
            "total_days": len(self._daily),
            "total_trades": total_trades,
            "win_rate": round(wins / total_trades, 3) if total_trades else 0.0,
            "total_pnl": round(total_pnl, 2),
            "avg_rr": round(sum(self._trade_rrs) / len(self._trade_rrs), 2) if self._trade_rrs else 0.0,
            "peak_equity": round(self._peak_equity, 2),
            "trailing_dd_pct": round(self._trailing_dd_pct, 4),
            "absolute_dd_pct": round(self._absolute_dd_pct, 4),
            "max_loss_streak": self._max_loss_streak,
            "current_loss_streak": self._current_loss_streak,
            "total_lockouts": self._total_lockouts,
            "total_throttles": self._total_throttles,
            "total_cb_fires": self._total_cb_fires,
            "total_cb_recoveries": self._total_cb_recoveries,
            "signal_drought_bars": self._bars_since_last_candidate,
        }

    def all_daily_summaries(self) -> list[dict[str, Any]]:
        return [self.daily_summary(k) for k in sorted(self._daily.keys())]
