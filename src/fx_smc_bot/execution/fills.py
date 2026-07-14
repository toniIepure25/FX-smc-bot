"""Fill simulation: determine when and at what price orders get filled.

Handles market, limit, and stop orders with proper lifecycle management.
Supports configurable fill policies for intrabar SL/TP conflict resolution.
"""

from __future__ import annotations

import random
from datetime import datetime

from fx_smc_bot.config import FillPolicy
from fx_smc_bot.domain import (
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
)
from fx_smc_bot.execution.slippage import (
    FixedSpreadSlippage,
    NativeBidAskSlippage,
    SlippageModel,
)


class FillEngine:
    """Processes orders against incoming bar data to produce fills.

    Supports three fill policies for SL/TP conflict resolution:
    - CONSERVATIVE: SL checked first (worst-case, default)
    - OPTIMISTIC: TP checked first
    - RANDOM: random order each bar (for Monte Carlo testing)
    """

    def __init__(
        self,
        slippage: SlippageModel | None = None,
        fill_policy: FillPolicy = FillPolicy.CONSERVATIVE,
        rng_seed: int | None = None,
    ) -> None:
        self._slippage = slippage or FixedSpreadSlippage()
        self._fill_policy = fill_policy
        self._rng = random.Random(rng_seed)

    def process_pending_orders(
        self,
        orders: list[Order],
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_time: datetime,
    ) -> list[tuple[Order, Fill]]:
        """Check each pending order against the current bar and fill if conditions met."""
        fills: list[tuple[Order, Fill]] = []

        for order in orders:
            if order.state != OrderState.PENDING:
                continue

            if order.expires_at and bar_time >= order.expires_at:
                order.state = OrderState.EXPIRED
                continue

            fill = self._try_fill(order, bar_open, bar_high, bar_low, bar_time)
            if fill is not None:
                order.state = OrderState.FILLED
                fills.append((order, fill))

        return fills

    def check_exit_conditions(
        self,
        position: Position,
        bar_high: float,
        bar_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        """Check if an open position hits SL or TP on the current bar.

        Uses the configured fill policy to resolve ambiguity when both
        SL and TP are within the bar's range.
        """
        if not position.is_open:
            return None

        sl_hit = self._sl_triggered(position, bar_high, bar_low)
        tp_hit = self._tp_triggered(position, bar_high, bar_low)

        if sl_hit and tp_hit:
            return self._resolve_conflict(position, bar_time)
        if sl_hit:
            return self._make_sl_fill(position, bar_time)
        if tp_hit:
            return self._make_tp_fill(position, bar_time)

        return None

    def check_same_bar_exit(
        self,
        position: Position,
        fill_price: float,
        bar_high: float,
        bar_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        """Check SL/TP on the fill bar for a newly filled position.

        After a limit order fill on bar N, we check whether the remaining
        bar range could have hit SL or TP.  For CONSERVATIVE policy,
        this only triggers SL.
        """
        if not position.is_open:
            return None

        if self._fill_policy == FillPolicy.OPTIMISTIC:
            tp_hit = self._tp_triggered(position, bar_high, bar_low)
            if tp_hit:
                return self._make_tp_fill(position, bar_time)

        sl_hit = self._sl_triggered(position, bar_high, bar_low)
        if sl_hit:
            return self._make_sl_fill(position, bar_time)

        return None

    def _sl_triggered(self, pos: Position, bar_high: float, bar_low: float) -> bool:
        if pos.direction == Direction.LONG:
            return bar_low <= pos.stop_loss
        return bar_high >= pos.stop_loss

    def _tp_triggered(self, pos: Position, bar_high: float, bar_low: float) -> bool:
        if pos.direction == Direction.LONG:
            return bar_high >= pos.take_profit
        return bar_low <= pos.take_profit

    def _resolve_conflict(self, pos: Position, bar_time: datetime) -> Fill:
        """Both SL and TP within bar range -- use fill policy to decide."""
        if self._fill_policy == FillPolicy.CONSERVATIVE:
            return self._make_sl_fill(pos, bar_time)
        elif self._fill_policy == FillPolicy.OPTIMISTIC:
            return self._make_tp_fill(pos, bar_time)
        else:
            if self._rng.random() < 0.5:
                return self._make_sl_fill(pos, bar_time)
            return self._make_tp_fill(pos, bar_time)

    def _make_sl_fill(self, pos: Position, bar_time: datetime) -> Fill:
        exit_dir = Direction.SHORT if pos.direction == Direction.LONG else Direction.LONG
        fill_price, spread, slip = self._slippage.apply(
            pos.stop_loss, exit_dir, pos.pair,
        )
        return Fill(
            order_id=pos.id, fill_price=fill_price,
            units=pos.units, spread_cost=spread,
            slippage=slip, timestamp=bar_time,
            reason=FillReason.STOP_LOSS_HIT,
        )

    def _make_tp_fill(self, pos: Position, bar_time: datetime) -> Fill:
        exit_dir = Direction.SHORT if pos.direction == Direction.LONG else Direction.LONG
        fill_price, spread, slip = self._slippage.apply(
            pos.take_profit, exit_dir, pos.pair,
        )
        return Fill(
            order_id=pos.id, fill_price=fill_price,
            units=pos.units, spread_cost=spread,
            slippage=slip, timestamp=bar_time,
            reason=FillReason.TAKE_PROFIT_HIT,
        )

    def _try_fill(
        self,
        order: Order,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        if order.order_type == OrderType.MARKET:
            fill_price, spread, slip = self._slippage.apply(
                bar_open, order.direction, order.pair,
            )
            return Fill(
                order_id=order.id, fill_price=fill_price,
                units=order.units, spread_cost=spread,
                slippage=slip, timestamp=bar_time,
                reason=FillReason.MARKET_OPEN,
            )

        if order.order_type == OrderType.LIMIT:
            if order.direction == Direction.LONG and bar_low <= order.requested_price:
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.LIMIT_TOUCHED,
                )
            if order.direction == Direction.SHORT and bar_high >= order.requested_price:
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.LIMIT_TOUCHED,
                )

        if order.order_type == OrderType.STOP:
            if order.direction == Direction.LONG and bar_high >= order.requested_price:
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.STOP_TRIGGERED,
                )
            if order.direction == Direction.SHORT and bar_low <= order.requested_price:
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.STOP_TRIGGERED,
                )

        return None  # no fill condition met


