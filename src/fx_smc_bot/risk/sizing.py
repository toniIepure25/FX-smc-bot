"""Position sizing strategies and capital deployment policies.

All sizers implement the SizingStrategy protocol and return (units, risk_fraction)
for a given trade candidate and current portfolio state.

SizingPolicy classes transform raw equity into a reference equity for sizing,
decoupling position sizing from unbounded equity compounding.

Implementations:
  - StopBasedSizer: fixed-fractional risk based on entry-SL distance
  - VolatilityAdjustedSizer: scales base risk by ATR regime
  - ScoreAwareSizer: modulates risk by signal quality score
  - CompositeSizer: chains multiple sizers (multiplicative adjustment)

SizingPolicies:
  - FullCompounding: baseline (uses current equity as-is)
  - FixedInitial: always sizes from initial capital
  - CappedCompounding: equity capped at initial * multiplier
  - SteppedCompounding: quantized equity steps
  - DrawdownAwareSizing: reduces reference equity when in drawdown
  - VolatilityScaledSizing: scales by inverse ATR ratio
  - HybridPropSizing: capped at 2x initial with DD-aware dampening
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from fx_smc_bot.config import PAIR_PIP_INFO, BacktestConfig, RiskConfig
from fx_smc_bot.domain import TradeCandidate


# ---------------------------------------------------------------------------
# Sizing policies: transform current equity into reference equity
# ---------------------------------------------------------------------------

class SizingPolicy:
    """Base class for capital deployment policies.

    Transforms current_equity into reference_equity before it reaches the
    sizer.  The sizer mechanics stay unchanged; only the equity input varies.
    """

    name: str = "base"

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        return current_equity


class FullCompounding(SizingPolicy):
    """Baseline: size from current equity (standard compounding)."""

    name = "full_compounding"

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        return current_equity


class FixedInitial(SizingPolicy):
    """Always size from initial capital — zero compounding."""

    name = "fixed_initial"

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        return initial_equity


class CappedCompounding(SizingPolicy):
    """Compound up to a cap, then freeze.

    reference = min(current_equity, initial_equity * cap_multiple)
    """

    name = "capped_compounding"

    def __init__(self, cap_multiple: float = 3.0) -> None:
        self.cap_multiple = cap_multiple

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        cap = initial_equity * self.cap_multiple
        return min(current_equity, cap)


class SteppedCompounding(SizingPolicy):
    """Size increases only at discrete equity thresholds.

    reference = initial_equity * floor(current_equity / initial_equity)
    So the reference only increases in whole-multiple steps.
    """

    name = "stepped_compounding"

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        if initial_equity <= 0:
            return current_equity
        multiple = max(1, int(math.floor(current_equity / initial_equity)))
        return initial_equity * multiple


class DrawdownAwareSizing(SizingPolicy):
    """Reduce sizing linearly with drawdown from HWM.

    At 0% DD → full current equity.
    At max_dd_for_full_reduction → current_equity * min_scale.
    """

    name = "drawdown_aware"

    def __init__(
        self,
        max_dd_for_full_reduction: float = 0.10,
        min_scale: float = 0.25,
    ) -> None:
        self.max_dd = max_dd_for_full_reduction
        self.min_scale = min_scale

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        if peak_equity <= 0:
            return current_equity
        dd = max(0.0, (peak_equity - current_equity) / peak_equity)
        if dd <= 0:
            return current_equity
        dd_ratio = min(1.0, dd / self.max_dd) if self.max_dd > 0 else 1.0
        scale = 1.0 - dd_ratio * (1.0 - self.min_scale)
        return current_equity * scale


class VolatilityScaledSizing(SizingPolicy):
    """Scale reference equity inversely with volatility.

    When ATR > median: reduce reference equity proportionally.
    When ATR <= median: use current equity unchanged.
    """

    name = "volatility_scaled"

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        if current_atr is None or median_atr is None or median_atr <= 0:
            return current_equity
        if current_atr <= median_atr:
            return current_equity
        scale = median_atr / current_atr
        return current_equity * scale


class HybridPropSizing(SizingPolicy):
    """Conservative prop-style policy: capped growth + DD dampening.

    1. Cap reference at initial_equity * cap_multiple (default 2x)
    2. Then reduce proportionally if in drawdown from HWM
    """

    name = "hybrid_prop"

    def __init__(
        self,
        cap_multiple: float = 2.0,
        dd_reduction_rate: float = 0.5,
    ) -> None:
        self.cap_multiple = cap_multiple
        self.dd_reduction_rate = dd_reduction_rate

    def reference_equity(
        self,
        current_equity: float,
        initial_equity: float,
        peak_equity: float,
        current_atr: float | None = None,
        median_atr: float | None = None,
    ) -> float:
        cap = initial_equity * self.cap_multiple
        ref = min(current_equity, cap)
        if peak_equity > 0:
            dd = max(0.0, (peak_equity - current_equity) / peak_equity)
            if dd > 0:
                ref *= max(0.2, 1.0 - dd * self.dd_reduction_rate)
        return ref


ALL_SIZING_POLICIES: dict[str, SizingPolicy] = {
    "full_compounding": FullCompounding(),
    "fixed_initial": FixedInitial(),
    "capped_compounding": CappedCompounding(cap_multiple=3.0),
    "stepped_compounding": SteppedCompounding(),
    "drawdown_aware": DrawdownAwareSizing(),
    "volatility_scaled": VolatilityScaledSizing(),
    "hybrid_prop": HybridPropSizing(),
}


# ---------------------------------------------------------------------------
# Sizing strategy protocol + implementations
# ---------------------------------------------------------------------------

@runtime_checkable
class SizingStrategy(Protocol):
    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
        initial_equity: float | None = None,
        peak_equity: float | None = None,
    ) -> tuple[float, float]:
        """Return (units, risk_fraction)."""
        ...


class StopBasedSizer:
    """Fixed-fractional risk: risk = equity * base_risk_per_trade.

    Units = risk_amount / risk_distance_per_unit.
    For USD-quoted pairs, 1 pip per unit = pip_size * 1 unit.

    If a SizingPolicy is attached, the raw equity is transformed into a
    reference equity before computing risk_amount.
    """

    def __init__(
        self,
        lot_size: float = 100_000.0,
        policy: SizingPolicy | None = None,
    ) -> None:
        self._lot_size = lot_size
        self._policy = policy

    @property
    def policy(self) -> SizingPolicy | None:
        return self._policy

    @policy.setter
    def policy(self, p: SizingPolicy | None) -> None:
        self._policy = p

    def compute(
        self,
        candidate: TradeCandidate,
        equity: float,
        risk_cfg: RiskConfig,
        current_atr: float | None = None,
        median_atr: float | None = None,
        initial_equity: float | None = None,
        peak_equity: float | None = None,
    ) -> tuple[float, float]:
        sizing_equity = equity
        if self._policy is not None:
            sizing_equity = self._policy.reference_equity(
                current_equity=equity,
                initial_equity=initial_equity or equity,
                peak_equity=peak_equity or equity,
                current_atr=current_atr,
                median_atr=median_atr,
            )

        risk_fraction = risk_cfg.base_risk_per_trade
        risk_amount = sizing_equity * risk_fraction
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
        initial_equity: float | None = None,
        peak_equity: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._base.compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
            initial_equity=initial_equity, peak_equity=peak_equity,
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
        initial_equity: float | None = None,
        peak_equity: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._base.compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
            initial_equity=initial_equity, peak_equity=peak_equity,
        )
        mod = risk_cfg.score_risk_modulation
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
        initial_equity: float | None = None,
        peak_equity: float | None = None,
    ) -> tuple[float, float]:
        units, risk_frac = self._sizers[0].compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
            initial_equity=initial_equity, peak_equity=peak_equity,
        )
        for sizer in self._sizers[1:]:
            u2, rf2 = sizer.compute(
                candidate, equity, risk_cfg, current_atr, median_atr,
                initial_equity=initial_equity, peak_equity=peak_equity,
            )
            if u2 > 0 and units > 0:
                base_u, _ = self._sizers[0].compute(
                    candidate, equity, risk_cfg, current_atr, median_atr,
                    initial_equity=initial_equity, peak_equity=peak_equity,
                )
                if base_u > 0:
                    scale = u2 / base_u
                    units *= scale
                    risk_frac *= scale
        return round(units, 2), risk_frac
