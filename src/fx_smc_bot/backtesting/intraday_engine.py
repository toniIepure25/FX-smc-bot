"""Intraday backtest engine for V2 stateful strategy runtimes.

Unlike the legacy BacktestEngine that uses stateless detectors through
generate_candidates(), this engine maintains StatefulStrategyRuntime
instances across bars and feeds execution events back to them.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    BacktestResult,
    Direction,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    StructureRegime,
)
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.slippage import FixedSpreadSlippage
from fx_smc_bot.execution.swap import SwapCalculator
from fx_smc_bot.portfolio.state import PortfolioState
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.utils.math import atr as compute_atr
from fx_smc_bot.utils.time import classify_session

logger = logging.getLogger(__name__)

_MIN_WARMUP_BARS = 30


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
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    swap_cost: float
    net_pnl: float
    entry_bar: int
    exit_bar: int
    entry_time: datetime | None = None
    exit_time: datetime | None = None


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


class IntradayBacktestEngine:
    """Event-driven engine for V2 stateful strategy runtimes.

    Feeds execution events back to the originating runtime and tracks
    full cost decomposition per trade.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        swap_rates: dict | None = None,
    ) -> None:
        self._cfg = config or AppConfig()
        self._fill_engine = FillEngine(
            FixedSpreadSlippage(self._cfg.execution),
            fill_policy=self._cfg.execution.fill_policy,
        )
        self._swap_calc = SwapCalculator(rates=swap_rates)
        self._ledger = TradeLedger(
            commission_per_lot=self._cfg.backtest.commission_per_lot,
            lot_size=self._cfg.backtest.lot_size,
        )
        self._portfolio = PortfolioState(self._cfg.backtest.initial_capital)

        self._runtimes: list[StatefulStrategyRuntime] = []
        self._intent_to_order: dict[str, str] = {}
        self._order_to_intent: dict[str, str] = {}
        self._order_to_runtime_idx: dict[str, int] = {}
        self._position_to_order: dict[str, str] = {}
        self._position_entry_bars: dict[str, int] = {}
        self._position_swap: dict[str, float] = {}
        self._prev_bar_times: dict[TradingPair, datetime] = {}
        self._funnels: dict[int, EventFunnel] = {}
        self._trade_records: list[TradeRecord] = []

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
        data: dict[TradingPair, BarSeries],
        htf_data: dict[TradingPair, BarSeries] | None = None,
    ) -> BacktestResult:
        """Run the backtest using V2 stateful runtimes."""
        config_hash = hashlib.md5(
            str(self._cfg.model_dump()).encode()
        ).hexdigest()[:12]

        pairs = list(data.keys())
        if not pairs:
            raise ValueError("No data provided")

        all_timestamps: set[Any] = set()
        for series in data.values():
            for ts in series.timestamps:
                all_timestamps.add(ts)
        sorted_ts = sorted(all_timestamps)
        if not sorted_ts:
            raise ValueError("No bars in data")

        ts_to_idx: dict[TradingPair, dict] = {}
        for pair, series in data.items():
            mapping = {}
            for i, ts in enumerate(series.timestamps):
                mapping[ts] = i
            ts_to_idx[pair] = mapping

        atr_cache: dict[TradingPair, list[float]] = {}
        for pair, series in data.items():
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

        for ts in sorted_ts:
            bar_time = ts.astype("datetime64[us]").astype(datetime)
            current_prices: dict[str, float] = {}

            for pair in pairs:
                idx_map = ts_to_idx[pair]
                if ts not in idx_map:
                    continue
                bar_idx = idx_map[ts]
                series = data[pair]
                current_prices[pair.value] = float(series.close[bar_idx])

                self._process_exits(pair, series, bar_idx, bar_time)
                self._process_pending_fills(pair, series, bar_idx, bar_time)
                self._process_swap(pair, bar_time)

                if bar_idx < _MIN_WARMUP_BARS:
                    self._prev_bar_times[pair] = bar_time
                    continue

                ltf_slice = series.slice(max(0, bar_idx - 200), bar_idx + 1)
                snapshot = build_structure_snapshot(
                    ltf_slice, self._cfg.structure, self._cfg.sessions,
                )

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
                spread = (
                    float(series.spread[bar_idx])
                    if series.spread is not None and bar_idx < len(series.spread)
                    else self._cfg.execution.default_spread_pips
                    * PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
                )

                ctx = CausalBarContext(
                    pair=pair,
                    timeframe=series.timeframe,
                    bar_idx=bar_idx,
                    timestamp=bar_time,
                    open=series.open,
                    high=series.high,
                    low=series.low,
                    close=series.close,
                    atr=current_atr,
                    spread=spread,
                    snapshot=snapshot,
                    htf_bias=htf_bias,
                    htf_snapshot=htf_snapshot,
                )

                for rt_idx, runtime in enumerate(self._runtimes):
                    if runtime.pair != pair:
                        continue

                    funnel = self._funnels[rt_idx]
                    funnel.bars_processed += 1

                    intents = runtime.on_bar(ctx)

                    for intent in intents:
                        funnel.intents_generated += 1

                        if intent.activation_bar <= bar_idx:
                            intent.activation_bar = bar_idx + 1

                        order = self._intent_to_order_obj(intent, bar_time)
                        self._portfolio.add_order(order)
                        self._intent_to_order[intent.intent_id] = order.id
                        self._order_to_intent[order.id] = intent.intent_id
                        self._order_to_runtime_idx[order.id] = rt_idx

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

        metadata = {
            "pairs": [p.value for p in pairs],
            "runtimes": len(self._runtimes),
            "trade_records": len(self._trade_records),
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
        risk_fraction = self._cfg.risk.risk_per_trade
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

            pos.exit_fill = exit_fill
            pos.closed_at = bar_time
            gross_pnl = self._compute_pnl(pos, exit_fill.fill_price)

            commission_cost = 0.0
            if self._cfg.backtest.commission_per_lot > 0 and self._cfg.backtest.lot_size > 0:
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

            exit_reason = exit_fill.reason.value
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
                    reason=exit_reason,
                    timestamp=bar_time,
                ))

            self._trade_records.append(TradeRecord(
                position_id=pos.id,
                order_id=order_id,
                intent_id=intent_id,
                family=self._runtimes[rt_idx].family if rt_idx is not None else "",
                pair=pair.value,
                direction=pos.direction.value,
                session=self._runtimes[rt_idx].session if rt_idx is not None else "",
                entry_price=pos.entry_price,
                exit_price=exit_fill.fill_price,
                units=pos.units,
                gross_pnl=gross_pnl,
                spread_cost=spread_cost,
                commission_cost=commission_cost,
                slippage_cost=slippage_cost,
                swap_cost=swap_cost,
                net_pnl=net_pnl,
                entry_bar=entry_bar,
                exit_bar=bar_idx,
                entry_time=pos.opened_at,
                exit_time=bar_time,
            ))

    def _process_pending_fills(
        self,
        pair: TradingPair,
        series: BarSeries,
        bar_idx: int,
        bar_time: datetime,
    ) -> None:
        pending = [o for o in self._portfolio.pending_orders if o.pair == pair]
        fills = self._fill_engine.process_pending_orders(
            pending,
            float(series.open[bar_idx]),
            float(series.high[bar_idx]),
            float(series.low[bar_idx]),
            float(series.close[bar_idx]),
            bar_time,
        )
        for order, fill in fills:
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
                pos.exit_fill = same_bar_exit
                pos.closed_at = bar_time
                gross_pnl = self._compute_pnl(pos, same_bar_exit.fill_price)

                commission_cost = 0.0
                if self._cfg.backtest.commission_per_lot > 0 and self._cfg.backtest.lot_size > 0:
                    lots = pos.units / self._cfg.backtest.lot_size
                    commission_cost = lots * self._cfg.backtest.commission_per_lot

                net_pnl = gross_pnl - commission_cost

                self._portfolio.close_position(pos.id, net_pnl)

                entry_session = (
                    classify_session(pos.opened_at, self._cfg.sessions)
                    if pos.opened_at
                    else None
                )
                self._ledger.record_trade(
                    pos, same_bar_exit.fill_price, bar_time,
                    entry_bar=bar_idx, exit_bar=bar_idx,
                    session=entry_session,
                )

                order_id_for_close = order.id
                if rt_idx is not None:
                    self._funnels[rt_idx].positions_closed += 1
                    self._runtimes[rt_idx].on_position_closed(PositionClosedEvent(
                        position_id=pos.id,
                        order_id=order_id_for_close,
                        intent_id=intent_id,
                        exit_price=same_bar_exit.fill_price,
                        pnl=net_pnl,
                        gross_pnl=gross_pnl,
                        spread_cost=same_bar_exit.spread_cost,
                        commission_cost=commission_cost,
                        slippage_cost=same_bar_exit.slippage,
                        swap_cost=0.0,
                        reason=same_bar_exit.reason.value,
                        timestamp=bar_time,
                    ))

                self._trade_records.append(TradeRecord(
                    position_id=pos.id,
                    order_id=order_id_for_close,
                    intent_id=intent_id,
                    family=self._runtimes[rt_idx].family if rt_idx is not None else "",
                    pair=pair.value,
                    direction=pos.direction.value,
                    session=self._runtimes[rt_idx].session if rt_idx is not None else "",
                    entry_price=pos.entry_price,
                    exit_price=same_bar_exit.fill_price,
                    units=pos.units,
                    gross_pnl=gross_pnl,
                    spread_cost=same_bar_exit.spread_cost,
                    commission_cost=commission_cost,
                    slippage_cost=same_bar_exit.slippage,
                    swap_cost=0.0,
                    net_pnl=net_pnl,
                    entry_bar=bar_idx,
                    exit_bar=bar_idx,
                    entry_time=pos.opened_at,
                    exit_time=bar_time,
                ))

        expired = [
            o for o in self._portfolio.pending_orders
            if o.pair == pair
            and o.state == OrderState.PENDING
            and o.expires_at is not None
            and bar_time >= o.expires_at
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

    @staticmethod
    def _compute_pnl(pos: Position, exit_price: float) -> float:
        if pos.direction == Direction.LONG:
            return (exit_price - pos.entry_price) * pos.units
        return (pos.entry_price - exit_price) * pos.units

    def get_funnels(self) -> dict[int, EventFunnel]:
        return dict(self._funnels)

    def get_trade_records(self) -> list[TradeRecord]:
        return list(self._trade_records)

    def reconcile(self) -> RuntimeReconciliation:
        """Verify lifecycle consistency between runtimes and ledger."""
        recon = RuntimeReconciliation()

        for rec in self._trade_records:
            oid = self._position_to_order.get(rec.position_id)
            if oid:
                recon.filled_with_matching_trade += 1

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
