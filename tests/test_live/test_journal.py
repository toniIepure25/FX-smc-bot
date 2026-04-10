"""Tests for EventJournal append/read functionality."""

from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.live.journal import EventJournal, JournalEvent


class TestJournalEvent:
    def test_roundtrip_json(self) -> None:
        evt = JournalEvent(
            event_type="signal",
            timestamp="2024-01-01T10:00:00",
            run_id="test_run",
            data={"pair": "EURUSD", "score": 0.75},
        )
        json_str = evt.to_json()
        restored = JournalEvent.from_json(json_str)
        assert restored.event_type == "signal"
        assert restored.data["pair"] == "EURUSD"


class TestEventJournal:
    def test_log_and_read(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "test.jsonl", "run_001")
        journal.log("test_event", {"key": "value"})
        journal.log("test_event", {"key": "value2"})
        assert journal.event_count == 2

        events = journal.read_events()
        assert len(events) == 2
        assert events[0].event_type == "test_event"

    def test_filter_by_type(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "test.jsonl", "run_001")
        journal.log_signal("EURUSD", "long", "sweep_reversal", 0.8)
        journal.log_order("ord_1", "EURUSD", "long", "market", 10000)
        journal.log_fill("ord_1", 1.1000, 10000, "market_open")

        signals = journal.read_events("signal")
        assert len(signals) == 1
        orders = journal.read_events("order")
        assert len(orders) == 1
        fills = journal.read_events("fill")
        assert len(fills) == 1

    def test_log_state_transition(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "test.jsonl", "run_001")
        journal.log_state_transition("active", "locked", "daily stop hit")
        events = journal.read_events("state_transition")
        assert len(events) == 1
        assert events[0].data["old"] == "active"

    def test_log_alert(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "test.jsonl", "run_001")
        journal.log_alert("WARNING", "Drawdown approaching limit")
        events = journal.read_events("alert")
        assert len(events) == 1