class BidAskFillEngine:
    """Fill engine using native bid/ask prices.

    Entry rules:
      LONG limit at L fills when ask_low <= L  (buy at ask)
      SHORT limit at L fills when bid_high >= L  (sell at bid)
    Exit rules:
      LONG SL/TP checked against bid prices (sell at bid)
      SHORT SL/TP checked against ask prices (buy at ask)
    Market orders:
      LONG filled at ask_open; SHORT filled at bid_open
    """

    def __init__(
        self,
        slippage: SlippageModel | None = None,
        fill_policy: FillPolicy = FillPolicy.CONSERVATIVE,
        rng_seed: int | None = None,
    ) -> None:
        self._slippage = slippage or NativeBidAskSlippage()
        self._fill_policy = fill_policy
        self._rng = random.Random(rng_seed)

    def process_pending_orders(
        self,
        orders: list[Order],
        bid_open: float, bid_high: float, bid_low: float, bid_close: float,
        ask_open: float, ask_high: float, ask_low: float, ask_close: float,
        bar_time: datetime,
    ) -> list[tuple[Order, Fill]]:
        fills: list[tuple[Order, Fill]] = []
        for order in orders:
            if order.state != OrderState.PENDING:
                continue
            if order.expires_at and bar_time >= order.expires_at:
                order.state = OrderState.EXPIRED
                continue
            fill = self._try_fill_bidask(
                order,
                bid_open, bid_high, bid_low,
                ask_open, ask_high, ask_low,
                bar_time,
            )
            if fill is not None:
                order.state = OrderState.FILLED
                fills.append((order, fill))
        return fills

    def check_exit_conditions_bidask(
        self,
        position: Position,
        bid_high: float, bid_low: float,
        ask_high: float, ask_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        if not position.is_open:
            return None

        sl_hit = self._sl_triggered_bidask(
            position, bid_high, bid_low, ask_high, ask_low,
        )
        tp_hit = self._tp_triggered_bidask(
            position, bid_high, bid_low, ask_high, ask_low,
        )

        if sl_hit and tp_hit:
            return self._resolve_conflict_bidask(position, bar_time)
        if sl_hit:
            return self._make_sl_fill_bidask(position, bar_time)
        if tp_hit:
            return self._make_tp_fill_bidask(position, bar_time)
        return None

    def check_same_bar_exit_bidask(
        self,
        position: Position,
        fill_price: float,
        bid_high: float, bid_low: float,
        ask_high: float, ask_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        if not position.is_open:
            return None
        if self._fill_policy == FillPolicy.OPTIMISTIC:
            if self._tp_triggered_bidask(
                position, bid_high, bid_low, ask_high, ask_low,
            ):
                return self._make_tp_fill_bidask(position, bar_time)
        if self._sl_triggered_bidask(
            position, bid_high, bid_low, ask_high, ask_low,
        ):
            return self._make_sl_fill_bidask(position, bar_time)
        return None

    def _sl_triggered_bidask(
        self, pos: Position,
        bid_high: float, bid_low: float,
        ask_high: float, ask_low: float,
    ) -> bool:
        if pos.direction == Direction.LONG:
            return bid_low <= pos.stop_loss
        return ask_high >= pos.stop_loss

    def _tp_triggered_bidask(
        self, pos: Position,
        bid_high: float, bid_low: float,
        ask_high: float, ask_low: float,
    ) -> bool:
        if pos.direction == Direction.LONG:
            return bid_high >= pos.take_profit
        return ask_low <= pos.take_profit

    def _resolve_conflict_bidask(
        self, pos: Position, bar_time: datetime,
    ) -> Fill:
        if self._fill_policy == FillPolicy.CONSERVATIVE:
            return self._make_sl_fill_bidask(pos, bar_time)
        elif self._fill_policy == FillPolicy.OPTIMISTIC:
            return self._make_tp_fill_bidask(pos, bar_time)
        else:
            if self._rng.random() < 0.5:
                return self._make_sl_fill_bidask(pos, bar_time)
            return self._make_tp_fill_bidask(pos, bar_time)

    def _make_sl_fill_bidask(
        self, pos: Position, bar_time: datetime,
    ) -> Fill:
        exit_dir = (
            Direction.SHORT if pos.direction == Direction.LONG
            else Direction.LONG
        )
        fill_price, spread, slip = self._slippage.apply(
            pos.stop_loss, exit_dir, pos.pair,
        )
        return Fill(
            order_id=pos.id, fill_price=fill_price,
            units=pos.units, spread_cost=spread,
            slippage=slip, timestamp=bar_time,
            reason=FillReason.STOP_LOSS_HIT,
        )

    def _make_tp_fill_bidask(
        self, pos: Position, bar_time: datetime,
    ) -> Fill:
        exit_dir = (
            Direction.SHORT if pos.direction == Direction.LONG
            else Direction.LONG
        )
        fill_price, spread, slip = self._slippage.apply(
            pos.take_profit, exit_dir, pos.pair,
        )
        return Fill(
            order_id=pos.id, fill_price=fill_price,
            units=pos.units, spread_cost=spread,
            slippage=slip, timestamp=bar_time,
            reason=FillReason.TAKE_PROFIT_HIT,
        )

    def _try_fill_bidask(
        self,
        order: Order,
        bid_open: float, bid_high: float, bid_low: float,
        ask_open: float, ask_high: float, ask_low: float,
        bar_time: datetime,
    ) -> Fill | None:
        if order.order_type == OrderType.MARKET:
            base = ask_open if order.direction == Direction.LONG else bid_open
            fill_price, spread, slip = self._slippage.apply(
                base, order.direction, order.pair,
            )
            return Fill(
                order_id=order.id, fill_price=fill_price,
                units=order.units, spread_cost=spread,
                slippage=slip, timestamp=bar_time,
                reason=FillReason.MARKET_OPEN,
            )

        if order.order_type == OrderType.LIMIT:
            if (order.direction == Direction.LONG
                    and ask_low <= order.requested_price):
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.LIMIT_TOUCHED,
                )
            if (order.direction == Direction.SHORT
                    and bid_high >= order.requested_price):
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.LIMIT_TOUCHED,
                )

        if order.order_type == OrderType.STOP:
            if (order.direction == Direction.LONG
                    and ask_high >= order.requested_price):
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.STOP_TRIGGERED,
                )
            if (order.direction == Direction.SHORT
                    and bid_low <= order.requested_price):
                fill_price, spread, slip = self._slippage.apply(
                    order.requested_price, order.direction, order.pair,
                )
                return Fill(
                    order_id=order.id, fill_price=fill_price,
                    units=order.units, spread_cost=spread,
                    slippage=slip, timestamp=bar_time,
                    reason=FillReason.STOP_TRIGGERED,
                )

        return None
