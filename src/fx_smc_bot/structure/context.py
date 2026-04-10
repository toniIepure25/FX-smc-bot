"""Multi-timeframe context assembly.

Combines all structure primitives for a single pair/timeframe into a
StructureSnapshot, and pairs HTF + LTF snapshots into a MultiTimeframeContext
for the alpha layer.
"""

from __future__ import annotations

import numpy as np

from fx_smc_bot.config import StructureConfig, SessionConfig, TradingPair, Timeframe
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    StructureRegime,
    StructureSnapshot,
)
from fx_smc_bot.structure.swings import detect_swings
from fx_smc_bot.structure.market_structure import detect_structure_breaks, current_regime
from fx_smc_bot.structure.displacement import detect_displacement
from fx_smc_bot.structure.fvg import detect_fvg, update_fvg_fill
from fx_smc_bot.structure.order_blocks import detect_order_blocks
from fx_smc_bot.structure.liquidity import detect_equal_levels
from fx_smc_bot.structure.sessions import track_session_windows


def build_structure_snapshot(
    series: BarSeries,
    structure_cfg: StructureConfig | None = None,
    session_cfg: SessionConfig | None = None,
) -> StructureSnapshot:
    """Compute full structure state for a single pair/timeframe up to the last bar."""
    s_cfg = structure_cfg or StructureConfig()
    sess_cfg = session_cfg or SessionConfig()

    swings = detect_swings(
        series.high, series.low, series.close, series.timestamps, config=s_cfg,
    )

    breaks = detect_structure_breaks(
        swings, series.close, series.timestamps,
    )
    regime = current_regime(breaks)

    displacements = detect_displacement(
        series.open, series.high, series.low, series.close,
        series.timestamps, config=s_cfg,
    )

    fvgs = detect_fvg(
        series.high, series.low, series.close, series.timestamps, config=s_cfg,
    )
    fvgs = update_fvg_fill(
        fvgs, series.high, series.low,
        up_to_bar=len(series) - 1, max_fill_pct=s_cfg.fvg_max_fill_pct,
    )
    active_fvgs = [f for f in fvgs if not f.invalidated]

    obs = detect_order_blocks(
        series.open, series.high, series.low, series.close,
        series.timestamps, displacements, breaks, config=s_cfg,
    )
    active_obs = [ob for ob in obs if not ob.invalidated]

    liquidity = detect_equal_levels(swings, series.pair, config=s_cfg)
    session_windows = track_session_windows(
        series.high, series.low, series.timestamps, config=sess_cfg,
    )

    return StructureSnapshot(
        pair=series.pair,
        timeframe=series.timeframe,
        bar_index=len(series) - 1,
        regime=regime,
        swings=swings,
        breaks=breaks,
        liquidity_levels=liquidity,
        active_fvgs=active_fvgs,
        active_order_blocks=active_obs,
        displacements=displacements,
        session_windows=session_windows,
    )


def build_mtf_context(
    htf_series: BarSeries,
    ltf_series: BarSeries,
    structure_cfg: StructureConfig | None = None,
    session_cfg: SessionConfig | None = None,
) -> MultiTimeframeContext:
    """Build a MultiTimeframeContext from HTF and LTF bar series."""
    htf_snap = build_structure_snapshot(htf_series, structure_cfg, session_cfg)
    ltf_snap = build_structure_snapshot(ltf_series, structure_cfg, session_cfg)

    htf_bias: Direction | None = None
    if htf_snap.regime == StructureRegime.BULLISH:
        htf_bias = Direction.LONG
    elif htf_snap.regime == StructureRegime.BEARISH:
        htf_bias = Direction.SHORT

    return MultiTimeframeContext(
        pair=htf_series.pair,
        htf_snapshot=htf_snap,
        ltf_snapshot=ltf_snap,
        htf_bias=htf_bias,
    )
