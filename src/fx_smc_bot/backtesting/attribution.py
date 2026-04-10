"""Attribution analysis: slice performance by pair, setup family, session, time period, regime."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import numpy as np

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import ClosedTrade, SessionName, SignalFamily


@dataclass(frozen=True, slots=True)
class AttributionSlice:
    label: str
    trade_count: int
    total_pnl: float
    win_rate: float
    avg_pnl: float
    avg_rr: float


def by_pair(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(trades, key=lambda t: t.pair.value)


def by_family(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(trades, key=lambda t: t.family.value)


def by_session(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(
        trades,
        key=lambda t: t.session.value if t.session else "unknown",
    )


def by_direction(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(trades, key=lambda t: t.direction.value)


def by_year(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(trades, key=lambda t: str(t.opened_at.year))


def by_month(trades: list[ClosedTrade]) -> list[AttributionSlice]:
    return _group_by(trades, key=lambda t: t.opened_at.strftime("%Y-%m"))


def by_regime(
    trades: list[ClosedTrade],
    regime_fn: Callable[[ClosedTrade], str] | None = None,
) -> list[AttributionSlice]:
    """Attribute trades by market regime (uses ClosedTrade.regime field)."""
    def default_regime(t: ClosedTrade) -> str:
        if t.regime:
            return t.regime
        for tag in t.tags:
            if tag.startswith("regime:"):
                return tag.split(":", 1)[1]
        return "unknown"

    key_fn = regime_fn or default_regime
    return _group_by(trades, key=key_fn)


def by_interaction(
    trades: list[ClosedTrade],
    key_a: Callable[[ClosedTrade], str],
    key_b: Callable[[ClosedTrade], str],
) -> list[AttributionSlice]:
    """Cross-dimensional attribution (e.g., pair x regime)."""
    return _group_by(trades, key=lambda t: f"{key_a(t)}|{key_b(t)}")


def _group_by(
    trades: list[ClosedTrade],
    key: Callable[[ClosedTrade], str],
) -> list[AttributionSlice]:
    groups: dict[str, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)

    slices: list[AttributionSlice] = []
    for label, group in sorted(groups.items()):
        pnls = [t.pnl for t in group]
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        slices.append(AttributionSlice(
            label=label,
            trade_count=n,
            total_pnl=sum(pnls),
            win_rate=wins / n if n > 0 else 0.0,
            avg_pnl=sum(pnls) / n if n > 0 else 0.0,
            avg_rr=float(np.mean([t.reward_risk_ratio for t in group])) if group else 0.0,
        ))
    return slices
