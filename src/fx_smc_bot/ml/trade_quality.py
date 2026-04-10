"""Trade quality scorer.

Scores individual trade candidates based on historical feature patterns.
Provides a Protocol for ML-based scoring and a rule-based baseline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fx_smc_bot.domain import TradeCandidate
from fx_smc_bot.ml.features import StructureFeatures


@runtime_checkable
class TradeQualityScorer(Protocol):
    def score(
        self,
        candidate: TradeCandidate,
        features: StructureFeatures,
    ) -> float:
        """Return a quality score in [0, 1]."""
        ...


class RuleBasedQualityScorer:
    """Baseline scorer using simple heuristics from structure features."""

    def score(
        self,
        candidate: TradeCandidate,
        features: StructureFeatures,
    ) -> float:
        score = 0.0

        # Regime alignment
        if candidate.direction.value == "long" and features.regime_bullish > 0:
            score += 0.3
        elif candidate.direction.value == "short" and features.regime_bearish > 0:
            score += 0.3

        # Active FVGs suggest institutional interest
        if features.active_fvg_count > 0:
            score += min(features.active_fvg_count * 0.1, 0.2)

        # Displacement confirms momentum
        if features.displacement_count > 0:
            score += 0.15

        # Recent structure breaks
        if features.recent_bos_count > 0:
            score += 0.15

        # Base signal quality from the candidate itself
        score += candidate.signal_score * 0.2

        return min(score, 1.0)
