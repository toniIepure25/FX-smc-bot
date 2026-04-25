"""Forward paper-validation runner: live-data event loop with full monitoring.

Unlike PaperTradingRunner (historical replay), ForwardPaperRunner:
  - Accepts a LiveFeedProvider instead of static BarSeries
  - Processes bars incrementally as they arrive
  - Maintains persistent state with full resume support
  - Generates daily/weekly review artifacts
  - Integrates feed-health, drift-detection, and live monitoring
  - Supports graceful start / pause / stop lifecycle
"""

from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fx_smc_bot.alpha.candidates import generate_candidates
from fx_smc_bot.alpha.review import (
    CandidateApprovalPipeline,
    CandidateReview,
    ReviewCollector,
    ReviewVerdict,
)
from fx_smc_bot.config import AppConfig, OperationalState, TradingPair, TIMEFRAME_MINUTES
from fx_smc_bot.data.models import BarBuffer, BarSeries
from fx_smc_bot.data.providers.live_feed import LiveFeedProvider
from fx_smc_bot.domain import Direction, MultiTimeframeContext, OrderType, StructureRegime
from fx_smc_bot.execution.orders import intent_to_order
from fx_smc_bot.live.alerts import AlertEvent, AlertRouter, AlertSink, LogAlertSink
from fx_smc_bot.live.broker import PaperBroker
from fx_smc_bot.live.drift_detector import BaselineProfile, DriftDetector
from fx_smc_bot.live.feed_health import FeedHealthMonitor
from fx_smc_bot.live.journal import EventJournal
from fx_smc_bot.live.monitor import LiveMonitor
from fx_smc_bot.live.state import LiveState, config_fingerprint
from fx_smc_bot.portfolio.allocator import allocate_risk_budget
from fx_smc_bot.portfolio.selector import select_candidates
from fx_smc_bot.risk.constraints import (
    ConstraintChecker,
    DailyStopConstraint,
    MaxDailyTradesConstraint,
    build_full_constraints,
)
from fx_smc_bot.risk.drawdown import DrawdownTracker
from fx_smc_bot.risk.sizing import SizingPolicy, StopBasedSizer
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.utils.math import atr as compute_atr

logger = logging.getLogger(__name__)

_MIN_WARMUP_BARS = 30
_CHECKPOINT_INTERVAL = 50  # bars between checkpoints


