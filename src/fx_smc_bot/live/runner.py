"""Paper trading runner: bar-by-bar replay through the broker adapter.

Uses the same signal/risk/portfolio logic as the backtest engine but
routes through the BrokerAdapter interface with full journaling, state
persistence, and operational risk state management.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.config import AppConfig, OperationalState, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    Order,
    OrderType,
    StructureRegime,
)
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.alpha.candidates import generate_candidates
from fx_smc_bot.alpha.review import (
    CandidateApprovalPipeline,
    CandidateReview,
    ReviewCollector,
    ReviewVerdict,
)
from fx_smc_bot.portfolio.selector import select_candidates
from fx_smc_bot.portfolio.allocator import allocate_risk_budget
from fx_smc_bot.execution.orders import intent_to_order
from fx_smc_bot.risk.drawdown import DrawdownTracker
from fx_smc_bot.risk.sizing import StopBasedSizer
from fx_smc_bot.utils.math import atr as compute_atr
from fx_smc_bot.live.broker import PaperBroker
from fx_smc_bot.live.health import HealthMonitor
from fx_smc_bot.live.journal import EventJournal
from fx_smc_bot.live.state import LiveState
from fx_smc_bot.live.alerts import AlertEvent, AlertSink, LogAlertSink

logger = logging.getLogger(__name__)

_MIN_WARMUP_BARS = 30


class PaperTradingRunner:
    """Replay real data through the paper broker with full audit trail."""

    def __init__(
        self,
        config: AppConfig,
        output_dir: Path | str = Path("paper_runs"),
        alert_sink: AlertSink | None = None,
    ) -> None:
        self._cfg = config
        self._run_id = f"paper_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._output_dir = Path(output_dir) / self._run_id
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._broker = PaperBroker(
            initial_capital=config.backtest.initial_capital,
            execution_config=config.execution,
            slippage_model=config.alpha.slippage_model,
        )
        self._journal = EventJournal(self._output_dir / "journal.jsonl", self._run_id)
        self._dd_tracker = DrawdownTracker(config.backtest.initial_capital, config.risk)
        self._sizer = StopBasedSizer(config.backtest.lot_size)
        self._alert_sink = alert_sink or LogAlertSink()
        self._health = HealthMonitor(alert_sink=self._alert_sink)
        self._approval = CandidateApprovalPipeline(config.risk, config.alpha)
        self._review_collector = ReviewCollector()
        self._bars_processed = 0
        self._prev_op_state = OperationalState.ACTIVE
        self._daily_trade_count = 0
        self._last_day: int | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    def run(
        self,
        data: dict[TradingPair, BarSeries],
        htf_data: dict[TradingPair, BarSeries] | None = None,
    ) -> LiveState:
        """Execute full paper trading replay and return final state."""
        self._journal.log("run_start", {"pairs": [p.value for p in data.keys()],
                                         "config_env": self._cfg.environment})

        pairs = list(data.keys())
        all_timestamps: set = set()
        for series in data.values():
            for ts in series.timestamps:
                all_timestamps.add(ts)
        sorted_ts = sorted(all_timestamps)

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

        for ts in sorted_ts:
            bar_time = ts.astype("datetime64[us]").astype(datetime)
            current_prices: dict[str, float] = {}

            self._health.on_bar(bar_time)

            # Daily boundary detection for summary events
            bar_day = bar_time.timetuple().tm_yday
            if self._last_day is not None and bar_day != self._last_day:
                self._journal.log("daily_summary", {
                    "day": self._last_day,
                    "equity": self._broker.get_account().equity,
                    "trades_today": self._daily_trade_count,
                    "operational_state": self._dd_tracker.operational_state.value,
                })
                self._daily_trade_count = 0
            self._last_day = bar_day

            for pair in pairs:
                if ts not in ts_to_idx[pair]:
                    continue
                bar_idx = ts_to_idx[pair][ts]
                series = data[pair]

                current_prices[pair.value] = float(series.close[bar_idx])

                fills = self._broker.process_bar(
                    pair,
                    float(series.open[bar_idx]),
                    float(series.high[bar_idx]),
                    float(series.low[bar_idx]),
                    float(series.close[bar_idx]),
                    bar_time,
                )
                for fill in fills:
                    self._health.on_fill()
                    self._daily_trade_count += 1
                    self._journal.log_fill(
                        fill.order_id, fill.fill_price, fill.units, fill.reason.value,
                        bar_time=bar_time,
                    )
                    if fill.reason.value in ("stop_loss_hit", "take_profit_hit"):
                        pnl = 0.0
                        for p in self._broker.all_closed_positions:
                            if p.exit_fill and p.exit_fill.order_id == fill.order_id:
                                pnl = p.pnl
                                break
                        self._dd_tracker.record_trade_result(pnl)

                if self._dd_tracker.operational_state in (
                    OperationalState.LOCKED, OperationalState.STOPPED,
                ):
                    continue

                if bar_idx < _MIN_WARMUP_BARS:
                    continue

                ltf_slice = series.slice(max(0, bar_idx - 200), bar_idx + 1)
                ltf_snapshot = build_structure_snapshot(
                    ltf_slice, self._cfg.structure, self._cfg.sessions,
                )

                htf_bias = None
                htf_snapshot = ltf_snapshot
                if htf_data and pair in htf_data:
                    htf_snap = build_structure_snapshot(
                        htf_data[pair], self._cfg.structure, self._cfg.sessions,
                    )
                    htf_snapshot = htf_snap
                    if htf_snap.regime == StructureRegime.BULLISH:
                        htf_bias = Direction.LONG
                    elif htf_snap.regime == StructureRegime.BEARISH:
                        htf_bias = Direction.SHORT

                mtf_ctx = MultiTimeframeContext(
                    pair=pair,
                    htf_snapshot=htf_snapshot,
                    ltf_snapshot=ltf_snapshot,
                    htf_bias=htf_bias,
                )

                current_atr = atr_cache[pair][bar_idx] if bar_idx < len(atr_cache[pair]) else None
                median_atr = float(
                    sorted(atr_cache[pair][:bar_idx + 1])[len(atr_cache[pair][:bar_idx + 1]) // 2]
                ) if bar_idx > 0 else current_atr

                candidates = generate_candidates(
                    mtf_ctx, float(series.close[bar_idx]), bar_time,
                    risk_cfg=self._cfg.risk, session_cfg=self._cfg.sessions,
                    alpha_cfg=self._cfg.alpha,
                )

                for c in candidates:
                    self._journal.log_signal(
                        c.pair.value, c.direction.value, c.family.value, c.signal_score,
                        bar_time=bar_time,
                    )

                if candidates:
                    account = self._broker.get_account()
                    risk_snap = self._dd_tracker.update(account.equity, bar_time)

                    # Track operational state transitions
                    new_op_state = self._dd_tracker.operational_state
                    if new_op_state != self._prev_op_state:
                        self._journal.log_state_transition(
                            self._prev_op_state.value, new_op_state.value,
                            reason=f"equity={account.equity:.2f}",
                            bar_time=bar_time,
                        )
                        self._alert_sink.emit(AlertEvent(
                            level="warning" if new_op_state != OperationalState.ACTIVE else "info",
                            message=f"Operational state: {self._prev_op_state.value} -> {new_op_state.value}",
                            timestamp=bar_time,
                            category="risk_state",
                        ))
                        self._health.on_state_change(new_op_state, bar_time)
                        self._prev_op_state = new_op_state

                    # Pre-selection review
                    pre_reviews = self._approval.review_candidates(
                        candidates,
                        self._broker.get_positions(),
                        self._dd_tracker.operational_state,
                    )
                    self._review_collector.add(pre_reviews)
                    approved = [r.candidate for r in pre_reviews if r.verdict == ReviewVerdict.ACCEPTED]

                    # Log rejections
                    for rev in pre_reviews:
                        if rev.verdict == ReviewVerdict.REJECTED:
                            self._journal.log("candidate_rejected", rev.to_dict(), bar_time=bar_time)

                    selection_reviews: list[CandidateReview] = []
                    intents = select_candidates(
                        approved, self._broker.get_positions(),
                        account.equity, self._cfg.risk, self._sizer,
                        current_atr=current_atr, median_atr=median_atr,
                        reviews=selection_reviews,
                    )
                    self._review_collector.add(selection_reviews)

                    intents = allocate_risk_budget(
                        intents, self._cfg.risk, account.equity,
                        throttle_factor=risk_snap.throttle_factor,
                    )

                    for intent in intents:
                        order = intent_to_order(intent, OrderType.MARKET, bar_time)
                        oid = self._broker.submit_order(order)
                        self._journal.log_order(
                            oid, order.pair.value, order.direction.value,
                            order.order_type.value, order.units,
                            bar_time=bar_time,
                        )

            self._bars_processed += 1

            if self._bars_processed % 500 == 0:
                self._save_checkpoint(bar_time)

        final_time = sorted_ts[-1].astype("datetime64[us]").astype(datetime) if sorted_ts else datetime.utcnow()
        final_state = self._save_checkpoint(final_time)

        # End-of-run summary with trade blotter stats
        closed = self._broker.all_closed_positions
        total_pnl = sum(p.pnl for p in closed)
        wins = sum(1 for p in closed if p.pnl > 0)
        self._journal.log("run_complete", {
            "bars_processed": self._bars_processed,
            "total_events": self._journal.event_count,
            "final_equity": final_state.equity,
            "total_trades": len(closed),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(wins / len(closed), 3) if closed else 0.0,
            "health": self._health.snapshot(final_time).to_dict(),
            **self._review_collector.to_metadata(),
        })
        return final_state

    def _save_checkpoint(self, timestamp: datetime) -> LiveState:
        account = self._broker.get_account()

        positions_data = [
            {"pair": p.pair.value, "direction": p.direction.value,
             "entry_price": p.entry_price, "units": p.units,
             "stop_loss": p.stop_loss, "take_profit": p.take_profit}
            for p in self._broker.get_positions()
        ]
        orders_data = [
            {"pair": o.pair.value, "direction": o.direction.value,
             "order_type": o.order_type.value, "units": o.units}
            for o in self._broker._pending_orders.values()
        ]

        state = LiveState.from_broker(
            run_id=self._run_id,
            equity=account.equity,
            cash=account.cash,
            bars_processed=self._bars_processed,
            operational_state=self._dd_tracker.operational_state,
            positions=positions_data,
            orders=orders_data,
            consecutive_losses=self._dd_tracker.consecutive_losses,
            trades_today=self._daily_trade_count,
        )
        state.save(self._output_dir / "state.json")
        return state
