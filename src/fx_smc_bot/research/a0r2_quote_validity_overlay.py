"""A0R2 execution overlay for invalid side-correct M1 quotes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

OVERLAY_ID = "A0R2_EXECUTABLE_M1_QUOTE_VALIDITY_OVERLAY_V1"

Direction = Literal["long", "short"]
FillKind = Literal["entry", "ordinary_exit", "mandatory_flat"]


@dataclass(frozen=True, slots=True)
class M1Quote:
    timestamp: object
    bid: float
    ask: float


@dataclass(frozen=True, slots=True)
class OverlayFillDecision:
    overlay_id: str
    fill_allowed: bool
    fill_kind: FillKind
    timestamp: object | None = None
    price: float | None = None
    quote_index: int | None = None
    integrity_breach: bool = False
    reason: str = ""
    forward_fill_used: bool = False
    synthetic_spread_used: bool = False


def quote_is_valid(quote: M1Quote) -> bool:
    """A side-correct execution quote is valid only when bid/ask are finite and uncrossed."""
    return isfinite(quote.bid) and isfinite(quote.ask) and quote.bid <= quote.ask


def side_correct_price(quote: M1Quote, direction: Direction, fill_kind: FillKind) -> float:
    if fill_kind == "entry":
        return quote.ask if direction == "long" else quote.bid
    return quote.bid if direction == "long" else quote.ask


def resolve_entry_quote(
    quotes: Sequence[M1Quote],
    index: int,
    *,
    direction: Direction,
) -> OverlayFillDecision:
    """Invalid entry quote means no fill; later quotes are not substituted."""
    quote = quotes[index]
    if not quote_is_valid(quote):
        return OverlayFillDecision(
            overlay_id=OVERLAY_ID,
            fill_allowed=False,
            fill_kind="entry",
            quote_index=index,
            integrity_breach=True,
            reason="INVALID_ENTRY_QUOTE_NO_FILL",
        )
    return OverlayFillDecision(
        overlay_id=OVERLAY_ID,
        fill_allowed=True,
        fill_kind="entry",
        timestamp=quote.timestamp,
        price=side_correct_price(quote, direction, "entry"),
        quote_index=index,
        reason="VALID_ENTRY_QUOTE",
    )


def resolve_invalid_exit_quote(
    quotes: Sequence[M1Quote],
    index: int,
    *,
    direction: Direction,
    reference_price: float,
    mandatory_flat: bool = False,
) -> OverlayFillDecision:
    """Resolve invalid exits without forward-filling or synthesizing spread."""
    fill_kind: FillKind = "mandatory_flat" if mandatory_flat else "ordinary_exit"
    for candidate_index in range(index + 1, len(quotes)):
        quote = quotes[candidate_index]
        if not quote_is_valid(quote):
            continue
        price = side_correct_price(quote, direction, fill_kind)
        adverse = price <= reference_price if direction == "long" else price >= reference_price
        if mandatory_flat or adverse:
            return OverlayFillDecision(
                overlay_id=OVERLAY_ID,
                fill_allowed=True,
                fill_kind=fill_kind,
                timestamp=quote.timestamp,
                price=price,
                quote_index=candidate_index,
                integrity_breach=mandatory_flat,
                reason=(
                    "INVALID_MANDATORY_FLAT_QUOTE_NEXT_VALID_SIDE_CORRECT"
                    if mandatory_flat
                    else "INVALID_EXIT_QUOTE_NEXT_ADVERSE_VALID_SIDE_CORRECT"
                ),
            )
    return OverlayFillDecision(
        overlay_id=OVERLAY_ID,
        fill_allowed=False,
        fill_kind=fill_kind,
        quote_index=index,
        integrity_breach=mandatory_flat,
        reason=(
            "INVALID_MANDATORY_FLAT_QUOTE_NO_LATER_VALID_SIDE_CORRECT"
            if mandatory_flat
            else "INVALID_EXIT_QUOTE_NO_LATER_ADVERSE_VALID_SIDE_CORRECT"
        ),
    )
