"""Strategy C: Opening Range Displacement -> FVG Retest.

Canonical name: opening_range_displacement_fvg_retest

State machine:
  IDLE -> RANGE_COMPLETE -> BREAKOUT_CONFIRMED -> FVG_CREATED
       -> ORDER_PENDING -> FILLED -> CLOSED

London and New York sessions are tested separately.
All windows use IANA time zones and remain correct through DST changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import TradingPair
from fx_smc_bot.data.timezone import opening_range_utc
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    StructureSnapshot,
)
from fx_smc_bot.alpha.intraday.common import (
    check_displacement,
    compute_min_excursion,
    find_qualifying_fvg,
)
from fx_smc_bot.alpha.intraday.state_machine import (
    StrategyInstance,
    StrategyState,
    StrategyTracker,
)

from pydantic import BaseModel, Field


class OpeningRangeConfig(BaseModel):
    """Configuration for the opening range strategy."""

    session_name: str = Field(default="london")
    tz_name: str = Field(default="Europe/London")
    range_start_local: str = Field(default="08:00")
    range_end_local: str = Field(default="08:30")
    session_cutoff_local: str = Field(default="11:00")

    min_range_atr: float = Field(default=0.3, ge=0.0)
    max_range_atr: float = Field(default=3.0, ge=0.0)
    breakout_min_close_distance_atr: float = Field(default=0.2, ge=0.0)
    max_retest_bars: int = Field(default=20, ge=1)
    max_order_bars: int = Field(default=20, ge=1)
    entry_fvg_pct: float = Field(default=0.5, ge=0.0, le=1.0)
    target_r: float = Field(default=2.0, ge=0.5)
    k_atr_sl_buffer: float = Field(default=0.3, ge=0.0)
    displacement_body_ratio: float = Field(default=1.5, ge=1.0)
    displacement_tr_ratio: float = Field(default=1.2, ge=0.5)
    displacement_clv: float = Field(default=0.5, ge=0.0, le=1.0)
    fvg_min_atr: float = Field(default=0.3, ge=0.0)
    median_body_lookback: int = Field(default=20, ge=5)


@dataclass
class OpeningRangeSignal:
    instance: StrategyInstance
    pair: TradingPair
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    fvg: FVGZone
    range_high: float
    range_low: float
    bar_index: int
    timestamp: datetime


@dataclass
class _OpeningRange:
    """Tracked opening range for a single day."""
    date: datetime
    utc_start: datetime
    utc_end: datetime
    high: float = 0.0
    low: float = float("inf")
    complete: bool = False
    processed: bool = False


class OpeningRangeDetector:
    """Causal opening range displacement + FVG retest detector."""

    def __init__(self, config: OpeningRangeConfig | None = None) -> None:
        self.cfg = config or OpeningRangeConfig()
        self.tracker = StrategyTracker()
        self._ranges: dict[str, _OpeningRange] = {}

        parts_start = self.cfg.range_start_local.split(":")
        parts_end = self.cfg.range_end_local.split(":")
        self._start_local = time(int(parts_start[0]), int(parts_start[1]))
        self._end_local = time(int(parts_end[0]), int(parts_end[1]))

        parts_cutoff = self.cfg.session_cutoff_local.split(":")
        self._cutoff_local = time(int(parts_cutoff[0]), int(parts_cutoff[1]))

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
    ) -> list[OpeningRangeSignal]:
        signals: list[OpeningRangeSignal] = []

        self._update_ranges(high, low, bar_idx, bar_time)
        self._check_new_ranges(bar_idx, bar_time, atr)
        self._advance_active(
            snapshot, open_, high, low, close,
            bar_idx, bar_time, atr, spread, signals,
        )
        self.tracker.cleanup_terminal()
        return signals

    def _update_ranges(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        """Track opening range bars and finalize when range window ends."""
        utc_start, utc_end = opening_range_utc(
            bar_time, self._start_local, self._end_local, self.cfg.tz_name,
        )
        date_key = utc_start.strftime("%Y-%m-%d_%H%M")

        if utc_start <= bar_time < utc_end:
            if date_key not in self._ranges:
                self._ranges[date_key] = _OpeningRange(
                    date=bar_time, utc_start=utc_start, utc_end=utc_end,
                )
            rng = self._ranges[date_key]
            h = float(high[bar_idx])
            l = float(low[bar_idx])
            if h > rng.high:
                rng.high = h
            if l < rng.low:
                rng.low = l
        elif bar_time >= utc_end:
            if date_key in self._ranges and not self._ranges[date_key].complete:
                self._ranges[date_key].complete = True

    def _check_new_ranges(
        self, bar_idx: int, bar_time: datetime, atr: float,
    ) -> None:
        for key, rng in self._ranges.items():
            if not rng.complete or rng.processed:
                continue
            rng.processed = True

            range_size = rng.high - rng.low
            if atr > 0:
                range_atr = range_size / atr
                if range_atr < self.cfg.min_range_atr or range_atr > self.cfg.max_range_atr:
                    continue

            level_id = f"or_{key}"

            inst_bull = StrategyInstance(
                family="opening_range_displacement_fvg_retest",
                pair=TradingPair.EURUSD,
                direction=Direction.LONG,
                created_at=bar_time,
                liquidity_level_id=f"{level_id}_long",
            )
            inst_bull.sweep_extreme = rng.low
            inst_bull.transition(
                StrategyState.RANGE_COMPLETE, bar_idx, bar_time,
                reason="opening range complete",
                metadata={"high": rng.high, "low": rng.low, "range_atr": range_size / atr if atr > 0 else 0},
            )
            self.tracker.register(inst_bull)

            inst_bear = StrategyInstance(
                family="opening_range_displacement_fvg_retest",
                pair=TradingPair.EURUSD,
                direction=Direction.SHORT,
                created_at=bar_time,
                liquidity_level_id=f"{level_id}_short",
            )
            inst_bear.sweep_extreme = rng.high
            inst_bear.transition(
                StrategyState.RANGE_COMPLETE, bar_idx, bar_time,
                reason="opening range complete",
                metadata={"high": rng.high, "low": rng.low},
            )
            self.tracker.register(inst_bear)

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
        signals: list[OpeningRangeSignal],
    ) -> None:
        median_body = self._compute_median_body(
            open_, close, bar_idx, self.cfg.median_body_lookback,
        )
        sl_buffer = compute_min_excursion(
            atr, spread, self.cfg.k_atr_sl_buffer, 1.0, 0.0002,
        )

        _, cutoff_utc = opening_range_utc(
            bar_time, self._start_local, self._cutoff_local, self.cfg.tz_name,
        )

        for inst in list(self.tracker.active_instances):
            if inst.is_terminal:
                continue

            if bar_time >= cutoff_utc and inst.state in (
                StrategyState.RANGE_COMPLETE,
                StrategyState.BREAKOUT_CONFIRMED,
                StrategyState.ORDER_PENDING,
            ):
                inst.invalidation_reason = "session cutoff"
                inst.transition(
                    StrategyState.EXPIRED, bar_idx, bar_time,
                    reason="session cutoff reached",
                )
                continue

            if inst.state == StrategyState.RANGE_COMPLETE:
                range_meta = inst.events[0].metadata if inst.events else {}
                range_high = range_meta.get("high", 0.0)
                range_low = range_meta.get("low", float("inf"))
                min_dist = self.cfg.breakout_min_close_distance_atr * atr

                c = float(close[bar_idx])
                broken_high = c > range_high + min_dist
                broken_low = c < range_low - min_dist

                if inst.direction == Direction.LONG and broken_high:
                    is_disp = check_displacement(
                        open_, high, low, close, bar_idx, Direction.LONG,
                        atr, median_body,
                        self.cfg.displacement_body_ratio,
                        self.cfg.displacement_tr_ratio,
                        self.cfg.displacement_clv,
                    )
                    if is_disp:
                        inst.sweep_bar = bar_idx
                        inst.transition(
                            StrategyState.BREAKOUT_CONFIRMED, bar_idx, bar_time,
                            reason="bullish breakout with displacement",
                        )
                elif inst.direction == Direction.SHORT and broken_low:
                    is_disp = check_displacement(
                        open_, high, low, close, bar_idx, Direction.SHORT,
                        atr, median_body,
                        self.cfg.displacement_body_ratio,
                        self.cfg.displacement_tr_ratio,
                        self.cfg.displacement_clv,
                    )
                    if is_disp:
                        inst.sweep_bar = bar_idx
                        inst.transition(
                            StrategyState.BREAKOUT_CONFIRMED, bar_idx, bar_time,
                            reason="bearish breakout with displacement",
                        )
                elif (inst.direction == Direction.LONG and broken_low) or \
                     (inst.direction == Direction.SHORT and broken_high):
                    inst.invalidation_reason = "opposite side breakout"
                    inst.transition(
                        StrategyState.INVALIDATED, bar_idx, bar_time,
                        reason="opposite side breakout",
                    )

            elif inst.state == StrategyState.BREAKOUT_CONFIRMED:
                if inst.sweep_bar is not None and bar_idx - inst.sweep_bar > self.cfg.max_retest_bars:
                    inst.invalidation_reason = "no retest FVG within max bars"
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
                    range_meta = inst.events[0].metadata if inst.events else {}
                    range_high = range_meta.get("high", 0.0)
                    range_low = range_meta.get("low", float("inf"))

                    entry, sl, tp = self._compute_entry_sl_tp(
                        fvg, inst.direction, range_high, range_low, sl_buffer,
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
                    signals.append(OpeningRangeSignal(
                        instance=inst, pair=snapshot.pair,
                        direction=inst.direction,
                        entry=entry, stop_loss=sl, take_profit=tp,
                        fvg=fvg, range_high=range_high, range_low=range_low,
                        bar_index=bar_idx, timestamp=bar_time,
                    ))

            elif inst.state == StrategyState.ORDER_PENDING:
                if inst.fvg_bar is not None and bar_idx - inst.fvg_bar > self.cfg.max_order_bars:
                    inst.invalidation_reason = "order expired"
                    inst.transition(
                        StrategyState.EXPIRED, bar_idx, bar_time,
                        reason="order lifetime exceeded",
                    )

    def _compute_entry_sl_tp(
        self,
        fvg: FVGZone,
        direction: Direction,
        range_high: float,
        range_low: float,
        sl_buffer: float,
    ) -> tuple[float, float, float]:
        if direction == Direction.LONG:
            entry = fvg.low + self.cfg.entry_fvg_pct * (fvg.high - fvg.low)
            stop = range_low - sl_buffer
            risk = entry - stop
            tp = entry + self.cfg.target_r * risk
        else:
            entry = fvg.high - self.cfg.entry_fvg_pct * (fvg.high - fvg.low)
            stop = range_high + sl_buffer
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
