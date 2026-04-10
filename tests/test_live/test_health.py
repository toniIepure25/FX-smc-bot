"""Tests for the operational health monitor."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from fx_smc_bot.config import OperationalState
from fx_smc_bot.live.alerts import CollectingAlertSink
from fx_smc_bot.live.health import ComponentStatus, HealthMonitor, HealthSnapshot


class TestHealthSnapshot:
    def test_is_healthy_when_all_ok(self) -> None:
        snap = HealthSnapshot()
        assert snap.is_healthy

    def test_not_healthy_when_stale(self) -> None:
        snap = HealthSnapshot(stale_data_flag=True)
        assert not snap.is_healthy

    def test_to_dict_structure(self) -> None:
        snap = HealthSnapshot(timestamp=datetime(2024, 1, 1))
        d = snap.to_dict()
        assert "engine" in d
        assert "is_healthy" in d


class TestHealthMonitor:
    def test_tracks_bars(self) -> None:
        monitor = HealthMonitor()
        monitor.on_bar(datetime(2024, 1, 1, 10, 0))
        monitor.on_bar(datetime(2024, 1, 1, 10, 15))
        snap = monitor.snapshot()
        assert snap.total_bars_processed == 2

    def test_detects_bar_gap(self) -> None:
        sink = CollectingAlertSink()
        monitor = HealthMonitor(alert_sink=sink, max_bar_gap_minutes=30)
        monitor.on_bar(datetime(2024, 1, 2, 10, 0))  # Wednesday
        warnings = monitor.on_bar(datetime(2024, 1, 2, 14, 0))  # 4hr gap
        assert len(warnings) == 1
        assert "gap" in warnings[0].lower()
        assert len(sink.alerts) == 1

    def test_no_gap_alert_on_weekend(self) -> None:
        monitor = HealthMonitor(max_bar_gap_minutes=30)
        # Saturday
        monitor.on_bar(datetime(2024, 1, 6, 10, 0))
        warnings = monitor.on_bar(datetime(2024, 1, 6, 14, 0))
        assert len(warnings) == 0

    def test_fill_tracking(self) -> None:
        monitor = HealthMonitor()
        monitor.on_bar(datetime(2024, 1, 1, 10, 0))
        snap = monitor.snapshot()
        assert snap.bars_since_last_fill == 1
        monitor.on_fill()
        snap = monitor.snapshot()
        assert snap.bars_since_last_fill == 0

    def test_stale_detection(self) -> None:
        monitor = HealthMonitor(stale_bars_threshold=5)
        for i in range(10):
            monitor.on_bar(datetime(2024, 1, 1, 10, i))
        snap = monitor.snapshot()
        assert snap.stale_data_flag

    def test_risk_status_degrades_when_locked(self) -> None:
        monitor = HealthMonitor()
        monitor.on_state_change(OperationalState.LOCKED, datetime(2024, 1, 1))
        snap = monitor.snapshot()
        assert snap.risk_status == ComponentStatus.DEGRADED

    def test_risk_status_error_when_stopped(self) -> None:
        monitor = HealthMonitor()
        monitor.on_state_change(OperationalState.STOPPED, datetime(2024, 1, 1))
        snap = monitor.snapshot()
        assert snap.risk_status == ComponentStatus.ERROR

    def test_state_change_emits_alert(self) -> None:
        sink = CollectingAlertSink()
        monitor = HealthMonitor(alert_sink=sink)
        monitor.on_state_change(OperationalState.THROTTLED, datetime(2024, 1, 1))
        assert len(sink.alerts) == 1
        assert "throttled" in sink.alerts[0].message.lower()
