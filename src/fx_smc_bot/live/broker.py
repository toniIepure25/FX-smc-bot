"""Broker adapter protocol and paper broker implementation.

BrokerAdapter defines the minimal interface for order submission, cancellation,
position queries, and account state. PaperBroker implements this using the
existing FillEngine for simulated execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from fx_smc_bot.config import ExecutionConfig, TradingPair
from fx_smc_bot.domain import (
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    PositionState,
)
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.slippage import (
    FixedSpreadSlippage,
    SlippageModel,
    SpreadFromDataSlippage,
    VolatilitySlippage,
)


@dataclass(slots=True, frozen=True)
class AccountState:
    equity: float
    cash: float
    unrealized_pnl: float
    open_position_count: int
    pending_order_count: int
    timestamp: datetime | None = None


@runtime_checkable
class BrokerAdapter(Protocol):
    def submit_order(self, order: Order) -> str:
        """Submit order, return order ID."""
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if cancelled."""
        ...

    def get_positions(self) -> list[Position]:
        """Return all open positions."""
        ...

    def get_account(self) -> AccountState:
        """Return current account state."""
        ...

    def process_bar(
        self,
        pair: TradingPair,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> list[Fill]:
        """Process a bar: fill pending orders, check exits. Return fills."""
        ...


class PaperBroker:
    """Simulated broker for paper trading and replay."""

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        execution_config: ExecutionConfig | None = None,
        slippage_model: str = "fixed",
    ) -> None:
        self._cash = initial_capital
        self._initial_capital = initial_capital
        cfg = execution_config or ExecutionConfig()
        slippage = self._build_slippage_model(slippage_model, cfg)
        self._fill_engine = FillEngine(slippage, fill_policy=cfg.fill_policy)
        self._positions: dict[str, Position] = {}
        self._pending_orders: dict[str, Order] = {}
        self._fills: list[Fill] = []

    @staticmethod
    def _build_slippage_model(model_name: str, cfg: ExecutionConfig) -> SlippageModel:
        if model_name == "volatility":
            return VolatilitySlippage(config=cfg)
        if model_name == "spread_from_data":
            return SpreadFromDataSlippage(cfg)
        return FixedSpreadSlippage(cfg)

    @property
    def cash(self) -> float:
        return self._cash

    def submit_order(self, order: Order) -> str:
        if not order.id:
            order.id = uuid.uuid4().hex[:12]
        order.state = OrderState.PENDING
        self._pending_orders[order.id] = order
        return order.id

    def cancel_order(self, order_id: str) -> bool:
        order = self._pending_orders.pop(order_id, None)
        if order:
            order.state = OrderState.CANCELLED
            return True
        return False

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.is_open]

    def get_account(self) -> AccountState:
        unrealized = sum(
            p.unrealized_pnl(p.entry_price)
            for p in self._positions.values()
            if p.is_open
        )
        return AccountState(
            equity=self._cash + unrealized,
            cash=self._cash,
            unrealized_pnl=unrealized,
            open_position_count=len(self.get_positions()),
            pending_order_count=len(self._pending_orders),
        )

    def process_bar(
        self,
        pair: TradingPair,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> list[Fill]:
        """Process one bar: fill pending orders and check exits."""
        bar_fills: list[Fill] = []

        for pos in list(self._positions.values()):
            if not pos.is_open or pos.pair != pair:
                continue
            exit_fill = self._fill_engine.check_exit_conditions(
                pos, high, low, timestamp,
            )
            if exit_fill is not None:
                pos.exit_fill = exit_fill
                pos.closed_at = timestamp
                pos.state = PositionState.CLOSED
                if pos.direction == Direction.LONG:
                    pnl = (exit_fill.fill_price - pos.entry_price) * pos.units
                else:
                    pnl = (pos.entry_price - exit_fill.fill_price) * pos.units
                pos.pnl = pnl
                self._cash += pnl
                bar_fills.append(exit_fill)

        pair_orders = [o for o in self._pending_orders.values() if o.pair == pair]
        filled_results = self._fill_engine.process_pending_orders(
            pair_orders, open_, high, low, close, timestamp,
        )
        for order, fill in filled_results:
            pos = Position(
                pair=order.pair,
                direction=order.direction,
                entry_price=fill.fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                units=fill.units,
                entry_fill=fill,
                opened_at=timestamp,
                candidate=order.candidate,
            )
            self._positions[pos.id] = pos
            self._pending_orders.pop(order.id, None)
            order.state = OrderState.FILLED
            bar_fills.append(fill)

        return bar_fills

    @property
    def all_closed_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if not p.is_open]
