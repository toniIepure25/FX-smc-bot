"""Session breakout baseline strategy.

Enter on break of Asian session range during London or New York session.
SL at opposite session extreme. This tests whether SMC adds value
over simple session-range breakout trading.
"""

from __future__ import annotations

from datetime import datetime, time

from fx_smc_bot.config import PAIR_PIP_INFO, SessionConfig, Timeframe
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    SessionName,
    SessionWindow,
    SignalFamily,
    StructureSnapshot,
    TradeCandidate,
)
from fx_smc_bot.utils.time import classify_session


class SessionBreakoutDetector:
    """Breakout of Asian session range.

    Parameters
    ----------
    rr_ratio : reward/risk ratio for TP placement
    buffer_pips : pip buffer beyond session extreme for entry confirmation
    """

    def __init__(self, rr_ratio: float = 2.0, buffer_pips: float = 3.0) -> None:
        self._rr_ratio = rr_ratio
        self._buffer_pips = buffer_pips

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        snap = ctx.ltf_snapshot
        cfg = session_cfg or SessionConfig()
        current_session = classify_session(current_time, cfg)

        # Only trade during London or New York
        if current_session not in (SessionName.LONDON, SessionName.NEW_YORK,
                                    SessionName.LONDON_NY_OVERLAP):
            return []

        asian_windows = [
            w for w in snap.session_windows
            if w.session_name == SessionName.ASIAN
        ]
        if not asian_windows:
            return []

        # Use most recent Asian session
        asian = asian_windows[-1]
        if asian.high <= asian.low or asian.high == 0:
            return []

        pip_size = PAIR_PIP_INFO[snap.pair][0]
        buffer = self._buffer_pips * pip_size
        asian_range = asian.high - asian.low
        candidates: list[TradeCandidate] = []

        if current_price > asian.high + buffer:
            entry = current_price
            sl = asian.low
            risk = entry - sl
            if risk > pip_size:
                tp = entry + risk * self._rr_ratio
                candidates.append(self._make_candidate(
                    snap, Direction.LONG, entry, sl, tp, current_time,
                ))

        elif current_price < asian.low - buffer:
            entry = current_price
            sl = asian.high
            risk = sl - entry
            if risk > pip_size:
                tp = entry - risk * self._rr_ratio
                candidates.append(self._make_candidate(
                    snap, Direction.SHORT, entry, sl, tp, current_time,
                ))

        return candidates

    def _make_candidate(
        self, snap: StructureSnapshot, direction: Direction,
        entry: float, sl: float, tp: float, ts: datetime,
    ) -> TradeCandidate:
        return TradeCandidate(
            pair=snap.pair, direction=direction,
            family=SignalFamily.SESSION_RAID,
            timestamp=ts, entry=entry, stop_loss=sl, take_profit=tp,
            signal_score=0.5,
            structure_score=0.3, liquidity_score=0.3,
            execution_timeframe=snap.timeframe,
            context_timeframe=snap.timeframe,
            tags=["baseline", "session_breakout"],
        )