class ForwardPaperRunner:
    """Forward paper-validation engine with live feed, monitoring, and resume."""

    def __init__(
        self,
        config: AppConfig,
        feed: LiveFeedProvider,
        output_dir: Path | str = Path("forward_runs"),
        alert_sink: AlertSink | None = None,
        sizing_policy: SizingPolicy | None = None,
        baseline_profile: BaselineProfile | None = None,
        htf_feed: LiveFeedProvider | None = None,
        run_id: str | None = None,
    ) -> None:
        self._cfg = config
        self._feed = feed
        self._htf_feed = htf_feed
        self._run_id = run_id or f"fwd_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._output_dir = Path(output_dir) / self._run_id
        self._output_dir.mkdir(parents=True, exist_ok=True)

        pair = feed.pair
        tf = feed.timeframe
        tf_minutes = TIMEFRAME_MINUTES.get(tf, 60)

        self._broker = PaperBroker(
            initial_capital=config.backtest.initial_capital,
            execution_config=config.execution,
            slippage_model=config.alpha.slippage_model,
        )
        self._journal = EventJournal(self._output_dir / "journal.jsonl", self._run_id)
        self._dd_tracker = DrawdownTracker(config.backtest.initial_capital, config.risk)
        self._sizer = StopBasedSizer(config.backtest.lot_size, policy=sizing_policy)

        # Alert routing
        if isinstance(alert_sink, AlertRouter):
            self._alert_router = alert_sink
        else:
            self._alert_router = AlertRouter(sinks=[alert_sink or LogAlertSink()])

        # Monitoring stack
        self._feed_health = FeedHealthMonitor(bar_interval_minutes=tf_minutes)
        self._monitor = LiveMonitor()
        self._drift = DriftDetector(baseline_profile or BaselineProfile())

        # Bar buffers
        self._buffer = BarBuffer(pair, tf, capacity=2000)
        self._htf_buffer: BarBuffer | None = None
        if htf_feed:
            self._htf_buffer = BarBuffer(htf_feed.pair, htf_feed.timeframe, capacity=500)

        self._approval = CandidateApprovalPipeline(config.risk, config.alpha)
        self._review_collector = ReviewCollector()

        # Persistent constraints
        self._daily_trades_constraint = MaxDailyTradesConstraint()
        self._daily_stop_constraint = DailyStopConstraint()
        base_constraints = build_full_constraints()
        self._persistent_constraints: list[ConstraintChecker] = [
            c for c in base_constraints
            if not isinstance(c, (MaxDailyTradesConstraint, DailyStopConstraint))
        ]
        self._persistent_constraints.append(self._daily_stop_constraint)
        self._persistent_constraints.append(self._daily_trades_constraint)

        self._bars_processed = 0
        self._prev_op_state = OperationalState.ACTIVE
        self._daily_trade_count = 0
        self._last_day: int | None = None
        self._running = False
        self._paused = False

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load_warmup(self, ltf_bars: list, htf_bars: list | None = None) -> None:
        """Pre-populate buffers with historical bars for indicator warmup."""
        for bar in ltf_bars:
            self._buffer.append_bar(bar)
        if htf_bars and self._htf_buffer is not None:
            for bar in htf_bars:
                self._htf_buffer.append_bar(bar)
        logger.info(
            "Warmup loaded: LTF=%d bars, HTF=%d bars",
            len(self._buffer),
            len(self._htf_buffer) if self._htf_buffer is not None else 0,
        )

    def start(self, resume_from: Path | None = None) -> None:
        """Begin the forward paper session. Optionally resume from a checkpoint."""
        if resume_from:
            self._restore(resume_from)

        self._running = True
        self._paused = False

        # Install signal handlers for graceful shutdown
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)

        def _shutdown(signum: int, frame: Any) -> None:
            logger.info("Received signal %d — initiating graceful shutdown", signum)
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self._journal.log("forward_session_start", {
            "run_id": self._run_id,
            "mode": "forward_paper",
            "pair": self._feed.pair.value,
            "timeframe": self._feed.timeframe.value,
            "config_fingerprint": config_fingerprint(self._cfg),
            "resume": resume_from is not None,
        })

        try:
            self._run_loop()
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            self.stop()

    def pause(self) -> None:
        self._paused = True
        self._save_checkpoint()
        self._journal.log("session_paused", {"bars_processed": self._bars_processed})

    def stop(self) -> LiveState:
        """Graceful stop: final checkpoint, session summary, and review artifacts."""
        self._running = False
        final_state = self._save_checkpoint()
        self._write_session_summary()
        self._journal.log("forward_session_stop", {
            "bars_processed": self._bars_processed,
            "final_equity": final_state.equity,
            "mode": "forward_paper",
        })
        return final_state

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _sync_htf_to(self, up_to: datetime) -> None:
        """Drain HTF feed of all bars with timestamps <= *up_to*.

        In replay mode the HTF feed starts from the oldest available bar.
        Without synchronisation the HTF buffer would contain data from a
        completely different time period than the LTF buffer, producing a
        wrong HTF regime and preventing signal generation.

        This method drains the HTF feed forward so that the buffer always
        reflects the market state as of *up_to*.
        """
        if self._htf_feed is None or self._htf_buffer is None:
            return
        while self._htf_feed.is_connected():
            htf_bars = self._htf_feed.poll_new_bars(since=self._htf_buffer.last_timestamp)
            if not htf_bars:
                break
            for htf_bar in htf_bars:
                self._htf_buffer.append_bar(htf_bar)
                if htf_bar.timestamp >= up_to:
                    return

    def _run_loop(self) -> None:
        """Main event loop: poll feed -> process bar -> generate signals -> execute."""
        last_ts = self._buffer.last_timestamp
        last_heartbeat = time.monotonic()
        _HEARTBEAT_INTERVAL = 1800  # log heartbeat every 30 minutes
        _POLL_SLEEP = 30  # seconds between polls when no data

        while self._running:
            if self._paused:
                time.sleep(5)
                continue

            new_bars = self._feed.poll_new_bars(since=last_ts)
            if not new_bars:
                if not self._feed.is_connected():
                    logger.info("Feed disconnected — ending forward loop")
                    break

                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    account = self._broker.get_account()
                    open_count = len(self._broker.get_positions())
                    logger.info(
                        "Heartbeat: bars=%d, equity=$%.2f, open=%d, feed=connected, waiting for market",
                        self._bars_processed, account.equity, open_count,
                    )
                    last_heartbeat = now

                time.sleep(_POLL_SLEEP)
                continue

            for bar in new_bars:
                accepted, reason = self._feed_health.validate_bar(bar)
                if not accepted:
                    self._journal.log("bar_rejected", {
                        "timestamp": bar.timestamp.isoformat(),
                        "reason": reason,
                    })
                    continue

                self._sync_htf_to(bar.timestamp)

                self._buffer.append_bar(bar)
                self._process_bar(bar)
                last_ts = bar.timestamp

                if self._bars_processed % _CHECKPOINT_INTERVAL == 0:
                    self._save_checkpoint()

                if not self._running:
                    break

    def _process_bar(self, bar: Any) -> None:
        """Process a single new bar through the full pipeline."""
        pair = self._feed.pair
        bar_time = bar.timestamp

        self._bars_processed += 1
        account = self._broker.get_account()
        self._monitor.on_bar(bar_time, account.equity)

        # Risk-state update
        self._dd_tracker.update(account.equity, bar_time)
        new_op = self._dd_tracker.operational_state
        if new_op != self._prev_op_state:
            self._handle_state_transition(new_op, bar_time, account.equity)

        # Daily boundary
        bar_day = bar_time.timetuple().tm_yday
        if self._last_day is not None and bar_day != self._last_day:
            self._on_day_boundary(bar_time)
        self._last_day = bar_day

        # Process fills
        fills = self._broker.process_bar(
            pair, bar.open, bar.high, bar.low, bar.close, bar_time,
        )
        for fill in fills:
            self._daily_trade_count += 1
            is_entry = fill.reason.value == "market_open"
            self._monitor.on_fill(bar_time, is_entry=is_entry)
            self._journal.log_fill(
                fill.order_id, fill.fill_price, fill.units,
                fill.reason.value, bar_time=bar_time,
            )
            if is_entry:
                self._daily_trades_constraint.record_trade(bar_time)
            if fill.reason.value in ("stop_loss_hit", "take_profit_hit"):
                pnl = 0.0
                rr = 0.0
                exit_pair = ""
                exit_dir = ""
                entry_price = 0.0
                duration_str = "?"
                for p in self._broker.all_closed_positions:
                    if p.exit_fill and p.exit_fill.order_id == fill.order_id:
                        pnl = p.pnl
                        exit_pair = p.pair.value if hasattr(p, "pair") else ""
                        exit_dir = p.direction.value if hasattr(p, "direction") else ""
                        entry_price = p.entry_price if hasattr(p, "entry_price") else 0.0
                        if p.candidate and p.candidate.risk_distance > 0:
                            rr = abs(pnl / p.units) / p.candidate.risk_distance
                        if hasattr(p, "entry_fill") and p.entry_fill:
                            delta = bar_time - p.entry_fill.fill_time
                            hours = int(delta.total_seconds() // 3600)
                            duration_str = f"{hours}h"
                        break
                self._dd_tracker.record_trade_result(pnl)
                self._monitor.on_trade_close(pnl, rr, bar_time)
                self._drift.record_trade(pnl, rr, bar_time)
                self._alert_router.emit(AlertEvent(
                    level="INFO",
                    message="Trade closed",
                    timestamp=bar_time,
                    category="trade_exit",
                    data={
                        "pair": exit_pair,
                        "direction": exit_dir,
                        "entry": entry_price,
                        "exit": fill.fill_price,
                        "pnl": pnl,
                        "reason": fill.reason.value.replace("_", " ").title(),
                        "duration": duration_str,
                        "timestamp": bar_time.strftime("%Y-%m-%d %H:%M UTC"),
                    },
                ))

        # Skip signal generation if locked/stopped
        if self._dd_tracker.operational_state in (
            OperationalState.LOCKED, OperationalState.STOPPED,
        ):
            return

        if len(self._buffer) < _MIN_WARMUP_BARS:
            return

        # Build structure
        series = self._buffer.to_series()
        n = len(series)
        ltf_start = max(0, n - 201)
        ltf_slice = series.slice(ltf_start, n)
        ltf_snapshot = build_structure_snapshot(
            ltf_slice, self._cfg.structure, self._cfg.sessions,
        )

        htf_bias = None
        htf_snapshot = ltf_snapshot
        if self._htf_buffer is not None and len(self._htf_buffer) > 10:
            htf_series = self._htf_buffer.to_series()
            htf_snap = build_structure_snapshot(
                htf_series, self._cfg.structure, self._cfg.sessions,
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

        # ATR computation
        atr_vals = compute_atr(series.high, series.low, series.close, self._cfg.structure.atr_period)
        current_atr = float(atr_vals[-1]) if len(atr_vals) > 0 else None
        median_atr = float(sorted(atr_vals)[len(atr_vals) // 2]) if len(atr_vals) > 0 else current_atr

        # Generate candidates
        candidates = generate_candidates(
            mtf_ctx, float(series.close[-1]), bar_time,
            risk_cfg=self._cfg.risk, session_cfg=self._cfg.sessions,
            alpha_cfg=self._cfg.alpha,
        )

        # Parity diagnostics — log pipeline state periodically or on events
        if self._bars_processed % 100 == 0 or candidates:
            htf_buf_len = len(self._htf_buffer) if self._htf_buffer is not None else 0
            self._journal.log("pipeline_diagnostic", {
                "bars_processed": self._bars_processed,
                "buffer_len": n,
                "ltf_slice_len": len(ltf_slice),
                "htf_buffer_len": htf_buf_len,
                "ltf_regime": ltf_snapshot.regime.value,
                "htf_regime": htf_snapshot.regime.value,
                "htf_bias": htf_bias.value if htf_bias else None,
                "ltf_swings": len(ltf_snapshot.swings),
                "ltf_breaks": len(ltf_snapshot.breaks),
                "ltf_fvgs": len(ltf_snapshot.active_fvgs),
                "ltf_obs": len(ltf_snapshot.active_order_blocks),
                "candidates_raw": len(candidates),
                "current_atr": current_atr,
            }, bar_time=bar_time)

        for c in candidates:
            self._journal.log_signal(
                c.pair.value, c.direction.value, c.family.value,
                c.signal_score, bar_time=bar_time,
            )

        accepted_count = 0
        if candidates:
            account = self._broker.get_account()
            risk_snap = self._dd_tracker.update(account.equity, bar_time)

            pre_reviews = self._approval.review_candidates(
                candidates, self._broker.get_positions(),
                self._dd_tracker.operational_state,
            )
            self._review_collector.add(pre_reviews)
            approved = [r.candidate for r in pre_reviews if r.verdict == ReviewVerdict.ACCEPTED]
            accepted_count = len(approved)

            for rev in pre_reviews:
                if rev.verdict == ReviewVerdict.REJECTED:
                    self._journal.log("candidate_rejected", rev.to_dict(), bar_time=bar_time)

            self._daily_stop_constraint.update(
                risk_snap.daily_drawdown, bar_time,
                self._cfg.risk.daily_loss_lockout,
            )
            self._daily_trades_constraint.update_day(bar_time)

            selection_reviews: list[CandidateReview] = []
            intents = select_candidates(
                approved, self._broker.get_positions(),
                account.equity, self._cfg.risk, self._sizer,
                current_atr=current_atr, median_atr=median_atr,
                reviews=selection_reviews,
                constraints=self._persistent_constraints,
                initial_equity=self._dd_tracker.initial_equity,
                peak_equity=self._dd_tracker.peak_equity,
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
                rr = 0.0
                if intent.stop_loss and intent.take_profit:
                    risk_d = abs(float(series.close[-1]) - intent.stop_loss)
                    rew_d = abs(intent.take_profit - float(series.close[-1]))
                    rr = rew_d / risk_d if risk_d > 0 else 0.0
                self._alert_router.emit(AlertEvent(
                    level="INFO",
                    message="New trade opened",
                    timestamp=bar_time,
                    category="trade_entry",
                    data={
                        "pair": order.pair.value,
                        "direction": order.direction.value,
                        "entry": float(series.close[-1]),
                        "sl": intent.stop_loss or 0,
                        "tp": intent.take_profit or 0,
                        "rr": rr,
                        "units": order.units,
                        "timestamp": bar_time.strftime("%Y-%m-%d %H:%M UTC"),
                    },
                ))

        self._monitor.on_candidates(len(candidates), accepted_count, bar_time)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _handle_state_transition(
        self, new_state: OperationalState, bar_time: datetime, equity: float,
    ) -> None:
        history = self._dd_tracker.state_history
        trigger = history[-1].reason if history else f"equity={equity:.2f}"
        self._journal.log_state_transition(
            self._prev_op_state.value, new_state.value,
            reason=trigger, bar_time=bar_time,
        )
        self._alert_router.emit(AlertEvent(
            level="CRITICAL" if new_state == OperationalState.STOPPED else (
                "WARNING" if new_state != OperationalState.ACTIVE else "INFO"
            ),
            message=f"State: {self._prev_op_state.value} -> {new_state.value} ({trigger})",
            timestamp=bar_time,
            category="risk_state",
        ))

        if new_state == OperationalState.LOCKED:
            self._monitor.on_lockout(bar_time)
        elif new_state == OperationalState.THROTTLED:
            self._monitor.on_throttle(bar_time)
        elif new_state == OperationalState.STOPPED:
            self._monitor.on_cb_fire(bar_time)
        elif self._prev_op_state == OperationalState.STOPPED and new_state == OperationalState.ACTIVE:
            self._monitor.on_cb_recovery(bar_time)

        self._prev_op_state = new_state

    def _on_day_boundary(self, bar_time: datetime) -> None:
        daily = self._monitor.daily_summary()
        self._journal.log("daily_summary", daily, bar_time=bar_time)

        day_str = daily.get("day", "unknown")
        review_path = self._output_dir / "reviews" / f"day_{day_str}.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        with open(review_path, "w") as f:
            json.dump(daily, f, indent=2)

        account = self._broker.get_account()
        closed = self._broker.all_closed_positions
        total_pnl = sum(p.pnl for p in closed)
        wins = sum(1 for p in closed if p.pnl > 0)
        day_pnl = daily.get("pnl", 0)

        self._alert_router.emit(AlertEvent(
            level="INFO",
            message="Daily summary",
            timestamp=bar_time,
            category="daily_summary",
            data={
                "date": day_str,
                "equity": account.equity,
                "pnl": day_pnl,
                "trades": self._daily_trade_count,
                "open_positions": len(self._broker.get_positions()),
                "win_rate": wins / len(closed) if closed else 0.0,
                "drawdown": self._dd_tracker.current_drawdown,
                "total_trades": len(closed),
                "total_pnl": total_pnl,
                "status": self._dd_tracker.operational_state.value,
                "feed_status": "connected" if self._feed.is_connected() else "disconnected",
            },
        ))

        self._daily_trade_count = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_checkpoint(self) -> LiveState:
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

        state = LiveState.from_forward_session(
            run_id=self._run_id,
            equity=account.equity,
            cash=account.cash,
            bars_processed=self._bars_processed,
            operational_state=self._dd_tracker.operational_state,
            dd_tracker=self._dd_tracker,
            cfg=self._cfg,
            positions=positions_data,
            orders=orders_data,
            trades_today=self._daily_trade_count,
            last_bar_timestamp=self._buffer.last_timestamp,
        )
        state.save(self._output_dir / "state.json")
        return state

    def _restore(self, checkpoint_path: Path) -> None:
        state = LiveState.load(checkpoint_path)

        if not state.verify_config(self._cfg):
            logger.warning(
                "Config fingerprint mismatch on resume — saved=%s current=%s",
                state.config_fingerprint, config_fingerprint(self._cfg),
            )

        state.restore_drawdown_tracker(self._dd_tracker)
        self._bars_processed = state.bars_processed
        self._daily_trade_count = state.trades_today
        self._prev_op_state = OperationalState(state.operational_state)

        logger.info(
            "Restored forward session %s: bars=%d equity=%.2f state=%s",
            state.run_id, state.bars_processed, state.equity, state.operational_state,
        )

    # ------------------------------------------------------------------
    # Review artifacts
    # ------------------------------------------------------------------

    def _write_session_summary(self) -> None:
        closed = self._broker.all_closed_positions
        total_pnl = sum(p.pnl for p in closed)
        wins = sum(1 for p in closed if p.pnl > 0)

        summary: dict[str, Any] = {
            "run_id": self._run_id,
            "mode": "forward_paper",
            "bars_processed": self._bars_processed,
            "total_trades": len(closed),
            "win_rate": round(wins / len(closed), 3) if closed else 0.0,
            "total_pnl": round(total_pnl, 2),
            "final_equity": self._broker.get_account().equity,
            "monitor": self._monitor.weekly_summary(),
            "drift": self._drift.summary(),
            "feed_health": self._feed_health.report.to_dict(),
            "reviews": self._review_collector.to_metadata(),
        }

        path = self._output_dir / "session_summary.json"
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info("Session summary written to %s", path)
