"""Portfolio state: tracks open positions, equity, and mark-to-market accounting."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.domain import (
    Direction,
    EquityPoint,
    Order,
    OrderState,
    Position,
    PositionState,
    PortfolioSnapshot,
)


class PortfolioState:
    """Mutable portfolio state maintained during a backtest or live session."""

    def __init__(self, initial_capital: float) -> None:
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._realized_pnl = 0.0
        self._positions: list[Position] = []
        self._pending_orders: list[Order] = []
        self._closed_positions: list[Position] = []
        self._peak_equity = initial_capital

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions if p.is_open]

    @property
    def closed_positions(self) -> list[Position]:
        return list(self._closed_positions)

    @property
    def pending_orders(self) -> list[Order]:
        return [o for o in self._pending_orders if o.state == OrderState.PENDING]

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Compute total unrealized PnL given current prices per pair."""
        total = 0.0
        for pos in self.open_positions:
            price = prices.get(pos.pair.value, pos.entry_price)
            total += pos.unrealized_pnl(price)
        return total

    def equity(self, prices: dict[str, float]) -> float:
        return self._cash + self.unrealized_pnl(prices)

    def add_order(self, order: Order) -> None:
        self._pending_orders.append(order)

    def open_position(self, position: Position) -> None:
        self._positions.append(position)

    def close_position(self, position_id: str, pnl: float) -> None:
        for pos in self._positions:
            if pos.id == position_id and pos.is_open:
                pos.state = PositionState.CLOSED
                pos.pnl = pnl
                self._realized_pnl += pnl
                self._cash += pnl
                self._closed_positions.append(pos)
                break

    def remove_order(self, order_id: str) -> None:
        self._pending_orders = [o for o in self._pending_orders if o.id != order_id]

    def snapshot(self, timestamp: datetime, prices: dict[str, float]) -> PortfolioSnapshot:
        eq = self.equity(prices)
        return PortfolioSnapshot(
            timestamp=timestamp,
            equity=eq,
            cash=self._cash,
            unrealized_pnl=self.unrealized_pnl(prices),
            realized_pnl=self._realized_pnl,
            open_positions=list(self.open_positions),
            pending_orders=list(self.pending_orders),
        )

    def equity_point(self, timestamp: datetime, prices: dict[str, float]) -> EquityPoint:
        eq = self.equity(prices)
        if eq > self._peak_equity:
            self._peak_equity = eq
        dd = max(0.0, self._peak_equity - eq)
        dd_pct = dd / self._peak_equity if self._peak_equity > 0 else 0.0
        return EquityPoint(
            timestamp=timestamp, equity=eq, cash=self._cash,
            unrealized_pnl=self.unrealized_pnl(prices),
            drawdown=dd, drawdown_pct=dd_pct,
        )
