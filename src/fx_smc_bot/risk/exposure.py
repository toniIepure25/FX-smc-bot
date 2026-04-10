"""Currency exposure calculation.

Computes net exposure per currency across all open positions,
enabling constraints on directional USD exposure and overall
currency concentration.
"""

from __future__ import annotations

from fx_smc_bot.config import PAIR_CURRENCIES
from fx_smc_bot.domain import Direction, Position


def compute_currency_exposures(
    positions: list[Position],
) -> dict[str, float]:
    """Return net signed exposure per currency across all open positions.

    Positive = long that currency, negative = short that currency.
    Units are in the position's native units (e.g., 100k = 1 standard lot).
    """
    exposures: dict[str, float] = {}

    for pos in positions:
        if not pos.is_open:
            continue

        base, quote = PAIR_CURRENCIES[pos.pair]
        signed_units = pos.units if pos.direction == Direction.LONG else -pos.units

        # Long EURUSD = long EUR, short USD
        exposures[base] = exposures.get(base, 0.0) + signed_units
        exposures[quote] = exposures.get(quote, 0.0) - signed_units

    return exposures


def net_usd_exposure(positions: list[Position]) -> float:
    """Return net USD exposure (positive = long USD, negative = short USD)."""
    exp = compute_currency_exposures(positions)
    return exp.get("USD", 0.0)
