"""Generic causal event-state machine for intraday strategies.

Each strategy instance tracks its lifecycle from IDLE through
a sequence of confirmed events to ORDER_PENDING, FILLED, and
terminal states. Every transition emits a StrategyEvent with
both the event timestamp and the information-availability timestamp.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import Direction, FVGZone, LiquidityLevel, SwingPoint


class StrategyState(str, Enum):
    IDLE = "idle"
    LEVEL_AVAILABLE = "level_available"
    LEVEL_BREACHED = "level_breached"
    RECLAIM_CONFIRMED = "reclaim_confirmed"
    ACCEPTANCE_CONFIRMED = "acceptance_confirmed"
    MSS_CONFIRMED = "mss_confirmed"
    DISPLACEMENT_CONFIRMED = "displacement_confirmed"
    RANGE_COMPLETE = "range_complete"
    BREAKOUT_CONFIRMED = "breakout_confirmed"
    FVG_CREATED = "fvg_created"
    ORDER_PENDING = "order_pending"
    FILLED = "filled"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CLOSED = "closed"


TERMINAL_STATES = frozenset({
    StrategyState.INVALIDATED,
    StrategyState.EXPIRED,
    StrategyState.CLOSED,
})


@dataclass(frozen=True, slots=True)
class StrategyEvent:
    """Record of a single state transition."""

    timestamp: datetime
    info_available_at: datetime
    state_from: StrategyState
    state_to: StrategyState
    source_bar_index: int
    strategy_instance_id: str
    liquidity_level_id: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyInstance:
    """A single lifecycle of one strategy attempt."""

    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    family: str = ""
    pair: TradingPair = TradingPair.EURUSD
    direction: Direction = Direction.LONG
    state: StrategyState = StrategyState.IDLE
    created_at: datetime | None = None
    events: list[StrategyEvent] = field(default_factory=list)

    liquidity_level: LiquidityLevel | None = None
    liquidity_level_id: str | None = None
    sweep_extreme: float | None = None
    sweep_bar: int | None = None
    reclaim_bar: int | None = None
    mss_swing: SwingPoint | None = None
    mss_bar: int | None = None
    displacement_bar: int | None = None
    fvg: FVGZone | None = None
    fvg_bar: int | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    invalidation_reason: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(
        self,
        new_state: StrategyState,
        bar_index: int,
        timestamp: datetime,
        info_available_at: datetime | None = None,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> StrategyEvent:
        """Perform a state transition and record the event."""
        event = StrategyEvent(
            timestamp=timestamp,
            info_available_at=info_available_at or timestamp,
            state_from=self.state,
            state_to=new_state,
            source_bar_index=bar_index,
            strategy_instance_id=self.instance_id,
            liquidity_level_id=self.liquidity_level_id,
            reason=reason,
            metadata=metadata or {},
        )
        self.state = new_state
        self.events.append(event)
        return event


class StrategyTracker:
    """Manages active and completed strategy instances.

    Enforces the rule that one liquidity level can only have one active
    (non-terminal) instance at a time.
    """

    def __init__(self) -> None:
        self._active: dict[str, StrategyInstance] = {}
        self._completed: list[StrategyInstance] = []

    @property
    def active_instances(self) -> list[StrategyInstance]:
        return list(self._active.values())

    @property
    def completed_instances(self) -> list[StrategyInstance]:
        return list(self._completed)

    @property
    def all_events(self) -> list[StrategyEvent]:
        events: list[StrategyEvent] = []
        for inst in self._active.values():
            events.extend(inst.events)
        for inst in self._completed:
            events.extend(inst.events)
        events.sort(key=lambda e: e.timestamp)
        return events

    def has_active_for_level(self, level_id: str) -> bool:
        for inst in self._active.values():
            if inst.liquidity_level_id == level_id and not inst.is_terminal:
                return True
        return False

    def register(self, instance: StrategyInstance) -> None:
        if instance.liquidity_level_id and self.has_active_for_level(
            instance.liquidity_level_id
        ):
            raise ValueError(
                f"Level {instance.liquidity_level_id} already has an active instance"
            )
        self._active[instance.instance_id] = instance

    def finalize(self, instance_id: str) -> None:
        inst = self._active.pop(instance_id, None)
        if inst is not None:
            self._completed.append(inst)

    def cleanup_terminal(self) -> None:
        terminal_ids = [
            iid for iid, inst in self._active.items() if inst.is_terminal
        ]
        for iid in terminal_ids:
            self.finalize(iid)
