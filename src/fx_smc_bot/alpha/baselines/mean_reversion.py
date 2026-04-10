"""Mean reversion baseline strategy.

Fade moves beyond 2-sigma from an N-period mean. SL at 3-sigma, TP at mean.
Tests whether SMC/ICT adds value beyond simple statistical mean-reversion.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from fx_smc_bot.config import PAIR_PIP_INFO, SessionConfig
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    SignalFamily,
    StructureSnapshot,
    TradeCandidate,
)


class MeanReversionDetector:
    """Bollinger-band-style mean reversion.

    Parameters
    ----------
    lookback : period for the rolling mean and standard deviation
    entry_sigma : standard deviations from mean to trigger entry
    sl_sigma : standard deviations from mean for stop loss
    """

    def __init__(
        self,
        lookback: int = 50,
        entry_sigma: float = 2.0,
        sl_sigma: float = 3.0,
    ) -> None:
        self._lookback = lookback
        self._entry_sigma = entry_sigma
        self._sl_sigma = sl_sigma

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        snap = ctx.ltf_snapshot
        if snap.bar_index < self._lookback + 5:
            return []

        # Reconstruct recent closes from swings (simplified heuristic)
        # In production, the detector would receive the actual BarSeries
        # Here we use available structure data as proxy
        swings = snap.swings
        if len(swings) < 10:
            return []

        prices = [s.price for s in swings[-self._lookback:]]
        if len(prices) < 10:
            return []

        mean = float(np.mean(prices))
        std = float(np.std(prices))
        if std == 0:
            return []

        pip_size = PAIR_PIP_INFO[snap.pair][0]
        z_score = (current_price - mean) / std
        candidates: list[TradeCandidate] = []

        if z_score > self._entry_sigma:
            entry = current_price
            sl = mean + self._sl_sigma * std
            tp = mean
            if sl - entry > pip_size and entry - tp > pip_size:
                candidates.append(self._make_candidate(
                    snap, Direction.SHORT, entry, sl, tp, current_time,
                ))

        elif z_score < -self._entry_sigma:
            entry = current_price
            sl = mean - self._sl_sigma * std
            tp = mean
            if entry - sl > pip_size and tp - entry > pip_size:
                candidates.append(self._make_candidate(
                    snap, Direction.LONG, entry, sl, tp, current_time,
                ))

        return candidates

    def _make_candidate(
        self, snap: StructureSnapshot, direction: Direction,
        entry: float, sl: float, tp: float, ts: datetime,
    ) -> TradeCandidate:
        return TradeCandidate(
            pair=snap.pair, direction=direction,
            family=SignalFamily.FVG_RETRACE,
            timestamp=ts, entry=entry, stop_loss=sl, take_profit=tp,
            signal_score=0.5,
            structure_score=0.3, liquidity_score=0.2,
            execution_timeframe=snap.timeframe,
            context_timeframe=snap.timeframe,
            tags=["baseline", "mean_reversion"],
        )
