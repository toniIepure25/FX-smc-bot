"""Order creation helpers."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.domain import (
    Direction,
    Order,
    OrderType,
    PositionIntent,
)


def intent_to_order(
    intent: PositionIntent,
    order_type: OrderType = OrderType.MARKET,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> Order:
    """Convert a PositionIntent into a concrete Order."""
    tc = intent.candidate
    return Order(
        pair=tc.pair,
        direction=tc.direction,
        order_type=order_type,
        requested_price=tc.entry,
        stop_loss=tc.stop_loss,
        take_profit=tc.take_profit,
        units=intent.units,
        created_at=created_at or tc.timestamp,
        expires_at=expires_at,
        candidate=tc,
    )
