"""Momentum / trend-following baseline strategy.

Long when close > N-period high, short when close < N-period low.
SL and TP are ATR-based. This is the simplest trend-following
benchmark against which SMC complexity must justify itself.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from fx_smc_bot.config import PAIR_PIP_INFO, SessionConfig, Timeframe
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    SignalFamily,
    StructureSnapshot,
    TradeCandidate,
)


class MomentumDetector:
    """Simple channel breakout / momentum strategy.

    Parameters
    ----------
    lookback : periods for the high/low channel (Donchian-style)
    atr_sl_mult : ATR multiplier for stop loss distance
    atr_tp_mult : ATR multiplier for take profit distance
    """

    def __init__(
        self,
        lookback: int = 20,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 4.0,
    ) -> None:
        self._lookback = lookback
        self._atr_sl_mult = atr_sl_mult
        self._atr_tp_mult = atr_tp_mult

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        snap = ctx.ltf_snapshot
        if snap.bar_index < self._lookback + 14:
            return []

        candidates: list[TradeCandidate] = []
        swings = snap.swings
        if len(swings) < self._lookback:
            return []

        recent_highs = [s.price for s in swings if s.swing_type.value == "swing_high"][-self._lookback:]
        recent_lows = [s.price for s in swings if s.swing_type.value == "swing_low"][-self._lookback:]

        if not recent_highs or not recent_lows:
            return []

        channel_high = max(recent_highs)
        channel_low = min(recent_lows)

        pip_size = PAIR_PIP_INFO[snap.pair][0]
        # Use rough ATR estimate from channel width
        atr_est = (channel_high - channel_low) / max(self._lookback, 1) * 5

        if current_price > channel_high:
            sl = current_price - atr_est * self._atr_sl_mult
            tp = current_price + atr_est * self._atr_tp_mult
            if current_price - sl > pip_size:
                candidates.append(self._make_candidate(
                    snap, Direction.LONG, current_price, sl, tp, current_time,
                ))
        elif current_price < channel_low:
            sl = current_price + atr_est * self._atr_sl_mult
            tp = current_price - atr_est * self._atr_tp_mult
            if sl - current_price > pip_size:
                candidates.append(self._make_candidate(
                    snap, Direction.SHORT, current_price, sl, tp, current_time,
                ))

        return candidates

    def _make_candidate(
        self, snap: StructureSnapshot, direction: Direction,
        entry: float, sl: float, tp: float, ts: datetime,
    ) -> TradeCandidate:
        return TradeCandidate(
            pair=snap.pair, direction=direction,
            family=SignalFamily.BOS_CONTINUATION,
            timestamp=ts, entry=entry, stop_loss=sl, take_profit=tp,
            signal_score=0.5,  # baseline strategies get neutral score
            structure_score=0.5, liquidity_score=0.0,
            execution_timeframe=snap.timeframe,
            context_timeframe=snap.timeframe,
            tags=["baseline", "momentum"],
        )
