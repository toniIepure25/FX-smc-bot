"""Core domain models for the FX SMC framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from fx_smc_bot.config import Timeframe, TradingPair


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalFamily(str, Enum):
    SWEEP_REVERSAL = "sweep_reversal"
    BOS_CONTINUATION = "bos_continuation"
    FVG_RETRACE = "fvg_retrace"
    SESSION_RAID = "session_raid"
    ORDER_BLOCK_MITIGATION = "order_block_mitigation"


@dataclass(slots=True)
class MarketBar:
    pair: TradingPair
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    spread: float | None = None


@dataclass(slots=True)
class TradeCandidate:
    pair: TradingPair
    direction: Direction
    family: SignalFamily
    timestamp: datetime
    entry: float
    stop_loss: float
    take_profit: float
    signal_score: float
    structure_score: float
    liquidity_score: float
    execution_timeframe: Timeframe
    context_timeframe: Timeframe
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PositionIntent:
    candidate: TradeCandidate
    risk_fraction: float
    units: float
    notional: float
    portfolio_weight: float


__all__ = [
    "Direction",
    "MarketBar",
    "PositionIntent",
    "SignalFamily",
    "TradeCandidate",
]
