"""Position sizing strategies.

All sizers implement the SizingStrategy protocol and return (units, risk_fraction)
for a given trade candidate and current portfolio state.

Implementations:
  - StopBasedSizer: fixed-fractional risk based on entry-SL distance
  - VolatilityAdjustedSizer: scales base risk by ATR regime
  - ScoreAwareSizer: modulates risk by signal quality score
  - CompositeSizer: chains multiple sizers (multiplicative adjustment)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fx_smc_bot.config import PAIR_PIP_INFO, BacktestConfig, RiskConfig
from fx_smc_bot.domain import TradeCandidate


@runtime_checkable
class SizingStrategy(Protocol):
    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> tuple[float, float]:
        """Return (units, risk_fraction)."""
        ...


class StopBasedSizer:
    """Fixed-fractional risk: risk = equity * base_risk_per_trade.

    Units = risk_amount / risk_distance_per_unit.
    For USD-quoted pairs, 1 pip per unit = pip_size * 1 unit.
    """

    def __init__(self, lot_size: float = 100_000.0) -> None:
        self._lot_size = lot_size

    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> tuple[float, float]:
        risk_fraction = risk_cfg.base_risk_per_trade
        risk_amount = equity * risk_fraction
        risk_dist = candidate.risk_distance

        if risk_dist <= 0:
            return 0.0, 0.0

        pip_size = PAIR_PIP_INFO[candidate.pair][0]
        risk_pips = risk_dist / pip_size
        pip_value = pip_size  # simplified for USD-quoted pairs

        if risk_pips <= 0:
            return 0.0, 0.0

        units = risk_amount / (risk_pips * pip_value)
        return round(units, 2), risk_fraction


class VolatilityAdjustedSizer:
    """Scale risk down when volatility is elevated relative to the median.

    If current ATR > median ATR, reduce position size proportionally.
    """

    def __init__(self, base_sizer: SizingStrategy | None = None) -> None:
        self._base = base_sizer or StopBasedSizer()

    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._base.compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
        )
        if not risk_cfg.volatility_risk_scaling:
            return units, risk_frac

        if current_atr is not None and median_atr is not None and median_atr > 0:
            vol_ratio = current_atr / median_atr
            if vol_ratio > 1.0:
                scale = 1.0 / vol_ratio
                units *= scale
                risk_frac *= scale

        return round(units, 2), risk_frac


class ScoreAwareSizer:
    """Modulate risk by signal quality score.

    Full score (1.0) => full risk.  Low score => scaled down by the
    `score_risk_modulation` parameter.
    """

    def __init__(self, base_sizer: SizingStrategy | None = None) -> None:
        self._base = base_sizer or StopBasedSizer()

    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._base.compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
        )
        mod = risk_cfg.score_risk_modulation
        # score_factor ranges from (1-mod) at score=0 to 1.0 at score=1
        score_factor = (1.0 - mod) + mod * candidate.signal_score
        units *= score_factor
        risk_frac *= score_factor
        return round(units, 2), risk_frac


class CompositeSizer:
    """Chain of sizers: applies adjustments multiplicatively."""

    def __init__(self, sizers: list[SizingStrategy]) -> None:
        if not sizers:
            raise ValueError("CompositeSizer requires at least one sizer")
        self._sizers = sizers

    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._sizers[0].compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
        )
        for sizer in self._sizers[1:]:
            u2, rf2 = sizer.compute(candidate, equity, risk_cfg, current_atr, median_atr)
            if u2 > 0 and units > 0:
                # Use the ratio as a scaling factor
                base_u, _ = self._sizers[0].compute(
                    candidate, equity, risk_cfg, current_atr, median_atr,
                )
                if base_u > 0:
                    scale = u2 / base_u
                    units *= scale
                    risk_frac *= scale
        return round(units, 2), risk_frac
