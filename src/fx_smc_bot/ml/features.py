"""Feature engineering from structure state.

Extracts numerical feature vectors from StructureSnapshot for use in
ML models (regime classification, trade quality scoring, meta-labeling).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.domain import (
    Direction,
    StructureRegime,
    StructureSnapshot,
    SwingType,
)


@dataclass(slots=True)
class StructureFeatures:
    """Numerical feature vector derived from a StructureSnapshot."""
    regime_bullish: float
    regime_bearish: float
    swing_high_count: int
    swing_low_count: int
    active_fvg_count: int
    active_ob_count: int
    liquidity_level_count: int
    displacement_count: int
    recent_bos_count: int
    recent_choch_count: int
    avg_fvg_size_atr: float
    avg_swing_strength: float

    def to_array(self) -> NDArray[np.float64]:
        return np.array([
            self.regime_bullish,
            self.regime_bearish,
            self.swing_high_count,
            self.swing_low_count,
            self.active_fvg_count,
            self.active_ob_count,
            self.liquidity_level_count,
            self.displacement_count,
            self.recent_bos_count,
            self.recent_choch_count,
            self.avg_fvg_size_atr,
            self.avg_swing_strength,
        ], dtype=np.float64)


def extract_features(snapshot: StructureSnapshot) -> StructureFeatures:
    """Extract ML features from a structure snapshot."""
    from fx_smc_bot.domain import BreakType

    regime_bull = 1.0 if snapshot.regime == StructureRegime.BULLISH else 0.0
    regime_bear = 1.0 if snapshot.regime == StructureRegime.BEARISH else 0.0

    sh_count = sum(1 for s in snapshot.swings if s.swing_type == SwingType.HIGH)
    sl_count = sum(1 for s in snapshot.swings if s.swing_type == SwingType.LOW)

    bos_count = sum(1 for b in snapshot.breaks if b.break_type == BreakType.BOS)
    choch_count = sum(1 for b in snapshot.breaks if b.break_type == BreakType.CHOCH)

    avg_fvg = 0.0
    if snapshot.active_fvgs:
        avg_fvg = sum(f.size_atr for f in snapshot.active_fvgs) / len(snapshot.active_fvgs)

    avg_strength = 0.0
    if snapshot.swings:
        avg_strength = sum(s.strength for s in snapshot.swings) / len(snapshot.swings)

    return StructureFeatures(
        regime_bullish=regime_bull,
        regime_bearish=regime_bear,
        swing_high_count=sh_count,
        swing_low_count=sl_count,
        active_fvg_count=len(snapshot.active_fvgs),
        active_ob_count=len(snapshot.active_order_blocks),
        liquidity_level_count=len(snapshot.liquidity_levels),
        displacement_count=len(snapshot.displacements),
        recent_bos_count=bos_count,
        recent_choch_count=choch_count,
        avg_fvg_size_atr=avg_fvg,
        avg_swing_strength=avg_strength,
    )
