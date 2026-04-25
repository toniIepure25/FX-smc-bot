"""Trade ledger: records completed trades, equity curve, exposure history."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import PAIR_PIP_INFO
from fx_smc_bot.domain import (
    ClosedTrade,
    Direction,
    EquityPoint,
    Position,
    SessionName,
    SignalFamily,
)
from fx_smc_bot.utils.math import price_to_pips


class TradeLedger:
    """Accumulates closed trades and equity snapshots during a backtest."""

    def __init__(self) -> None:
        self._trades: list[ClosedTrade] = []
        self._equity_curve: list[EquityPoint] = []

    @property
    def trades(self) -> list[ClosedTrade]:
        return list(self._trades)

    @property
    def equity_curve(self) -> list[EquityPoint]:
        return list(self._equity_curve)

    def record_trade(
        self,
        position: Position,
        exit_price: float,
        close_time: datetime,
        entry_bar: int = 0,
        exit_bar: int = 0,
        regime: str | None = None,
        session: SessionName | None = None,
    ) -> ClosedTrade:
        """Record a completed trade from a closed position."""
        if position.direction == Direction.LONG:
            pnl = (exit_price - position.entry_price) * position.units
        else:
            pnl = (position.entry_price - exit_price) * position.units

        pnl_pips = price_to_pips(
            abs(exit_price - position.entry_price), position.pair,
        )
        if (position.direction == Direction.LONG and exit_price < position.entry_price) or \
           (position.direction == Direction.SHORT and exit_price > position.entry_price):
            pnl_pips = -pnl_pips

        risk_dist = abs(position.entry_price - position.stop_loss)
        reward_dist = abs(exit_price - position.entry_price)
        rr = reward_dist / risk_dist if risk_dist > 0 else 0.0
        if pnl < 0:
            rr = -rr

        family = SignalFamily.SWEEP_REVERSAL
        tags: list[str] = []
        if position.candidate:
            family = position.candidate.family
            tags = position.candidate.tags

        trade = ClosedTrade(
            position=position,
            family=family,
            pair=position.pair,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=exit_price,
            units=position.units,
            pnl=pnl,
            pnl_pips=pnl_pips,
            opened_at=position.opened_at or close_time,
            closed_at=close_time,
            duration_bars=max(exit_bar - entry_bar, 1),
            reward_risk_ratio=rr,
            session=session,
            regime=regime,
            tags=tags,
        )
        self._trades.append(trade)
        return trade

    def record_equity(self, point: EquityPoint) -> None:
        self._equity_curve.append(point)
