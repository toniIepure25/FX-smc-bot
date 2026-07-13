"""Strategy A: Liquidity Sweep -> Reclaim -> MSS -> Displacement -> FVG Reversal.

Canonical name: liquidity_sweep_mss_fvg_reversal

This detector uses an explicit causal state machine. Each liquidity level
that gets swept spawns a StrategyInstance that progresses through:

  IDLE -> LEVEL_AVAILABLE -> LEVEL_BREACHED -> RECLAIM_CONFIRMED
       -> MSS_CONFIRMED -> FVG_CREATED -> ORDER_PENDING -> FILLED -> CLOSED

Any step can transition to INVALIDATED or EXPIRED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import StructureConfig, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    StructureSnapshot,
    SwingPoint,
)
from fx_smc_bot.alpha.intraday.common import (
    HIGH_SIDE_TYPES,
    LOW_SIDE_TYPES,
    check_displacement,
    check_mss,
    check_reclaim,
    check_sweep,
    compute_entry_sl_tp,
    compute_min_excursion,
    find_causal_swing,
    find_qualifying_fvg,
    sweep_direction,
)
from fx_smc_bot.alpha.intraday.state_machine import (
    StrategyInstance,
    StrategyState,
    StrategyTracker,
)

from pydantic import BaseModel, Field


class SweepReversalConfig(BaseModel):
    """Configuration for the sweep reversal strategy."""

    k_atr_excursion: float = Field(default=0.5, ge=0.0)
    k_spread_excursion: float = Field(default=2.0, ge=0.0)
    min_pips_excursion: float = Field(default=3.0, ge=0.0)
    max_reclaim_bars: int = Field(default=6, ge=1)
    max_mss_bars: int = Field(default=10, ge=1)
    max_displacement_bars: int = Field(default=5, ge=1)
    max_fvg_bars: int = Field(default=5, ge=1)
    max_order_bars: int = Field(default=20, ge=1)
    entry_fvg_pct: float = Field(default=0.5, ge=0.0, le=1.0)
    target_r: float = Field(default=2.0, ge=0.5)
    k_atr_sl_buffer: float = Field(default=0.3, ge=0.0)
    k_spread_sl_buffer: float = Field(default=1.5, ge=0.0)
    min_sl_buffer_pips: float = Field(default=2.0, ge=0.0)
    displacement_body_ratio: float = Field(default=2.0, ge=1.0)
    displacement_tr_ratio: float = Field(default=1.5, ge=0.5)
    displacement_clv: float = Field(default=0.6, ge=0.0, le=1.0)
    fvg_min_atr: float = Field(default=0.3, ge=0.0)
    eligible_level_types: list[str] = Field(default_factory=lambda: [
        "equal_highs", "equal_lows",
        "session_high", "session_low",
        "prior_day_high", "prior_day_low",
    ])
    swing_lookback: int = Field(default=5, ge=2)
    median_body_lookback: int = Field(default=20, ge=5)


@dataclass
class SweepReversalSignal:
    """Output of the sweep reversal detector when ORDER_PENDING is reached."""

    instance: StrategyInstance
    pair: TradingPair
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    fvg: FVGZone
    sweep_extreme: float
    bar_index: int
    timestamp: datetime


class SweepReversalDetectorV2:
    """Causal sweep reversal detector with explicit state machine."""

    def __init__(
        self,
        config: SweepReversalConfig | None = None,
    ) -> None:
        self.cfg = config or SweepReversalConfig()
        self.tracker = StrategyTracker()
        self._eligible_types = frozenset(
            LiquidityLevelType(t) for t in self.cfg.eligible_level_types
        )

    def process_bar(
        self,
        snapshot: StructureSnapshot,
        open_: NDArray[np.float64],
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_idx: int,
        bar_time: datetime,
        atr: float,
        spread: float,
        htf_bias: Direction | None = None,
    ) -> list[SweepReversalSignal]:
        """Process a single bar and return any new signals."""
        signals: list[SweepReversalSignal] = []

        self._check_new_levels(snapshot, bar_idx, bar_time)

        self._advance_active(
            snapshot, open_, high, low, close,
            bar_idx, bar_time, atr, spread, htf_bias, signals,
        )

        self.tracker.cleanup_terminal()
        return signals

    def _check_new_levels(
        self,
        snapshot: StructureSnapshot,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        """Register new strategy instances for eligible liquidity levels."""
        for level in snapshot.liquidity_levels:
            if level.level_type not in self._eligible_types:
                continue
            if level.swept:
                continue

            level_id = f"{level.level_type.value}_{level.price:.5f}_{level.formation_index}"
            if self.tracker.has_active_for_level(level_id):
                continue

            direction = sweep_direction(level)
            if direction is None:
                continue

            inst = StrategyInstance(
                family="liquidity_sweep_mss_fvg_reversal",
                pair=snapshot.pair,
                direction=direction,
                created_at=bar_time,
                liquidity_level=level,
                liquidity_level_id=level_id,
            )
            inst.transition(
                StrategyState.LEVEL_AVAILABLE,
                bar_idx, bar_time, reason="level eligible",
            )
            self.tracker.register(inst)

    def _advance_active(
        self,
        snapshot: StructureSnapshot,
        open_: NDArray[np.float64],
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_idx: int,
        bar_time: datetime,
        atr: float,
        spread: float,
        htf_bias: Direction | None,
        signals: list[SweepReversalSignal],
    ) -> None:
        """Advance each active instance through its state machine."""
        min_excursion = compute_min_excursion(
            atr, spread,
            self.cfg.k_atr_excursion,
            self.cfg.k_spread_excursion,
            self.cfg.min_pips_excursion * 0.0001,
        )
        sl_buffer = compute_min_excursion(
            atr, spread,
            self.cfg.k_atr_sl_buffer,
            self.cfg.k_spread_sl_buffer,
            self.cfg.min_sl_buffer_pips * 0.0001,
        )

        median_body = self._compute_median_body(
            open_, close, bar_idx, self.cfg.median_body_lookback,
        )

        for inst in list(self.tracker.active_instances):
            if inst.is_terminal:
                continue

            level = inst.liquidity_level
            if level is None:
                continue

            if inst.state == StrategyState.LEVEL_AVAILABLE:
                breached, extreme = check_sweep(
                    level, high, low, bar_idx, min_excursion,
                )
                if breached:
                    inst.sweep_extreme = extreme
                    inst.sweep_bar = bar_idx
                    inst.transition(
                        StrategyState.LEVEL_BREACHED,
                        bar_idx, bar_time, reason="sweep detected",
                        metadata={"extreme": extreme, "excursion": abs(extreme - level.price)},
                    )

            elif inst.state == StrategyState.LEVEL_BREACHED:
                if inst.sweep_bar is not None and bar_idx - inst.sweep_bar > self.cfg.max_reclaim_bars:
                    inst.invalidation_reason = "no reclaim within max bars"
                    inst.transition(
                        StrategyState.INVALIDATED,
                        bar_idx, bar_time, reason=inst.invalidation_reason,
                    )
                    continue

                reclaimed = check_reclaim(
                    level, close, inst.sweep_bar or 0, bar_idx, self.cfg.max_reclaim_bars,
                )
                if reclaimed:
                    inst.reclaim_bar = bar_idx
                    inst.transition(
                        StrategyState.RECLAIM_CONFIRMED,
                        bar_idx, bar_time, reason="price reclaimed level",
                    )

            elif inst.state == StrategyState.RECLAIM_CONFIRMED:
                if inst.reclaim_bar is not None and bar_idx - inst.reclaim_bar > self.cfg.max_mss_bars:
                    inst.invalidation_reason = "no MSS within max bars"
                    inst.transition(
                        StrategyState.INVALIDATED,
                        bar_idx, bar_time, reason=inst.invalidation_reason,
                    )
                    continue

                swing = find_causal_swing(
                    snapshot.swings, inst.direction, bar_idx,
                    self.cfg.swing_lookback,
                )
                if swing is not None and check_mss(inst.direction, close, bar_idx, swing):
                    inst.mss_swing = swing
                    inst.mss_bar = bar_idx
                    inst.transition(
                        StrategyState.MSS_CONFIRMED,
                        bar_idx, bar_time, reason="MSS confirmed",
                        metadata={"swing_price": swing.price, "swing_bar": swing.bar_index},
                    )

            elif inst.state == StrategyState.MSS_CONFIRMED:
                if inst.mss_bar is not None and bar_idx - inst.mss_bar > self.cfg.max_displacement_bars:
                    inst.invalidation_reason = "no displacement within max bars"
                    inst.transition(
                        StrategyState.INVALIDATED,
                        bar_idx, bar_time, reason=inst.invalidation_reason,
                    )
                    continue

                if htf_bias is not None and htf_bias != inst.direction:
                    inst.invalidation_reason = "HTF bias against direction"
                    inst.transition(
                        StrategyState.INVALIDATED,
                        bar_idx, bar_time, reason=inst.invalidation_reason,
                    )
                    continue

                is_disp = check_displacement(
                    open_, high, low, close, bar_idx, inst.direction,
                    atr, median_body,
                    self.cfg.displacement_body_ratio,
                    self.cfg.displacement_tr_ratio,
                    self.cfg.displacement_clv,
                )
                if is_disp:
                    inst.displacement_bar = bar_idx

                    fvg = find_qualifying_fvg(
                        snapshot.active_fvgs, inst.direction,
                        after_bar=inst.mss_bar or 0,
                        min_atr_size=self.cfg.fvg_min_atr,
                    )
                    if fvg is not None:
                        inst.fvg = fvg
                        inst.fvg_bar = fvg.bar_index
                        entry, sl, tp = compute_entry_sl_tp(
                            fvg, inst.direction,
                            inst.sweep_extreme or level.price,
                            self.cfg.entry_fvg_pct,
                            self.cfg.target_r,
                            sl_buffer,
                        )
                        inst.entry_price = entry
                        inst.stop_loss = sl
                        inst.take_profit = tp

                        inst.transition(
                            StrategyState.FVG_CREATED,
                            bar_idx, bar_time, reason="FVG + displacement confirmed",
                        )
                        inst.transition(
                            StrategyState.ORDER_PENDING,
                            bar_idx, bar_time,
                            info_available_at=bar_time,
                            reason="limit order placed",
                            metadata={"entry": entry, "sl": sl, "tp": tp},
                        )

                        signals.append(SweepReversalSignal(
                            instance=inst,
                            pair=snapshot.pair,
                            direction=inst.direction,
                            entry=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            fvg=fvg,
                            sweep_extreme=inst.sweep_extreme or level.price,
                            bar_index=bar_idx,
                            timestamp=bar_time,
                        ))

            elif inst.state == StrategyState.ORDER_PENDING:
                if inst.fvg_bar is not None and bar_idx - inst.fvg_bar > self.cfg.max_order_bars:
                    inst.invalidation_reason = "order expired"
                    inst.transition(
                        StrategyState.EXPIRED,
                        bar_idx, bar_time, reason="order lifetime exceeded",
                    )

    @staticmethod
    def _compute_median_body(
        open_: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_idx: int,
        lookback: int,
    ) -> float:
        start = max(0, bar_idx - lookback)
        if start >= bar_idx:
            return 0.0
        bodies = np.abs(close[start:bar_idx] - open_[start:bar_idx])
        return float(np.median(bodies)) if len(bodies) > 0 else 0.0
