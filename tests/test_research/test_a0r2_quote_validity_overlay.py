"""Tests for the A0R2 crossed-quote execution validity overlay."""

from __future__ import annotations

from fx_smc_bot.research.a0r2_quote_validity_overlay import (
    OVERLAY_ID,
    M1Quote,
    quote_is_valid,
    resolve_entry_quote,
    resolve_invalid_exit_quote,
)


def test_crossed_quote_is_invalid() -> None:
    assert not quote_is_valid(M1Quote("t0", bid=1.2, ask=1.1))


def test_invalid_entry_quote_is_no_fill_without_substitution() -> None:
    quotes = [
        M1Quote("t0", bid=1.2, ask=1.1),
        M1Quote("t1", bid=1.0, ask=1.1),
    ]

    decision = resolve_entry_quote(quotes, 0, direction="long")

    assert decision.overlay_id == OVERLAY_ID
    assert not decision.fill_allowed
    assert decision.quote_index == 0
    assert decision.forward_fill_used is False
    assert decision.synthetic_spread_used is False
    assert decision.reason == "INVALID_ENTRY_QUOTE_NO_FILL"


def test_invalid_ordinary_exit_waits_for_later_adverse_valid_quote() -> None:
    quotes = [
        M1Quote("t0", bid=1.2, ask=1.1),
        M1Quote("t1", bid=1.11, ask=1.12),
        M1Quote("t2", bid=1.08, ask=1.09),
    ]

    decision = resolve_invalid_exit_quote(
        quotes,
        0,
        direction="long",
        reference_price=1.10,
    )

    assert decision.fill_allowed
    assert decision.timestamp == "t2"
    assert decision.price == 1.08
    assert decision.integrity_breach is False
    assert decision.forward_fill_used is False
    assert decision.synthetic_spread_used is False


def test_invalid_mandatory_flat_uses_next_valid_quote_and_flags_breach() -> None:
    quotes = [
        M1Quote("t0", bid=1.2, ask=1.1),
        M1Quote("t1", bid=1.11, ask=1.12),
    ]

    decision = resolve_invalid_exit_quote(
        quotes,
        0,
        direction="short",
        reference_price=1.10,
        mandatory_flat=True,
    )

    assert decision.fill_allowed
    assert decision.timestamp == "t1"
    assert decision.price == 1.12
    assert decision.integrity_breach
    assert decision.reason == "INVALID_MANDATORY_FLAT_QUOTE_NEXT_VALID_SIDE_CORRECT"
