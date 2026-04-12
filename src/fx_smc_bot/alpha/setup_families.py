"""Setup family definitions: formalized SMC/ICT trade setups.

Each family encodes a specific market scenario into a systematic rule set
that produces (or rejects) a TradeCandidate from the current StructureSnapshot.

Families
--------
1. **Sweep Reversal**: liquidity sweep + displacement + FVG/OB entry
2. **BOS Continuation**: BOS in HTF direction + pullback to FVG/OB
3. **FVG Retrace**: price returns to unfilled FVG in trend direction
4. **Session Raid**: session high/low swept + reversal structure
5. **OB Mitigation**: price reaches unmitigated OB with confirming structure
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fx_smc_bot.config import PAIR_PIP_INFO, Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    MultiTimeframeContext,
    OrderBlock,
    SignalFamily,
    StructureBreak,
    StructureRegime,
    StructureSnapshot,
    TradeCandidate,
)
from fx_smc_bot.alpha.scoring import (
    composite_score,
    score_fvg_quality,
    score_htf_alignment,
    score_liquidity_sweep,
    score_ob_quality,
    score_session_timing,
)
from fx_smc_bot.utils.time import classify_session
from fx_smc_bot.config import SessionConfig


class SetupDetector(Protocol):
    """Interface for a setup family detector."""
    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]: ...


class SweepReversalDetector:
    """Liquidity sweep + displacement + entry at FVG or OB."""

    def __init__(self, scoring_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)) -> None:
        self._weights = scoring_weights

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        ltf = ctx.ltf_snapshot
        candidates: list[TradeCandidate] = []

        swept_levels = [l for l in ltf.liquidity_levels if l.swept]
        if not swept_levels:
            return []

        for level in swept_levels:
            direction = _sweep_reversal_direction(level)
            if direction is None:
                continue
            if ctx.htf_bias is not None and ctx.htf_bias != direction:
                continue

            entry_zone = _find_entry_zone(ltf, direction)
            if entry_zone is None:
                continue

            entry, sl, tp = _compute_levels(entry_zone, direction, current_price, ltf.pair)
            if entry is None:
                continue

            session = classify_session(current_time, session_cfg or SessionConfig())
            struct_score = score_htf_alignment(ctx.htf_bias, direction)
            liq_score = score_liquidity_sweep(level)
            sess_score = score_session_timing(session)

            candidates.append(TradeCandidate(
                pair=ltf.pair, direction=direction,
                family=SignalFamily.SWEEP_REVERSAL,
                timestamp=current_time,
                entry=entry, stop_loss=sl, take_profit=tp,
                signal_score=composite_score(struct_score, liq_score, sess_score, self._weights),
                structure_score=struct_score,
                liquidity_score=liq_score,
                execution_timeframe=ltf.timeframe,
                context_timeframe=ctx.htf_snapshot.timeframe,
                tags=["sweep_reversal"],
            ))

        return candidates


class BOSContinuationDetector:
    """BOS in HTF direction + pullback to FVG/OB."""

    def __init__(self, scoring_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)) -> None:
        self._weights = scoring_weights

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        if ctx.htf_bias is None:
            return []

        ltf = ctx.ltf_snapshot
        recent_breaks = [b for b in ltf.breaks if b.direction == ctx.htf_bias]
        if not recent_breaks:
            return []

        entry_zone = _find_entry_zone(ltf, ctx.htf_bias)
        if entry_zone is None:
            return []

        entry, sl, tp = _compute_levels(entry_zone, ctx.htf_bias, current_price, ltf.pair)
        if entry is None:
            return []

        session = classify_session(current_time, session_cfg or SessionConfig())
        struct_score = 0.8
        liq_score = 0.3
        sess_score = score_session_timing(session)

        return [TradeCandidate(
            pair=ltf.pair, direction=ctx.htf_bias,
            family=SignalFamily.BOS_CONTINUATION,
            timestamp=current_time,
            entry=entry, stop_loss=sl, take_profit=tp,
            signal_score=composite_score(struct_score, liq_score, sess_score, self._weights),
            structure_score=struct_score,
            liquidity_score=liq_score,
            execution_timeframe=ltf.timeframe,
            context_timeframe=ctx.htf_snapshot.timeframe,
            tags=["bos_continuation"],
        )]


class FVGRetraceDetector:
    """Price returns to unfilled FVG in the current trend direction."""

    def __init__(self, scoring_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)) -> None:
        self._weights = scoring_weights

    def scan(
        self,
        ctx: MultiTimeframeContext,
        current_price: float,
        current_time: datetime,
        session_cfg: SessionConfig | None = None,
    ) -> list[TradeCandidate]:
        ltf = ctx.ltf_snapshot
        if ltf.regime == StructureRegime.RANGING:
            return []

        direction = Direction.LONG if ltf.regime == StructureRegime.BULLISH else Direction.SHORT
        aligned_fvgs = [f for f in ltf.active_fvgs
                        if f.direction == direction and not f.invalidated]

        candidates: list[TradeCandidate] = []
        for fvg in aligned_fvgs:
            in_zone = (fvg.low <= current_price <= fvg.high)
            if not in_zone:
                continue

            entry = current_price
            pip_size = PAIR_PIP_INFO[ltf.pair][0]
            if direction == Direction.LONG:
                sl = fvg.low - 10 * pip_size
                tp = entry + (entry - sl) * 2.5
            else:
                sl = fvg.high + 10 * pip_size
                tp = entry - (sl - entry) * 2.5

            session = classify_session(current_time, session_cfg or SessionConfig())
            struct_score = score_htf_alignment(ctx.htf_bias, direction)
            fvg_score = score_fvg_quality(fvg)
            sess_score = score_session_timing(session)

            candidates.append(TradeCandidate(
                pair=ltf.pair, direction=direction,
                family=SignalFamily.FVG_RETRACE,
                timestamp=current_time,
                entry=entry, stop_loss=sl, take_profit=tp,
                signal_score=composite_score(struct_score, fvg_score, sess_score, self._weights),
                structure_score=struct_score,
                liquidity_score=fvg_score,
                execution_timeframe=ltf.timeframe,
                context_timeframe=ctx.htf_snapshot.timeframe,
                tags=["fvg_retrace"],
            ))

        return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sweep_reversal_direction(level: LiquidityLevel) -> Direction | None:
    from fx_smc_bot.domain import LiquidityLevelType
    if level.level_type in (LiquidityLevelType.EQUAL_HIGHS,
                            LiquidityLevelType.SESSION_HIGH,
                            LiquidityLevelType.PRIOR_DAY_HIGH,
                            LiquidityLevelType.PRIOR_WEEK_HIGH):
        return Direction.SHORT
    if level.level_type in (LiquidityLevelType.EQUAL_LOWS,
                            LiquidityLevelType.SESSION_LOW,
                            LiquidityLevelType.PRIOR_DAY_LOW,
                            LiquidityLevelType.PRIOR_WEEK_LOW):
        return Direction.LONG
    return None


def _find_entry_zone(
    snap: StructureSnapshot,
    direction: Direction,
) -> FVGZone | OrderBlock | None:
    """Find the best FVG or OB for entry in the given direction."""
    # Prefer FVG first, then OB
    fvgs = [f for f in snap.active_fvgs if f.direction == direction and not f.invalidated]
    if fvgs:
        return max(fvgs, key=lambda f: f.size_atr)

    obs = [ob for ob in snap.active_order_blocks if ob.direction == direction and not ob.invalidated]
    if obs:
        return obs[-1]

    return None


def _compute_levels(
    zone: FVGZone | OrderBlock,
    direction: Direction,
    current_price: float,
    pair: TradingPair,
) -> tuple[float | None, float, float]:
    """Compute entry, stop loss, and take profit from an entry zone."""
    pip_size = PAIR_PIP_INFO[pair][0]

    if direction == Direction.LONG:
        entry = zone.low + (zone.high - zone.low) * 0.5
        sl = zone.low - 10 * pip_size
        risk = entry - sl
        tp = entry + risk * 2.5
    else:
        entry = zone.high - (zone.high - zone.low) * 0.5
        sl = zone.high + 10 * pip_size
        risk = sl - entry
        tp = entry - risk * 2.5

    if risk <= 0:
        return None, 0.0, 0.0

    return round(entry, 5), round(sl, 5), round(tp, 5)
