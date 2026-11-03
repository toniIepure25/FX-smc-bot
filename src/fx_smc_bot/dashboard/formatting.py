"""Small display-only formatting helpers for the research dashboard."""

from __future__ import annotations

import math


def compact_money(value: float) -> str:
    """Format a currency amount without hiding its sign."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:,.1f}k"
    return f"{sign}${value:,.0f}"


def finite(value: float, fallback: str = "—") -> str:
    """Format a number, returning a placeholder for NaN/infinity."""
    return fallback if not math.isfinite(value) else f"{value:,.2f}"


def compact_pct(value: float, digits: int = 1) -> str:
    """Format a fraction as a percentage."""
    return f"{value * 100:.{digits}f}%"
