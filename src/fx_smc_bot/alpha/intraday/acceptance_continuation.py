"""Strategy B: Liquidity Break -> Acceptance -> FVG Continuation.

Canonical name: liquidity_acceptance_fvg_continuation

State machine:
  IDLE -> LEVEL_AVAILABLE -> LEVEL_BREACHED -> ACCEPTANCE_CONFIRMED
       -> FVG_CREATED -> ORDER_PENDING -> FILLED -> CLOSED

This strategy explicitly distinguishes acceptance (close beyond level)
from rejection (wick beyond but close back inside).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from fx_smc_bot.alpha.intraday.common import (
    HIGH_SIDE_TYPES,
    LOW_SIDE_TYPES,
    check_displacement,
    compute_min_excursion,
    find_qualifying_fvg,
)
from fx_smc_bot.alpha.intraday.state_machine import (
    StrategyInstance,
    StrategyState,
    StrategyTracker,
)
from fx_smc_bot.config import PAIR_PIP_INFO, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    StructureSnapshot,
)


class AcceptanceContinuationConfig(BaseModel):
    """Configuration for the acceptance continuation strategy."""

    k_atr_break: float = Field(default=0.3, ge=0.0)
    k_spread_break: float = Field(default=1.5, ge=0.0)
    min_pips_break: float = Field(default=2.0, ge=0.0)
    acceptance_consecutive_closes: int = Field(default=2, ge=1)
    max_acceptance_bars: int = Field(default=6, ge=1)
    max_retest_bars: int = Field(default=15, ge=1)
    max_order_bars: int = Field(default=20, ge=1)
    entry_fvg_pct: float = Field(default=0.5, ge=0.0, le=1.0)
    target_r: float = Field(default=2.0, ge=0.5)
    k_atr_sl_buffer: float = Field(default=0.3, ge=0.0)
    k_spread_sl_buffer: float = Field(default=1.5, ge=0.0)
    min_sl_buffer_pips: float = Field(default=2.0, ge=0.0)
    displacement_body_ratio: float = Field(default=1.5, ge=1.0)
    displacement_tr_ratio: float = Field(default=1.2, ge=0.5)
    displacement_clv: float = Field(default=0.5, ge=0.0, le=1.0)
    fvg_min_atr: float = Field(default=0.3, ge=0.0)
    eligible_level_types: list[str] = Field(default_factory=lambda: [
        "equal_highs", "equal_lows",
        "session_high", "session_low",
        "prior_day_high", "prior_day_low",
    ])
    median_body_lookback: int = Field(default=20, ge=5)


def _break_direction(level: LiquidityLevel) -> Direction | None:
    """The continuation direction when a level is broken (not swept).

    High-side break -> LONG continuation (breakout above).
    Low-side break -> SHORT continuation (breakdown below).
    """
    if level.level_type in HIGH_SIDE_TYPES:
        return Direction.LONG
    if level.level_type in LOW_SIDE_TYPES:
        return Direction.SHORT
    return None


@dataclass
class AcceptanceContinuationSignal:
    instance: StrategyInstance
    pair: TradingPair
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    fvg: FVGZone
    bar_index: int
    timestamp: datetime


class AcceptanceContinuationDetector:
    """Causal acceptance continuation detector."""

    def __init__(
        self,
        config: AcceptanceContinuationConfig | None = None,
        pair: TradingPair = TradingPair.EURUSD,
    ) -> None:
        self.cfg = config or AcceptanceContinuationConfig()
        self.pair = pair
        self._pip_size = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
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
    ) -> list[AcceptanceContinuationSignal]:
        signals: list[AcceptanceContinuationSignal] = []
        self._check_new_levels(snapshot, bar_idx, bar_time)
        self._advance_active(
            snapshot, open_, high, low, close,
            bar_idx, bar_time, atr, spread, htf_bias, signals,
        )
        self.tracker.cleanup_terminal()
        return signals

    def _check_new_levels(
        self, snapshot: StructureSnapshot, bar_idx: int, bar_time: datetime,
    ) -> None:
        for level in snapshot.liquidity_levels:
            if level.level_type not in self._eligible_types:
                continue
            if level.swept:
                continue
            level_id = f"acc_{level.level_type.value}_{level.price:.5f}_{level.formation_index}"
            if self.tracker.has_active_for_level(level_id):
                continue
            direction = _break_direction(level)
            if direction is None:
                continue
            inst = StrategyInstance(
                family="liquidity_acceptance_fvg_continuation",
                pair=snapshot.pair,
                direction=direction,
                created_at=bar_time,
                liquidity_level=level,
                liquidity_level_id=level_id,
            )
            inst.transition(
                StrategyState.LEVEL_AVAILABLE, bar_idx, bar_time,
                reason="level eligible for acceptance",
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
        signals: list[AcceptanceContinuationSignal],
    ) -> None:
        min_break = compute_min_excursion(
            atr, spread, self.cfg.k_atr_break,
            self.cfg.k_spread_break, self.cfg.min_pips_break * self._pip_size,
        )
        sl_buffer = compute_min_excursion(
            atr, spread, self.cfg.k_atr_sl_buffer,
            self.cfg.k_spread_sl_buffer, self.cfg.min_sl_buffer_pips * self._pip_size,
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
                broken = self._check_break(
                    level, inst.direction, close, bar_idx, min_break,
                )
                if broken:
                    is_disp = check_displacement(
                        open_, high, low, close, bar_idx, inst.direction,
                        atr, median_body,
                        self.cfg.displacement_body_ratio,
                        self.cfg.displacement_tr_ratio,
                        self.cfg.displacement_clv,
                    )
                    if is_disp:
                        inst.sweep_bar = bar_idx
                        inst.transition(
                            StrategyState.LEVEL_BREACHED, bar_idx, bar_time,
                            reason="break with displacement",
                        )

            elif inst.state == StrategyState.LEVEL_BREACHED:
                max_bars = self.cfg.max_acceptance_bars
                if inst.sweep_bar is not None and bar_idx - inst.sweep_bar > max_bars:
                    inst.invalidation_reason = "no acceptance within max bars"
                    inst.transition(
                        StrategyState.INVALIDATED, bar_idx, bar_time,
                        reason=inst.invalidation_reason,
                    )
                    continue

                n_closes = self._count_consecutive_closes_beyond(
                    level, inst.direction, close,
                    inst.sweep_bar or 0, bar_idx,
                )
                if n_closes >= self.cfg.acceptance_consecutive_closes:
                    inst.reclaim_bar = bar_idx
                    inst.transition(
                        StrategyState.ACCEPTANCE_CONFIRMED, bar_idx, bar_time,
                        reason=f"{n_closes} consecutive closes beyond level",
                    )

            elif inst.state == StrategyState.ACCEPTANCE_CONFIRMED:
                max_rt = self.cfg.max_retest_bars
                if inst.reclaim_bar is not None and bar_idx - inst.reclaim_bar > max_rt:
                    inst.invalidation_reason = "no retest within max bars"
                    inst.transition(
                        StrategyState.INVALIDATED, bar_idx, bar_time,
                        reason=inst.invalidation_reason,
                    )
                    continue

                reclaimed_back = self._check_reclaim_back(
                    level, inst.direction, close, bar_idx,
                )
                if reclaimed_back:
                    inst.invalidation_reason = "price reclaimed back through level"
                    inst.transition(
                        StrategyState.INVALIDATED, bar_idx, bar_time,
                        reason=inst.invalidation_reason,
                    )
                    continue

                fvg = find_qualifying_fvg(
                    snapshot.active_fvgs, inst.direction,
                    after_bar=inst.sweep_bar or 0,
                    min_atr_size=self.cfg.fvg_min_atr,
                )
                if fvg is not None:
                    retest_swing_low = self._find_retest_swing(
                        low if inst.direction == Direction.LONG else high,
                        inst.reclaim_bar or bar_idx, bar_idx, inst.direction,
                    )
                    entry, sl, tp = self._compute_entry_sl_tp(
                        fvg, inst.direction, level.price,
                        retest_swing_low, sl_buffer,
                    )
                    inst.fvg = fvg
                    inst.fvg_bar = fvg.bar_index
                    inst.entry_price = entry
                    inst.stop_loss = sl
                    inst.take_profit = tp
                    inst.transition(
                        StrategyState.FVG_CREATED, bar_idx, bar_time,
                        reason="retest FVG found",
                    )
                    inst.transition(
                        StrategyState.ORDER_PENDING, bar_idx, bar_time,
                        reason="limit order placed",
                    )
                    signals.append(AcceptanceContinuationSignal(
                        instance=inst, pair=snapshot.pair,
                        direction=inst.direction,
                        entry=entry, stop_loss=sl, take_profit=tp,
                        fvg=fvg, bar_index=bar_idx, timestamp=bar_time,
                    ))

            elif inst.state == StrategyState.ORDER_PENDING:
                if inst.fvg_bar is not None and bar_idx - inst.fvg_bar > self.cfg.max_order_bars:
                    inst.invalidation_reason = "order expired"
                    inst.transition(
                        StrategyState.EXPIRED, bar_idx, bar_time,
                        reason="order lifetime exceeded",
                    )

    @staticmethod
    def _check_break(
        level: LiquidityLevel,
        direction: Direction,
        close: NDArray[np.float64],
        bar_idx: int,
        min_distance: float,
    ) -> bool:
        c = float(close[bar_idx])
        if direction == Direction.LONG:
            return c > level.price + min_distance
        else:
            return c < level.price - min_distance

    @staticmethod
    def _count_consecutive_closes_beyond(
        level: LiquidityLevel,
        direction: Direction,
        close: NDArray[np.float64],
        from_bar: int,
        to_bar: int,
    ) -> int:
        count = 0
        for i in range(from_bar, to_bar + 1):
            c = float(close[i])
            if direction == Direction.LONG:
                beyond = c > level.price
            else:
                beyond = c < level.price
            if beyond:
                count += 1
            else:
                count = 0
        return count

    @staticmethod
    def _check_reclaim_back(
        level: LiquidityLevel,
        direction: Direction,
        close: NDArray[np.float64],
        bar_idx: int,
    ) -> bool:
        c = float(close[bar_idx])
        if direction == Direction.LONG:
            return c < level.price
        else:
            return c > level.price

    @staticmethod
    def _find_retest_swing(
        price_arr: NDArray[np.float64],
        from_bar: int,
        to_bar: int,
        direction: Direction,
    ) -> float:
        segment = price_arr[from_bar:to_bar + 1]
        if len(segment) == 0:
            return float(price_arr[from_bar])
        if direction == Direction.LONG:
            return float(np.min(segment))
        else:
            return float(np.max(segment))

    def _compute_entry_sl_tp(
        self,
        fvg: FVGZone,
        direction: Direction,
        level_price: float,
        retest_extreme: float,
        sl_buffer: float,
    ) -> tuple[float, float, float]:
        if direction == Direction.LONG:
            entry = fvg.low + self.cfg.entry_fvg_pct * (fvg.high - fvg.low)
            stop = retest_extreme - sl_buffer
            risk = entry - stop
            tp = entry + self.cfg.target_r * risk
        else:
            entry = fvg.high - self.cfg.entry_fvg_pct * (fvg.high - fvg.low)
            stop = retest_extreme + sl_buffer
            risk = stop - entry
            tp = entry - self.cfg.target_r * risk
        return entry, stop, tp

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
