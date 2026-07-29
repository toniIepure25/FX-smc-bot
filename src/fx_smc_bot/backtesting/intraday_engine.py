"""Intraday backtest engine for V2 stateful strategy runtimes.

Unlike the legacy BacktestEngine that uses stateless detectors through
generate_candidates(), this engine maintains StatefulStrategyRuntime
instances across bars and feeds execution events back to them.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, cast

import numpy as np

from fx_smc_bot.alpha.intraday.runtime import (
    CausalBarContext,
    OrderAcceptedEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderIntent,
    PositionClosedEvent,
    StatefulStrategyRuntime,
)
from fx_smc_bot.backtesting.ledger import TradeLedger
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import (
    PAIR_PIP_INFO,
    TIMEFRAME_MINUTES,
    AppConfig,
    SessionConfig,
    StructureConfig,
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    BacktestResult,
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    StructureRegime,
    StructureSnapshot,
)
from fx_smc_bot.execution.fills import BidAskFillEngine, FillEngine
from fx_smc_bot.execution.slippage import (
    FixedSpreadSlippage,
    NativeBidAskSlippage,
)
from fx_smc_bot.execution.swap import SwapCalculator
from fx_smc_bot.portfolio.state import PortfolioState
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.utils.math import atr as compute_atr
from fx_smc_bot.utils.time import classify_session

logger = logging.getLogger(__name__)

_MIN_WARMUP_BARS = 30

EXECUTION_MODE_BID_ASK = "BID_ASK_NATIVE"
EXECUTION_MODE_MID = "MID_PRICE_EXPLORATORY_MODE"


@dataclass(frozen=True, slots=True)
class IntradayExecutionPolicy:
    """Optional stricter lifecycle rules for prospective research protocols."""

    warmup_bars: int = _MIN_WARMUP_BARS
    close_at_session_cutoff: bool = False
    close_at_fx_week_end: bool = False
    close_at_final_bar: bool = False
    single_position_per_pair: bool = False
    apply_swap: bool = True
    structure_lookback_bars: int = 201
    session_cutoff_resolver: Callable[[datetime, str], datetime] | None = None
    fx_week_close_resolver: Callable[[datetime], datetime] | None = None
    runtime_bar_filter: Callable[[datetime, str], bool] | None = None
    snapshot_builder: Callable[
        [BarSeries, StructureConfig, SessionConfig], StructureSnapshot
    ] | None = None


@dataclass(slots=True)
class TradeRecord:
    """Extended trade record with full cost decomposition."""
    position_id: str
    order_id: str
    intent_id: str
    family: str
    pair: str
    direction: str
    session: str
    entry_price: float
    exit_price: float
    units: float
    gross_pnl: float
    bid_ask_execution_effect: float
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    swap_cost: float
    net_pnl: float
    entry_bar: int
    exit_bar: int
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    price_mode: str = EXECUTION_MODE_MID
    exit_reason: str = ""


@dataclass(slots=True)
class RuntimeReconciliation:
    """Lifecycle reconciliation between strategy state and ledger."""
    filled_with_matching_trade: int = 0
    closed_with_matching_close: int = 0
    expired_without_fill: int = 0
    cancelled_without_fill: int = 0
    orphan_fills: int = 0
    orphan_trades: int = 0
    violations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EventFunnel:
    """Event-state funnel counters for a runtime."""
    family: str = ""
    pair: str = ""
    session: str = ""
    bars_processed: int = 0
    intents_generated: int = 0
    orders_accepted: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    orders_expired: int = 0
    positions_closed: int = 0
    sl_exits: int = 0
    tp_exits: int = 0
    session_exits: int = 0
    fx_week_exits: int = 0
    final_bar_exits: int = 0
    position_overlap_rejections: int = 0
    session_horizon_signal_rejections: int = 0


class IntradayBacktestEngine:
    """Event-driven engine for V2 stateful strategy runtimes.

    Feeds execution events back to the originating runtime and tracks
    full cost decomposition per trade.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        swap_rates: dict | None = None,
        execution_policy: IntradayExecutionPolicy | None = None,
    ) -> None:
        self._cfg = config or AppConfig()
        self._fill_engine = FillEngine(
            FixedSpreadSlippage(self._cfg.execution),
            fill_policy=self._cfg.execution.fill_policy,
        )
        self._bidask_slippage = NativeBidAskSlippage(self._cfg.execution)
        self._bidask_fill_engine = BidAskFillEngine(
            self._bidask_slippage,
            fill_policy=self._cfg.execution.fill_policy,
        )
        self._swap_calc = SwapCalculator(rates=swap_rates)
        self._ledger = TradeLedger(
            commission_per_lot=self._cfg.backtest.commission_per_lot,
            lot_size=self._cfg.backtest.lot_size,
        )
        self._portfolio = PortfolioState(self._cfg.backtest.initial_capital)
        self._policy = execution_policy or IntradayExecutionPolicy()
        if self._policy.warmup_bars < 0:
            raise ValueError("warmup_bars must be non-negative")

        self._runtimes: list[StatefulStrategyRuntime] = []
        self._intent_to_order: dict[str, str] = {}
        self._order_to_intent: dict[str, str] = {}
        self._order_to_runtime_idx: dict[str, int] = {}
        self._order_activation_bar: dict[str, int] = {}
        self._position_to_order: dict[str, str] = {}
        self._position_entry_bars: dict[str, int] = {}
        self._position_swap: dict[str, float] = {}
        self._position_exit_kind: dict[str, str] = {}
        self._prev_bar_times: dict[TradingPair, datetime] = {}
        self._funnels: dict[int, EventFunnel] = {}
        self._trade_records: list[TradeRecord] = []
        self._execution_mode: str = EXECUTION_MODE_MID
        self._execution_errors: list[str] = []

    def add_runtime(self, runtime: StatefulStrategyRuntime) -> int:
        """Register a strategy runtime. Returns its index."""
        idx = len(self._runtimes)
        self._runtimes.append(runtime)
        self._funnels[idx] = EventFunnel(
            family=runtime.family,
            pair=runtime.pair.value,
            session=runtime.session,
        )
        return idx

    def run(
        self,
        data: (
            dict[TradingPair, BarSeries]
            | dict[TradingPair, BidAskBarSeries]
        ),
        htf_data: dict[TradingPair, BarSeries] | None = None,
    ) -> BacktestResult:
        """Run the backtest using V2 stateful runtimes.

        Accepts either BarSeries (MID_PRICE_EXPLORATORY_MODE) or
        BidAskBarSeries (BID_ASK_NATIVE). Execution semantics differ:
        in bid/ask mode, fills use the correct price side without
        adding synthetic spread.
        """
        config_hash = hashlib.md5(
            str(self._cfg.model_dump()).encode()
        ).hexdigest()[:12]

        pairs = list(data.keys())
        if not pairs:
            raise ValueError("No data provided")

        first_val = next(iter(data.values()))
        use_bidask = isinstance(first_val, BidAskBarSeries)
        self._execution_mode = (
            EXECUTION_MODE_BID_ASK if use_bidask else EXECUTION_MODE_MID
        )

        mid_data: dict[TradingPair, BarSeries] = {}
        ba_data: dict[TradingPair, BidAskBarSeries] = {}
        if use_bidask:
            for pair, series in data.items():
                ba_series = cast(BidAskBarSeries, series)
                ba_data[pair] = ba_series
                mid_data[pair] = ba_series.to_mid_series()
        else:
            for pair, series in data.items():
                mid_data[pair] = series  # type: ignore[assignment]

        all_timestamps: set[Any] = set()
        for series in mid_data.values():
            for ts in series.timestamps:
                all_timestamps.add(ts)
        sorted_ts = sorted(all_timestamps)
        if not sorted_ts:
            raise ValueError("No bars in data")

        ts_to_idx: dict[TradingPair, dict] = {}
        for pair, series in mid_data.items():
            mapping = {}
            for i, ts in enumerate(series.timestamps):
                mapping[ts] = i
            ts_to_idx[pair] = mapping

        final_idx = {pair: len(series) - 1 for pair, series in mid_data.items()}

        atr_cache: dict[TradingPair, list[float]] = {}
        for pair, series in mid_data.items():
            atr_vals = compute_atr(
                series.high, series.low, series.close,
                self._cfg.structure.atr_period,
            )
            atr_cache[pair] = atr_vals.tolist()

        _htf_causal_idx: dict[TradingPair, dict] = {}
        _htf_snap_cache: dict[TradingPair, tuple] = {}
        _htf_last_idx: dict[TradingPair, int] = {}
        if htf_data:
            for pair, htf_series in htf_data.items():
                htf_tf_minutes = TIMEFRAME_MINUTES.get(htf_series.timeframe, 60)
                htf_close_times = (
                    htf_series.timestamps
                    + np.timedelta64(htf_tf_minutes, "m")
                )
                _htf_causal_idx[pair] = {
                    "close_times": htf_close_times,
                    "series": htf_series,
                }
                _htf_last_idx[pair] = -1

        start_dt = sorted_ts[0].astype("datetime64[us]").astype(datetime)
        end_dt = sorted_ts[-1].astype("datetime64[us]").astype(datetime)

        current_prices: dict[str, float] = {}
        for ts in sorted_ts:
            bar_time = ts.astype("datetime64[us]").astype(datetime)

            for pair in pairs:
                idx_map = ts_to_idx[pair]
                if ts not in idx_map:
                    continue
                bar_idx = idx_map[ts]
                mid_series = mid_data[pair]
                next_bar_time = (
                    mid_series.timestamps[bar_idx + 1]
                    .astype("datetime64[us]")
                    .astype(datetime)
                    if bar_idx < final_idx[pair]
                    else None
                )
                current_prices[pair.value] = float(
                    mid_series.close[bar_idx]
                )

                if use_bidask:
                    ba = ba_data[pair]
                    self._validate_bidask_bar(ba, bar_idx, bar_time)
                    self._process_exits_bidask(
                        pair, ba, mid_series, bar_idx, bar_time,
                    )
                    self._process_pending_fills_bidask(
                        pair, ba, mid_series, bar_idx, bar_time,
                    )
                    self._process_protocol_time_exits_bidask(
                        pair,
                        ba,
                        mid_series,
                        bar_idx,
                        bar_time,
                        next_bar_time=next_bar_time,
                        is_final_bar=bar_idx == final_idx[pair],
                    )
                else:
                    self._process_exits(
                        pair, mid_series, bar_idx, bar_time,
                    )
                    self._process_pending_fills(
                        pair, mid_series, bar_idx, bar_time,
                    )
                if self._policy.apply_swap:
                    self._process_swap(pair, bar_time)

                if bar_idx < self._policy.warmup_bars:
                    self._prev_bar_times[pair] = bar_time
                    continue

                eligible_runtime_indices = [
                    rt_idx
                    for rt_idx, runtime in enumerate(self._runtimes)
                    if runtime.pair == pair
                    and (
                        self._policy.runtime_bar_filter is None
                        or self._policy.runtime_bar_filter(bar_time, runtime.session)
                    )
                ]
                if not eligible_runtime_indices:
                    self._prev_bar_times[pair] = bar_time
                    continue

                slice_start = max(
                    0,
                    bar_idx - self._policy.structure_lookback_bars + 1,
                )
                ltf_slice = mid_series.slice(slice_start, bar_idx + 1)
                snapshot_builder = (
                    self._policy.snapshot_builder or build_structure_snapshot
                )
                snapshot = snapshot_builder(
                    ltf_slice, self._cfg.structure, self._cfg.sessions,
                )
                self._offset_snapshot_indices(snapshot, slice_start)

                htf_bias = None
                htf_snapshot = None
                if pair in _htf_causal_idx:
                    htf_info = _htf_causal_idx[pair]
                    htf_close_times = htf_info["close_times"]
                    htf_series = htf_info["series"]
                    valid = np.where(htf_close_times <= ts)[0]
                    if len(valid) > 0:
                        causal_idx = int(valid[-1])
                        if causal_idx != _htf_last_idx[pair]:
                            _htf_last_idx[pair] = causal_idx
                            htf_slice = htf_series.slice(0, causal_idx + 1)
                            snap = build_structure_snapshot(
                                htf_slice,
                                self._cfg.structure,
                                self._cfg.sessions,
                            )
                            bias = None
                            if snap.regime == StructureRegime.BULLISH:
                                bias = Direction.LONG
                            elif snap.regime == StructureRegime.BEARISH:
                                bias = Direction.SHORT
                            _htf_snap_cache[pair] = (snap, bias)
                        htf_snapshot, htf_bias = _htf_snap_cache[pair]

                current_atr = (
                    atr_cache[pair][bar_idx]
                    if bar_idx < len(atr_cache[pair])
                    else 0.001
                )
                if use_bidask:
                    ba_s = ba_data[pair]
                    spread = float(
                        ba_s.ask_close[bar_idx]
                        - ba_s.bid_close[bar_idx]
                    )
                elif (
                    mid_series.spread is not None
                    and bar_idx < len(mid_series.spread)
                ):
                    spread = float(mid_series.spread[bar_idx])
                else:
                    pip = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
                    spread = self._cfg.execution.default_spread_pips * pip

                ctx = CausalBarContext(
                    pair=pair,
                    timeframe=mid_series.timeframe,
                    bar_idx=bar_idx,
                    timestamp=bar_time,
                    open=mid_series.open,
                    high=mid_series.high,
                    low=mid_series.low,
                    close=mid_series.close,
                    atr=current_atr,
                    spread=spread,
                    snapshot=snapshot,
                    htf_bias=htf_bias,
                    htf_snapshot=htf_snapshot,
                )

                for rt_idx in eligible_runtime_indices:
                    runtime = self._runtimes[rt_idx]

                    funnel = self._funnels[rt_idx]
                    funnel.bars_processed += 1

                    intents = runtime.on_bar(ctx)

                    for intent in intents:
                        funnel.intents_generated += 1

                        if self._bar_reaches_session_cutoff(
                            bar_time,
                            next_bar_time,
                            runtime.session,
                            mid_series.timeframe,
                        ):
                            funnel.session_horizon_signal_rejections += 1
                            continue

                        if intent.activation_bar <= bar_idx:
                            intent.activation_bar = bar_idx + 1

                        order = self._intent_to_order_obj(intent, bar_time)
                        self._portfolio.add_order(order)
                        self._intent_to_order[intent.intent_id] = order.id
                        self._order_to_intent[order.id] = intent.intent_id
                        self._order_to_runtime_idx[order.id] = rt_idx
                        self._order_activation_bar[order.id] = intent.activation_bar

                        funnel.orders_accepted += 1
                        runtime.on_order_accepted(OrderAcceptedEvent(
                            order_id=order.id,
                            intent_id=intent.intent_id,
                            timestamp=bar_time,
                        ))

                self._prev_bar_times[pair] = bar_time

            if current_prices:
                eq_point = self._portfolio.equity_point(bar_time, current_prices)
                self._ledger.record_equity(eq_point)

        if self._policy.close_at_final_bar:
            self._cancel_all_pending("final_available_certified_bar", end_dt)

        metadata = {
            "pairs": [p.value for p in pairs],
            "runtimes": len(self._runtimes),
            "trade_records": len(self._trade_records),
            "execution_mode": self._execution_mode,
            "execution_errors": list(self._execution_errors),
            "open_positions_at_end": len(self._portfolio.open_positions),
            "pending_orders_at_end": len(self._portfolio.pending_orders),
            "warmup_bars": self._policy.warmup_bars,
        }

        return BacktestResult(
            config_hash=config_hash,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=self._cfg.backtest.initial_capital,
            final_equity=(
                self._portfolio.equity(current_prices)
                if current_prices
                else self._cfg.backtest.initial_capital
            ),
            trades=self._ledger.trades,
            equity_curve=self._ledger.equity_curve,
            metadata=metadata,
        )

    def _intent_to_order_obj(
        self, intent: OrderIntent, bar_time: datetime,
    ) -> Order:
        """Convert an OrderIntent to an engine Order."""
        expiry = None
        if intent.expiry_bars > 0 and intent.signal_timestamp:
            from datetime import timedelta
            tf_min = TIMEFRAME_MINUTES.get(Timeframe.M5, 5)
            expiry = bar_time + timedelta(minutes=tf_min * intent.expiry_bars)

        units = self._compute_units(intent)

        return Order(
            pair=intent.pair,
            direction=intent.direction,
            order_type=OrderType.LIMIT,
            requested_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            units=units,
            created_at=bar_time,
            expires_at=expiry,
        )

    def _compute_units(self, intent: OrderIntent) -> float:
        """Size position based on config risk fraction."""
        risk_fraction = self._cfg.risk.base_risk_per_trade
        equity = self._portfolio.equity({})
        risk_amount = equity * risk_fraction
        risk_dist = abs(intent.entry_price - intent.stop_loss)
        if risk_dist <= 0:
            return 0.0
        return risk_amount / risk_dist

    def _process_exits(
        self,
        pair: TradingPair,
        series: BarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        for pos in list(self._portfolio.open_positions):
            if pos.pair != pair:
                continue
            exit_fill = self._fill_engine.check_exit_conditions(
                pos,
                float(series.high[bar_idx]),
                float(series.low[bar_idx]),
                bar_time,
            )
            if exit_fill is None:
                continue
            self._close_position(
                pos, exit_fill, pair, bar_idx, bar_time, series,
            )

    def _process_exits_bidask(
        self,
        pair: TradingPair,
        ba: BidAskBarSeries,
        mid: BarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        for pos in list(self._portfolio.open_positions):
            if pos.pair != pair:
                continue
            exit_fill = (
                self._bidask_fill_engine.check_exit_conditions_bidask(
                    pos,
                    bid_high=float(ba.bid_high[bar_idx]),
                    bid_low=float(ba.bid_low[bar_idx]),
                    ask_high=float(ba.ask_high[bar_idx]),
                    ask_low=float(ba.ask_low[bar_idx]),
                    bar_time=bar_time,
                )
            )
            if exit_fill is None:
                continue
            self._close_position(
                pos, exit_fill, pair, bar_idx, bar_time, mid,
            )

    def _process_pending_fills_bidask(
        self,
        pair: TradingPair,
        ba: BidAskBarSeries,
        mid: BarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        self._expire_orders(pair, bar_time)
        pending = [
            o
            for o in self._portfolio.pending_orders
            if o.pair == pair
            and self._order_activation_bar.get(o.id, 0) <= bar_idx
        ]
        fills = self._bidask_fill_engine.process_pending_orders(
            pending,
            bid_open=float(ba.bid_open[bar_idx]),
            bid_high=float(ba.bid_high[bar_idx]),
            bid_low=float(ba.bid_low[bar_idx]),
            bid_close=float(ba.bid_close[bar_idx]),
            ask_open=float(ba.ask_open[bar_idx]),
            ask_high=float(ba.ask_high[bar_idx]),
            ask_low=float(ba.ask_low[bar_idx]),
            ask_close=float(ba.ask_close[bar_idx]),
            bar_time=bar_time,
        )
        for order, fill in fills:
            if self._policy.single_position_per_pair and any(
                pos.pair == pair for pos in self._portfolio.open_positions
            ):
                self._reject_overlap(order, bar_time)
                continue
            pos = Position(
                pair=order.pair,
                direction=order.direction,
                entry_price=fill.fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                units=fill.units,
                entry_fill=fill,
                opened_at=bar_time,
                candidate=order.candidate,
            )
            self._portfolio.open_position(pos)
            self._position_entry_bars[pos.id] = bar_idx
            self._position_to_order[pos.id] = order.id
            self._portfolio.remove_order(order.id)

            rt_idx = self._order_to_runtime_idx.get(order.id)
            intent_id = self._order_to_intent.get(order.id, "")

            if rt_idx is not None:
                self._funnels[rt_idx].orders_filled += 1
                self._runtimes[rt_idx].on_order_filled(OrderFilledEvent(
                    order_id=order.id,
                    intent_id=intent_id,
                    fill_price=fill.fill_price,
                    units=fill.units,
                    timestamp=bar_time,
                    position_id=pos.id,
                ))

            same_exit = (
                self._bidask_fill_engine.check_same_bar_exit_bidask(
                    pos, fill.fill_price,
                    bid_high=float(ba.bid_high[bar_idx]),
                    bid_low=float(ba.bid_low[bar_idx]),
                    ask_high=float(ba.ask_high[bar_idx]),
                    ask_low=float(ba.ask_low[bar_idx]),
                    bar_time=bar_time,
                )
            )
            if same_exit is not None:
                self._close_position(
                    pos, same_exit, pair, bar_idx, bar_time, mid,
                )

    def _process_pending_fills(
        self,
        pair: TradingPair,
        series: BarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        self._expire_orders(pair, bar_time)
        pending = [
            o
            for o in self._portfolio.pending_orders
            if o.pair == pair
            and self._order_activation_bar.get(o.id, 0) <= bar_idx
        ]
        fills = self._fill_engine.process_pending_orders(
            pending,
            float(series.open[bar_idx]),
            float(series.high[bar_idx]),
            float(series.low[bar_idx]),
            float(series.close[bar_idx]),
            bar_time,
        )
        for order, fill in fills:
            if self._policy.single_position_per_pair and any(
                pos.pair == pair for pos in self._portfolio.open_positions
            ):
                self._reject_overlap(order, bar_time)
                continue
            pos = Position(
                pair=order.pair,
                direction=order.direction,
                entry_price=fill.fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                units=fill.units,
                entry_fill=fill,
                opened_at=bar_time,
                candidate=order.candidate,
            )
            self._portfolio.open_position(pos)
            self._position_entry_bars[pos.id] = bar_idx
            self._position_to_order[pos.id] = order.id
            self._portfolio.remove_order(order.id)

            rt_idx = self._order_to_runtime_idx.get(order.id)
            intent_id = self._order_to_intent.get(order.id, "")

            if rt_idx is not None:
                self._funnels[rt_idx].orders_filled += 1
                self._runtimes[rt_idx].on_order_filled(OrderFilledEvent(
                    order_id=order.id,
                    intent_id=intent_id,
                    fill_price=fill.fill_price,
                    units=fill.units,
                    timestamp=bar_time,
                    position_id=pos.id,
                ))

            same_bar_exit = self._fill_engine.check_same_bar_exit(
                pos, fill.fill_price,
                float(series.high[bar_idx]),
                float(series.low[bar_idx]),
                bar_time,
            )
            if same_bar_exit is not None:
                self._close_position(
                    pos, same_bar_exit, pair, bar_idx, bar_time, series,
                )

    def _expire_orders(self, pair: TradingPair, bar_time: datetime) -> None:
        expired = [
            order
            for order in self._portfolio.pending_orders
            if order.pair == pair
            and order.expires_at is not None
            and bar_time >= order.expires_at
        ]
        for order in expired:
            order.state = OrderState.EXPIRED
            self._portfolio.remove_order(order.id)
            rt_idx = self._order_to_runtime_idx.get(order.id)
            intent_id = self._order_to_intent.get(order.id, "")
            if rt_idx is not None:
                self._funnels[rt_idx].orders_expired += 1
                self._runtimes[rt_idx].on_order_cancelled(OrderCancelledEvent(
                    order_id=order.id,
                    intent_id=intent_id,
                    reason="expired",
                    timestamp=bar_time,
                ))

    def _reject_overlap(self, order: Order, bar_time: datetime) -> None:
        order.state = OrderState.CANCELLED
        self._portfolio.remove_order(order.id)
        rt_idx = self._order_to_runtime_idx.get(order.id)
        if rt_idx is None:
            return
        self._funnels[rt_idx].orders_cancelled += 1
        self._funnels[rt_idx].position_overlap_rejections += 1
        self._runtimes[rt_idx].on_order_cancelled(OrderCancelledEvent(
            order_id=order.id,
            intent_id=self._order_to_intent.get(order.id, ""),
            reason="position_overlap",
            timestamp=bar_time,
        ))

    def _cancel_all_pending(self, reason: str, bar_time: datetime) -> None:
        for order in list(self._portfolio.pending_orders):
            order.state = OrderState.CANCELLED
            self._portfolio.remove_order(order.id)
            rt_idx = self._order_to_runtime_idx.get(order.id)
            if rt_idx is not None:
                self._funnels[rt_idx].orders_cancelled += 1
                self._runtimes[rt_idx].on_order_cancelled(OrderCancelledEvent(
                    order_id=order.id,
                    intent_id=self._order_to_intent.get(order.id, ""),
                    reason=reason,
                    timestamp=bar_time,
                ))

    @staticmethod
    def _same_time_basis(value: datetime, reference: datetime) -> datetime:
        if reference.tzinfo is None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        if reference.tzinfo is not None and value.tzinfo is None:
            return value.replace(tzinfo=reference.tzinfo)
        return value

    def _position_runtime(self, pos: Position) -> tuple[int | None, str]:
        order_id = self._position_to_order.get(pos.id, "")
        rt_idx = self._order_to_runtime_idx.get(order_id)
        session = self._runtimes[rt_idx].session if rt_idx is not None else ""
        return rt_idx, session

    def _process_protocol_time_exits_bidask(
        self,
        pair: TradingPair,
        ba: BidAskBarSeries,
        mid: BarSeries,
        bar_idx: int,
        bar_time: datetime,
        *,
        next_bar_time: datetime | None,
        is_final_bar: bool,
    ) -> None:
        bar_end = bar_time + timedelta(minutes=TIMEFRAME_MINUTES[mid.timeframe])
        for pos in list(self._portfolio.open_positions):
            if pos.pair != pair:
                continue
            rt_idx, session = self._position_runtime(pos)
            exit_kind = ""
            if (
                self._policy.close_at_session_cutoff
                and self._policy.session_cutoff_resolver is not None
                and pos.opened_at is not None
            ):
                cutoff = self._policy.session_cutoff_resolver(pos.opened_at, session)
                cutoff = self._same_time_basis(cutoff, bar_end)
                if self._reaches_boundary(
                    bar_time, bar_end, next_bar_time, cutoff,
                ):
                    exit_kind = "originating_session_cutoff"
            if (
                not exit_kind
                and self._policy.close_at_fx_week_end
                and self._policy.fx_week_close_resolver is not None
            ):
                week_close = self._policy.fx_week_close_resolver(bar_time)
                week_close = self._same_time_basis(week_close, bar_end)
                if self._reaches_boundary(
                    bar_time, bar_end, next_bar_time, week_close,
                ):
                    exit_kind = "fx_week_safety_close"
            if not exit_kind and self._policy.close_at_final_bar and is_final_bar:
                exit_kind = "final_available_certified_bar"
            if not exit_kind:
                continue

            exit_direction = (
                Direction.SHORT if pos.direction == Direction.LONG else Direction.LONG
            )
            executable_close = (
                float(ba.bid_close[bar_idx])
                if pos.direction == Direction.LONG
                else float(ba.ask_close[bar_idx])
            )
            fill_price, spread, slippage = self._bidask_slippage.apply(
                executable_close, exit_direction, pair,
            )
            self._position_exit_kind[pos.id] = exit_kind
            self._close_position(
                pos,
                Fill(
                    order_id=pos.id,
                    fill_price=fill_price,
                    units=pos.units,
                    spread_cost=spread,
                    slippage=slippage,
                    timestamp=bar_time,
                    reason=FillReason.MANUAL_CLOSE,
                ),
                pair,
                bar_idx,
                bar_time,
                mid,
            )
            if rt_idx is not None:
                if exit_kind == "originating_session_cutoff":
                    self._funnels[rt_idx].session_exits += 1
                elif exit_kind == "fx_week_safety_close":
                    self._funnels[rt_idx].fx_week_exits += 1
                else:
                    self._funnels[rt_idx].final_bar_exits += 1

        if self._policy.close_at_session_cutoff:
            for order in list(self._portfolio.pending_orders):
                if order.pair != pair:
                    continue
                rt_idx = self._order_to_runtime_idx.get(order.id)
                if rt_idx is None:
                    continue
                session = self._runtimes[rt_idx].session
                resolver = self._policy.session_cutoff_resolver
                if resolver is None or order.created_at is None:
                    continue
                cutoff = self._same_time_basis(resolver(order.created_at, session), bar_end)
                if self._reaches_boundary(
                    bar_time, bar_end, next_bar_time, cutoff,
                ):
                    order.state = OrderState.CANCELLED
                    self._portfolio.remove_order(order.id)
                    self._funnels[rt_idx].orders_cancelled += 1
                    self._runtimes[rt_idx].on_order_cancelled(OrderCancelledEvent(
                        order_id=order.id,
                        intent_id=self._order_to_intent.get(order.id, ""),
                        reason="originating_session_cutoff",
                        timestamp=bar_time,
                    ))

    @staticmethod
    def _reaches_boundary(
        bar_time: datetime,
        bar_end: datetime,
        next_bar_time: datetime | None,
        boundary: datetime,
    ) -> bool:
        if bar_end >= boundary:
            return True
        return (
            bar_time < boundary
            and next_bar_time is not None
            and next_bar_time >= boundary
        )

    def _bar_reaches_session_cutoff(
        self,
        bar_time: datetime,
        next_bar_time: datetime | None,
        session: str,
        timeframe: Timeframe,
    ) -> bool:
        if (
            not self._policy.close_at_session_cutoff
            or self._policy.session_cutoff_resolver is None
        ):
            return False
        bar_end = bar_time + timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        cutoff = self._same_time_basis(
            self._policy.session_cutoff_resolver(bar_time, session),
            bar_end,
        )
        return self._reaches_boundary(
            bar_time, bar_end, next_bar_time, cutoff,
        )

    @staticmethod
    def _validate_bidask_bar(
        series: BidAskBarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        values = (
            series.bid_open[bar_idx], series.bid_high[bar_idx],
            series.bid_low[bar_idx], series.bid_close[bar_idx],
            series.ask_open[bar_idx], series.ask_high[bar_idx],
            series.ask_low[bar_idx], series.ask_close[bar_idx],
        )
        if not all(np.isfinite(value) and value > 0 for value in values):
            raise ValueError(f"EXECUTION_DATA_MISSING at {bar_time.isoformat()}")

    @staticmethod
    def _offset_snapshot_indices(
        snapshot: StructureSnapshot,
        offset: int,
    ) -> None:
        if offset == 0:
            return
        snapshot.bar_index += offset
        snapshot.swings = [
            replace(item, bar_index=item.bar_index + offset)
            for item in snapshot.swings
        ]
        snapshot.breaks = [
            replace(
                item,
                break_bar_index=item.break_bar_index + offset,
                swing_broken=replace(
                    item.swing_broken,
                    bar_index=item.swing_broken.bar_index + offset,
                ),
            )
            for item in snapshot.breaks
        ]
        snapshot.liquidity_levels = [
            replace(
                item,
                formation_index=item.formation_index + offset,
                sweep_index=(
                    item.sweep_index + offset
                    if item.sweep_index is not None
                    else None
                ),
            )
            for item in snapshot.liquidity_levels
        ]
        snapshot.active_fvgs = [
            replace(item, bar_index=item.bar_index + offset)
            for item in snapshot.active_fvgs
        ]
        snapshot.active_order_blocks = [
            replace(item, bar_index=item.bar_index + offset)
            for item in snapshot.active_order_blocks
        ]
        snapshot.displacements = [
            replace(item, bar_index=item.bar_index + offset)
            for item in snapshot.displacements
        ]
        snapshot.session_windows = [
            replace(
                item,
                high_index=item.high_index + offset,
                low_index=item.low_index + offset,
            )
            for item in snapshot.session_windows
        ]

    def _process_swap(self, pair: TradingPair, bar_time: datetime) -> None:
        """Apply swap charges for positions crossing rollover."""
        prev_time = self._prev_bar_times.get(pair)
        if prev_time is None:
            return

        if not self._swap_calc.crosses_rollover(prev_time, bar_time):
            return

        for pos in self._portfolio.open_positions:
            if pos.pair != pair:
                continue
            swap = self._swap_calc.daily_swap(
                pair, pos.direction.value, pos.units,
                bar_time.weekday(),
            )
            if pos.id not in self._position_swap:
                self._position_swap[pos.id] = 0.0
            self._position_swap[pos.id] += swap

    def _close_position(
        self,
        pos: Position,
        exit_fill: Any,
        pair: TradingPair,
        bar_idx: int,
        bar_time: datetime,
        mid_series: BarSeries,
    ) -> None:
        """Unified position close for both mid and bid/ask execution."""
        pos.exit_fill = exit_fill
        pos.closed_at = bar_time
        gross_pnl = self._compute_pnl(pos, exit_fill.fill_price)

        ba_effect = 0.0
        if self._execution_mode == EXECUTION_MODE_BID_ASK:
            mid_close = float(mid_series.close[bar_idx])
            mid_open_price = float(
                mid_series.open[
                    self._position_entry_bars.get(pos.id, bar_idx)
                ]
            )
            ideal_pnl = self._compute_pnl_raw(
                pos.direction, mid_open_price, mid_close, pos.units,
            )
            ba_effect = ideal_pnl - gross_pnl

        commission_cost = 0.0
        if (
            self._cfg.backtest.commission_per_lot > 0
            and self._cfg.backtest.lot_size > 0
        ):
            lots = pos.units / self._cfg.backtest.lot_size
            commission_cost = lots * self._cfg.backtest.commission_per_lot

        swap_cost = self._position_swap.pop(pos.id, 0.0)
        spread_cost = exit_fill.spread_cost
        slippage_cost = exit_fill.slippage

        net_pnl = gross_pnl - commission_cost + swap_cost

        self._portfolio.close_position(pos.id, net_pnl)

        entry_bar = self._position_entry_bars.pop(pos.id, 0)
        entry_session = (
            classify_session(pos.opened_at, self._cfg.sessions)
            if pos.opened_at
            else None
        )
        self._ledger.record_trade(
            pos, exit_fill.fill_price, bar_time,
            entry_bar=entry_bar, exit_bar=bar_idx,
            session=entry_session,
        )

        order_id = self._position_to_order.pop(pos.id, "")
        intent_id = self._order_to_intent.get(order_id, "")
        rt_idx = self._order_to_runtime_idx.get(order_id)

        if exit_fill.reason == FillReason.STOP_LOSS_HIT:
            if rt_idx is not None:
                self._funnels[rt_idx].sl_exits += 1
        elif exit_fill.reason == FillReason.TAKE_PROFIT_HIT:
            if rt_idx is not None:
                self._funnels[rt_idx].tp_exits += 1

        if rt_idx is not None:
            runtime = self._runtimes[rt_idx]
            self._funnels[rt_idx].positions_closed += 1
            runtime.on_position_closed(PositionClosedEvent(
                position_id=pos.id,
                order_id=order_id,
                intent_id=intent_id,
                exit_price=exit_fill.fill_price,
                pnl=net_pnl,
                gross_pnl=gross_pnl,
                spread_cost=spread_cost,
                commission_cost=commission_cost,
                slippage_cost=slippage_cost,
                swap_cost=swap_cost,
                reason=exit_fill.reason.value,
                timestamp=bar_time,
            ))

        self._trade_records.append(TradeRecord(
            position_id=pos.id,
            order_id=order_id,
            intent_id=intent_id,
            family=(
                self._runtimes[rt_idx].family
                if rt_idx is not None else ""
            ),
            pair=pair.value,
            direction=pos.direction.value,
            session=(
                self._runtimes[rt_idx].session
                if rt_idx is not None else ""
            ),
            entry_price=pos.entry_price,
            exit_price=exit_fill.fill_price,
            units=pos.units,
            gross_pnl=gross_pnl,
            bid_ask_execution_effect=ba_effect,
            spread_cost=spread_cost,
            commission_cost=commission_cost,
            slippage_cost=slippage_cost,
            swap_cost=swap_cost,
            net_pnl=net_pnl,
            entry_bar=entry_bar,
            exit_bar=bar_idx,
            entry_time=pos.opened_at,
            exit_time=bar_time,
            price_mode=self._execution_mode,
            exit_reason=(
                self._position_exit_kind.pop(pos.id, "")
                or exit_fill.reason.value
            ),
        ))

    @staticmethod
    def _compute_pnl(pos: Position, exit_price: float) -> float:
        if pos.direction == Direction.LONG:
            return (exit_price - pos.entry_price) * pos.units
        return (pos.entry_price - exit_price) * pos.units

    @staticmethod
    def _compute_pnl_raw(
        direction: Direction,
        entry: float,
        exit_price: float,
        units: float,
    ) -> float:
        if direction == Direction.LONG:
            return (exit_price - entry) * units
        return (entry - exit_price) * units

    def get_funnels(self) -> dict[int, EventFunnel]:
        return dict(self._funnels)

    def get_trade_records(self) -> list[TradeRecord]:
        return list(self._trade_records)

    def reconcile(self) -> RuntimeReconciliation:
        """Verify lifecycle consistency between runtimes and ledger."""
        recon = RuntimeReconciliation()

        for rec in self._trade_records:
            if rec.order_id and rec.intent_id:
                recon.filled_with_matching_trade += 1
            else:
                recon.orphan_trades += 1

        for rec in self._trade_records:
            if rec.exit_time is not None:
                recon.closed_with_matching_close += 1

        for _rt_idx, funnel in self._funnels.items():
            if funnel.orders_expired > 0:
                recon.expired_without_fill += funnel.orders_expired

        if recon.filled_with_matching_trade != len(self._trade_records):
            recon.violations.append(
                f"Trade records: {len(self._trade_records)} vs "
                f"matched fills: {recon.filled_with_matching_trade}"
            )

        return recon

    def metrics(self, result: BacktestResult) -> PerformanceSummary:
        return compute_metrics(
            result.trades, result.equity_curve, result.initial_capital,
        )
