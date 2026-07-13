"""Tests for the generic causal state machine framework."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.alpha.intraday.state_machine import (
    StrategyEvent,
    StrategyInstance,
    StrategyState,
    StrategyTracker,
    TERMINAL_STATES,
)
from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import Direction


class TestStrategyInstance:

    def test_initial_state_is_idle(self):
        inst = StrategyInstance()
        assert inst.state == StrategyState.IDLE
        assert not inst.is_terminal

    def test_transition_records_event(self):
        inst = StrategyInstance()
        event = inst.transition(
            StrategyState.LEVEL_AVAILABLE,
            bar_index=10,
            timestamp=datetime(2024, 1, 2, 8, 0),
            reason="level found",
        )
        assert inst.state == StrategyState.LEVEL_AVAILABLE
        assert len(inst.events) == 1
        assert event.state_from == StrategyState.IDLE
        assert event.state_to == StrategyState.LEVEL_AVAILABLE
        assert event.reason == "level found"

    def test_terminal_states(self):
        for state in TERMINAL_STATES:
            inst = StrategyInstance()
            inst.transition(state, 0, datetime(2024, 1, 1))
            assert inst.is_terminal

    def test_multiple_transitions(self):
        inst = StrategyInstance()
        ts = datetime(2024, 1, 2, 8, 0)
        inst.transition(StrategyState.LEVEL_AVAILABLE, 1, ts)
        inst.transition(StrategyState.LEVEL_BREACHED, 5, ts)
        inst.transition(StrategyState.RECLAIM_CONFIRMED, 7, ts)
        assert len(inst.events) == 3
        assert inst.state == StrategyState.RECLAIM_CONFIRMED

    def test_event_metadata(self):
        inst = StrategyInstance()
        event = inst.transition(
            StrategyState.LEVEL_BREACHED, 5,
            datetime(2024, 1, 2, 8, 0),
            metadata={"extreme": 1.1050},
        )
        assert event.metadata["extreme"] == 1.1050


class TestStrategyTracker:

    def test_register_and_list(self):
        tracker = StrategyTracker()
        inst = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst)
        assert len(tracker.active_instances) == 1

    def test_no_duplicate_for_same_level(self):
        tracker = StrategyTracker()
        inst1 = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst1)
        inst2 = StrategyInstance(liquidity_level_id="L1")
        with pytest.raises(ValueError, match="already has an active"):
            tracker.register(inst2)

    def test_finalize_moves_to_completed(self):
        tracker = StrategyTracker()
        inst = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst)
        tracker.finalize(inst.instance_id)
        assert len(tracker.active_instances) == 0
        assert len(tracker.completed_instances) == 1

    def test_cleanup_terminal(self):
        tracker = StrategyTracker()
        inst = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst)
        inst.transition(StrategyState.INVALIDATED, 0, datetime(2024, 1, 1))
        tracker.cleanup_terminal()
        assert len(tracker.active_instances) == 0
        assert len(tracker.completed_instances) == 1

    def test_can_register_new_after_terminal(self):
        tracker = StrategyTracker()
        inst1 = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst1)
        inst1.transition(StrategyState.INVALIDATED, 0, datetime(2024, 1, 1))
        tracker.cleanup_terminal()

        inst2 = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst2)
        assert len(tracker.active_instances) == 1

    def test_all_events_sorted(self):
        tracker = StrategyTracker()
        inst = StrategyInstance(liquidity_level_id="L1")
        tracker.register(inst)
        inst.transition(StrategyState.LEVEL_AVAILABLE, 1, datetime(2024, 1, 2, 8, 0))
        inst.transition(StrategyState.LEVEL_BREACHED, 5, datetime(2024, 1, 2, 9, 0))
        events = tracker.all_events
        assert len(events) == 2
        assert events[0].timestamp <= events[1].timestamp
