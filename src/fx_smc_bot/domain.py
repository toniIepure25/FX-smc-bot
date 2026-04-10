"""Core domain models for the FX SMC framework.

All value objects and entities used across the system. Domain objects use
frozen dataclasses for immutability and slots for memory efficiency.
Configuration objects live in config.py (Pydantic).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

from fx_smc_bot.config import Timeframe, TradingPair


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalFamily(str, Enum):
    SWEEP_REVERSAL = "sweep_reversal"
    BOS_CONTINUATION = "bos_continuation"
    FVG_RETRACE = "fvg_retrace"
    SESSION_RAID = "session_raid"
    ORDER_BLOCK_MITIGATION = "order_block_mitigation"


class SwingType(str, Enum):
    HIGH = "swing_high"
    LOW = "swing_low"


class BreakType(str, Enum):
    BOS = "bos"
    CHOCH = "choch"


class StructureRegime(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


class LiquidityLevelType(str, Enum):
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"
    PRIOR_DAY_HIGH = "prior_day_high"
    PRIOR_DAY_LOW = "prior_day_low"
    PRIOR_WEEK_HIGH = "prior_week_high"
    PRIOR_WEEK_LOW = "prior_week_low"


class SessionName(str, Enum):
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NY_OVERLAP = "london_ny_overlap"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderState(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PositionState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class FillReason(str, Enum):
    MARKET_OPEN = "market_open"
    LIMIT_TOUCHED = "limit_touched"
    STOP_TRIGGERED = "stop_triggered"
    STOP_LOSS_HIT = "stop_loss_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    MANUAL_CLOSE = "manual_close"
    EXPIRY = "expiry"


class StructureLevel(str, Enum):
    """Whether a structure observation is internal (minor) or external (major)."""
    INTERNAL = "internal"
    EXTERNAL = "external"


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MarketBar:
    pair: TradingPair
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    bar_index: int = 0
    volume: float | None = None
    spread: float | None = None


# ---------------------------------------------------------------------------
# Structure primitives
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class SwingPoint:
    bar_index: int
    price: float
    swing_type: SwingType
    timestamp: datetime
    strength: int = 1


@dataclass(slots=True, frozen=True)
class StructureBreak:
    break_type: BreakType
    direction: Direction
    level: StructureLevel
    swing_broken: SwingPoint
    break_bar_index: int
    break_price: float
    timestamp: datetime


@dataclass(slots=True, frozen=True)
class LiquidityLevel:
    price: float
    level_type: LiquidityLevelType
    touch_count: int
    formation_index: int
    formation_time: datetime
    swept: bool = False
    sweep_index: int | None = None


@dataclass(slots=True, frozen=True)
class DisplacementCandle:
    bar_index: int
    timestamp: datetime
    direction: Direction
    body_size: float
    range_size: float
    atr_multiple: float
    body_efficiency: float


@dataclass(slots=True, frozen=True)
class FVGZone:
    high: float
    low: float
    direction: Direction
    bar_index: int
    timestamp: datetime
    size_atr: float
    filled_pct: float = 0.0
    invalidated: bool = False


@dataclass(slots=True, frozen=True)
class OrderBlock:
    high: float
    low: float
    direction: Direction
    bar_index: int
    timestamp: datetime
    confirmed: bool = False
    mitigated_pct: float = 0.0
    invalidated: bool = False


@dataclass(slots=True, frozen=True)
class SessionWindow:
    session_name: SessionName
    date: datetime
    open_time: datetime
    close_time: datetime
    high: float = 0.0
    low: float = float("inf")
    high_index: int = -1
    low_index: int = -1


# ---------------------------------------------------------------------------
# Structure context (aggregated per pair/timeframe)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StructureSnapshot:
    """Aggregated structure state for a single pair and timeframe at a point in time."""
    pair: TradingPair
    timeframe: Timeframe
    bar_index: int
    regime: StructureRegime = StructureRegime.RANGING
    swings: list[SwingPoint] = field(default_factory=list)
    breaks: list[StructureBreak] = field(default_factory=list)
    liquidity_levels: list[LiquidityLevel] = field(default_factory=list)
    active_fvgs: list[FVGZone] = field(default_factory=list)
    active_order_blocks: list[OrderBlock] = field(default_factory=list)
    displacements: list[DisplacementCandle] = field(default_factory=list)
    session_windows: list[SessionWindow] = field(default_factory=list)


@dataclass(slots=True)
class MultiTimeframeContext:
    """Combines higher-timeframe bias with lower-timeframe execution detail."""
    pair: TradingPair
    htf_snapshot: StructureSnapshot
    ltf_snapshot: StructureSnapshot
    htf_bias: Direction | None = None


# ---------------------------------------------------------------------------
# Trade candidates
# ---------------------------------------------------------------------------

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
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_distance(self) -> float:
        return abs(self.entry - self.stop_loss)

    @property
    def reward_distance(self) -> float:
        return abs(self.take_profit - self.entry)

    @property
    def reward_risk_ratio(self) -> float:
        rd = self.risk_distance
        if rd == 0:
            return 0.0
        return self.reward_distance / rd


# ---------------------------------------------------------------------------
# Execution lifecycle
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Order:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    pair: TradingPair = TradingPair.EURUSD
    direction: Direction = Direction.LONG
    order_type: OrderType = OrderType.MARKET
    state: OrderState = OrderState.PENDING
    requested_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    units: float = 0.0
    created_at: datetime | None = None
    expires_at: datetime | None = None
    candidate: TradeCandidate | None = None


@dataclass(slots=True)
class Fill:
    order_id: str
    fill_price: float
    units: float
    spread_cost: float
    slippage: float
    timestamp: datetime
    reason: FillReason


@dataclass(slots=True)
class Position:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    pair: TradingPair = TradingPair.EURUSD
    direction: Direction = Direction.LONG
    state: PositionState = PositionState.OPEN
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    units: float = 0.0
    entry_fill: Fill | None = None
    exit_fill: Fill | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    pnl: float = 0.0
    pnl_pips: float = 0.0
    candidate: TradeCandidate | None = None

    @property
    def is_open(self) -> bool:
        return self.state == PositionState.OPEN

    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == Direction.LONG:
            return (current_price - self.entry_price) * self.units
        return (self.entry_price - current_price) * self.units


# ---------------------------------------------------------------------------
# Risk / sizing
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PositionIntent:
    candidate: TradeCandidate
    risk_fraction: float
    units: float
    notional: float
    portfolio_weight: float


@dataclass(slots=True, frozen=True)
class RiskSnapshot:
    timestamp: datetime
    equity: float
    open_risk: float
    daily_drawdown: float
    weekly_drawdown: float
    peak_equity: float
    throttle_factor: float
    open_position_count: int
    currency_exposures: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Portfolio state
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PortfolioSnapshot:
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions: list[Position] = field(default_factory=list)
    pending_orders: list[Order] = field(default_factory=list)
    risk_snapshot: RiskSnapshot | None = None


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ClosedTrade:
    """A fully resolved trade with entry and exit."""
    position: Position
    family: SignalFamily
    pair: TradingPair
    direction: Direction
    entry_price: float
    exit_price: float
    units: float
    pnl: float
    pnl_pips: float
    opened_at: datetime
    closed_at: datetime
    duration_bars: int
    reward_risk_ratio: float
    session: SessionName | None = None
    regime: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EquityPoint:
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    drawdown: float
    drawdown_pct: float


@dataclass(slots=True)
class BacktestResult:
    config_hash: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_equity: float
    trades: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "BacktestResult",
    "BreakType",
    "ClosedTrade",
    "Direction",
    "DisplacementCandle",
    "EquityPoint",
    "FVGZone",
    "Fill",
    "FillReason",
    "LiquidityLevel",
    "LiquidityLevelType",
    "MarketBar",
    "MultiTimeframeContext",
    "Order",
    "OrderBlock",
    "OrderState",
    "OrderType",
    "Position",
    "PositionIntent",
    "PositionState",
    "PortfolioSnapshot",
    "RiskSnapshot",
    "SessionName",
    "SessionWindow",
    "SignalFamily",
    "StructureBreak",
    "StructureLevel",
    "StructureRegime",
    "StructureSnapshot",
    "SwingPoint",
    "SwingType",
    "TradeCandidate",
]
