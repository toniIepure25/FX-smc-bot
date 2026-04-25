"""Operational health monitoring for the paper/live trading runner.

Tracks bar gaps, stale prices, missing data, and component status.
Emits alerts via AlertSink when health issues are detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from fx_smc_bot.config import OperationalState
from fx_smc_bot.live.alerts import AlertEvent, AlertSink


class ComponentStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(slots=True)
class HealthSnapshot:
    timestamp: datetime | None = None
    engine_status: ComponentStatus = ComponentStatus.OK
    broker_status: ComponentStatus = ComponentStatus.OK
    data_status: ComponentStatus = ComponentStatus.OK
    risk_status: ComponentStatus = ComponentStatus.OK
    operational_state: OperationalState = OperationalState.ACTIVE
    last_bar_time: datetime | None = None
    bars_since_last_fill: int = 0
    stale_data_flag: bool = False
    missing_bar_count: int = 0
    total_bars_processed: int = 0

    @property
    def is_healthy(self) -> bool:
        return all(
            s == ComponentStatus.OK
            for s in (self.engine_status, self.broker_status, self.data_status, self.risk_status)
        ) and not self.stale_data_flag

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": str(self.timestamp) if self.timestamp else None,
            "engine": self.engine_status.value,
            "broker": self.broker_status.value,
            "data": self.data_status.value,
            "risk": self.risk_status.value,
            "operational_state": self.operational_state.value,
            "last_bar_time": str(self.last_bar_time) if self.last_bar_time else None,
            "bars_since_last_fill": self.bars_since_last_fill,
            "stale_data_flag": self.stale_data_flag,
            "missing_bar_count": self.missing_bar_count,
            "is_healthy": self.is_healthy,
        }


class HealthMonitor:
    """Tracks runtime health and emits alerts for anomalies."""

    def __init__(
        self,
        alert_sink: AlertSink | None = None,
        max_bar_gap_minutes: int = 120,
        stale_bars_threshold: int = 100,
    ) -> None:
        self._alert_sink = alert_sink
        self._max_bar_gap = timedelta(minutes=max_bar_gap_minutes)
        self._stale_bars_threshold = stale_bars_threshold
        self._last_bar_time: datetime | None = None
        self._last_fill_bar: int = 0
        self._bars_processed: int = 0
        self._missing_bars: int = 0
        self._operational_state = OperationalState.ACTIVE

    def on_bar(self, bar_time: datetime) -> list[str]:
        """Process a new bar timestamp. Returns list of warning messages."""
        warnings: list[str] = []
        self._bars_processed += 1

        if self._last_bar_time is not None:
            gap = bar_time - self._last_bar_time
            is_weekend_gap = self._is_fx_weekend_gap(self._last_bar_time, bar_time)
            if gap > self._max_bar_gap and not is_weekend_gap:
                self._missing_bars += 1
                msg = f"Bar gap detected: {gap} between {self._last_bar_time} and {bar_time}"
                warnings.append(msg)
                self._emit_alert("warning", msg, bar_time, "data_health")

        self._last_bar_time = bar_time
        return warnings

    @staticmethod
    def _is_fx_weekend_gap(prev_time: datetime, cur_time: datetime) -> bool:
        """True if the gap spans the normal FX weekend (Fri close -> Sun/Mon open)."""
        if prev_time.weekday() == 4 and cur_time.weekday() in (6, 0):
            return True
        if prev_time.weekday() == 4 and cur_time.weekday() == 0:
            return True
        if prev_time.weekday() >= 5 or cur_time.weekday() == 0 and prev_time.weekday() >= 4:
            return True
        return False

    def on_fill(self) -> None:
        self._last_fill_bar = self._bars_processed

    def on_state_change(self, new_state: OperationalState, bar_time: datetime) -> None:
        if new_state != self._operational_state:
            self._emit_alert(
                "warning" if new_state != OperationalState.ACTIVE else "info",
                f"Operational state changed to {new_state.value}",
                bar_time,
                "risk_state",
            )
            self._operational_state = new_state

    def snapshot(self, bar_time: datetime | None = None) -> HealthSnapshot:
        bars_since_fill = self._bars_processed - self._last_fill_bar
        # Only flag stale data when the system is ACTIVE —
        # in LOCKED/STOPPED state, absence of fills is expected risk behavior
        actively_trading = self._operational_state == OperationalState.ACTIVE
        stale = bars_since_fill > self._stale_bars_threshold and actively_trading

        risk_status = ComponentStatus.OK
        if self._operational_state == OperationalState.LOCKED:
            risk_status = ComponentStatus.DEGRADED
        elif self._operational_state == OperationalState.STOPPED:
            risk_status = ComponentStatus.ERROR

        data_status = ComponentStatus.OK
        if self._missing_bars > 5:
            data_status = ComponentStatus.DEGRADED
        if stale:
            data_status = ComponentStatus.ERROR

        return HealthSnapshot(
            timestamp=bar_time or self._last_bar_time,
            engine_status=ComponentStatus.OK,
            broker_status=ComponentStatus.OK,
            data_status=data_status,
            risk_status=risk_status,
            operational_state=self._operational_state,
            last_bar_time=self._last_bar_time,
            bars_since_last_fill=bars_since_fill,
            stale_data_flag=stale,
            missing_bar_count=self._missing_bars,
            total_bars_processed=self._bars_processed,
        )

    def _emit_alert(self, level: str, message: str, bar_time: datetime, category: str = "health") -> None:
        if self._alert_sink is not None:
            self._alert_sink.emit(AlertEvent(
                level=level, message=message,
                timestamp=bar_time, category=category,
            ))
