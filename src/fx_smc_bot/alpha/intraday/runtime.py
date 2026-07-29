"""Stateful strategy runtime protocol and event types for V2 intraday strategies.

This module defines the interface between the backtest engine and
stateful intraday detectors. Each runtime instance is responsible for
one strategy family × pair × session and maintains state across bars.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import PAIR_PIP_INFO, Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    StructureSnapshot,
)


@dataclass(slots=True, frozen=True)
class CausalBarContext:
    """All information available to a strategy at the close of bar_idx."""
    pair: TradingPair
    timeframe: Timeframe
    bar_idx: int
    timestamp: datetime
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    atr: float
    spread: float
    snapshot: StructureSnapshot
    htf_bias: Direction | None = None
    htf_snapshot: StructureSnapshot | None = None


@dataclass(slots=True)
class OrderIntent:
    """A strategy's request to place an order."""
    intent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    family: str = ""
    pair: TradingPair = TradingPair.EURUSD
    direction: Direction = Direction.LONG
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    signal_bar: int = 0
    signal_timestamp: datetime | None = None
    activation_bar: int = 0
    expiry_bars: int = 20
    strategy_instance_id: str = ""
    level_id: str = ""
    fvg_id: str = ""
    session: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OrderAcceptedEvent:
    order_id: str
    intent_id: str
    timestamp: datetime


@dataclass(slots=True, frozen=True)
class OrderFilledEvent:
    order_id: str
    intent_id: str
    fill_price: float
    units: float
    timestamp: datetime
    position_id: str = ""


@dataclass(slots=True, frozen=True)
class OrderCancelledEvent:
    order_id: str
    intent_id: str
    reason: str
    timestamp: datetime


@dataclass(slots=True, frozen=True)
class PositionClosedEvent:
    position_id: str
    order_id: str
    intent_id: str
    exit_price: float
    pnl: float
    gross_pnl: float
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    swap_cost: float
    reason: str
    timestamp: datetime


@runtime_checkable
class StatefulStrategyRuntime(Protocol):
    """Protocol for V2 intraday strategy runtimes."""
    family: str
    pair: TradingPair
    session: str

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]: ...
    def on_order_accepted(self, event: OrderAcceptedEvent) -> None: ...
    def on_order_filled(self, event: OrderFilledEvent) -> None: ...
    def on_order_cancelled(self, event: OrderCancelledEvent) -> None: ...
    def on_position_closed(self, event: PositionClosedEvent) -> None: ...
    def snapshot_state(self) -> dict: ...
    def reset(self) -> None: ...


def pip_size(pair: TradingPair) -> float:
    """Return the pip size for a pair using PAIR_PIP_INFO."""
    info = PAIR_PIP_INFO.get(pair)
    if info is None:
        raise ValueError(f"No pip info for {pair.value}")
    return info[0]


def pips_to_price(pips: float, pair: TradingPair) -> float:
    """Convert a pip count to a price distance for the given pair."""
    return pips * pip_size(pair)


def config_hash(config: dict[str, Any]) -> str:
    """Deterministic SHA-256 of a configuration dict."""
    import json
    raw = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
