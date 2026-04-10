"""Event-driven backtest engine.

Orchestrates the full simulation loop:
  1. Load multi-pair data
  2. Iterate bars chronologically
  3. On each bar: update structure -> generate candidates -> select -> size -> order -> fill -> log
  4. Produce BacktestResult with full trade log and equity curve

The engine is designed to be reproducible: given the same config and data,
it will produce identical results.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Sequence

from fx_smc_bot.config import AppConfig, OperationalState, PAIR_PIP_INFO, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    BacktestResult,
    Direction,
    Order,
    OrderType,
    Position,
    PositionState,
)
from fx_smc_bot.structure.context import build_structure_snapshot
from fx_smc_bot.structure.market_structure import current_regime
from fx_smc_bot.domain import MultiTimeframeContext, StructureRegime, StructureSnapshot
from fx_smc_bot.alpha.candidates import generate_candidates
from fx_smc_bot.alpha.review import CandidateApprovalPipeline, CandidateReview, ReviewCollector
from fx_smc_bot.portfolio.selector import select_candidates
from fx_smc_bot.portfolio.allocator import allocate_risk_budget
from fx_smc_bot.portfolio.state import PortfolioState
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.orders import intent_to_order
from fx_smc_bot.execution.slippage import (
    FixedSpreadSlippage,
    SlippageModel,
    SpreadFromDataSlippage,
    VolatilitySlippage,
)
from fx_smc_bot.risk.drawdown import DrawdownTracker
from fx_smc_bot.risk.sizing import StopBasedSizer
from fx_smc_bot.backtesting.ledger import TradeLedger
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.utils.math import atr as compute_atr

logger = logging.getLogger(__name__)

# Minimum bars required before the structure engine can produce useful output.
_MIN_WARMUP_BARS = 30


class BacktestEngine:
    """Multi-pair event-driven backtest engine."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._cfg = config or AppConfig()
        slippage = self._build_slippage_model()
        self._fill_engine = FillEngine(
            slippage,
            fill_policy=self._cfg.execution.fill_policy,
        )
        self._sizer = StopBasedSizer(self._cfg.backtest.lot_size)
        self._ledger = TradeLedger()
        self._portfolio = PortfolioState(self._cfg.backtest.initial_capital)
        self._dd_tracker = DrawdownTracker(
            self._cfg.backtest.initial_capital, self._cfg.risk,
        )
        self._approval = CandidateApprovalPipeline(self._cfg.risk, self._cfg.alpha)
        self._review_collector = ReviewCollector()
        self._regime_classifier = None
        if self._cfg.ml.enable_regime_tagging:
            try:
                from fx_smc_bot.ml.regime import VolatilityRegimeClassifier
                self._regime_classifier = VolatilityRegimeClassifier(
                    atr_period=self._cfg.structure.atr_period,
                )
            except ImportError:
                pass

    def _build_slippage_model(self) -> SlippageModel:
        model_name = self._cfg.alpha.slippage_model
        if model_name == "volatility":
            return VolatilitySlippage(config=self._cfg.execution)
        if model_name == "spread_from_data":
            return SpreadFromDataSlippage(self._cfg.execution)
        return FixedSpreadSlippage(self._cfg.execution)

    def run(
        self,
        data: dict[TradingPair, BarSeries],
        htf_data: dict[TradingPair, BarSeries] | None = None,
    ) -> BacktestResult:
        """Run the backtest over the provided data.

        Parameters
        ----------
        data : execution-timeframe BarSeries per pair.
        htf_data : optional higher-timeframe BarSeries per pair for HTF context.
        """
        config_hash = hashlib.md5(
            str(self._cfg.model_dump()).encode()
        ).hexdigest()[:12]

        pairs = list(data.keys())
        if not pairs:
            raise ValueError("No data provided")

        # Build synchronized bar index: iterate by timestamp
        all_timestamps = set()
        for series in data.values():
            for ts in series.timestamps:
                all_timestamps.add(ts)

        sorted_ts = sorted(all_timestamps)
        if not sorted_ts:
            raise ValueError("No bars in data")

        # Build index maps: pair -> {timestamp -> bar_index}
        ts_to_idx: dict[TradingPair, dict] = {}
        for pair, series in data.items():
            mapping = {}
            for i, ts in enumerate(series.timestamps):
                mapping[ts] = i
            ts_to_idx[pair] = mapping

        # Pre-compute ATR for each pair
        atr_cache: dict[TradingPair, list[float]] = {}
        for pair, series in data.items():
            atr_vals = compute_atr(series.high, series.low, series.close,
                                   self._cfg.structure.atr_period)
            atr_cache[pair] = atr_vals.tolist()

        start_dt = sorted_ts[0].astype("datetime64[us]").astype(datetime)
        end_dt = sorted_ts[-1].astype("datetime64[us]").astype(datetime)

        # Main simulation loop
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

                # --- Classify regime for this bar ---
                bar_regime: str | None = None
                if self._regime_classifier is not None and bar_idx >= 50:
                    bar_regime = self._regime_classifier.classify(
                        series.high, series.low, series.close, bar_idx,
                    ).value

                # --- Process exits for open positions ---
                for pos in list(self._portfolio.open_positions):
                    if pos.pair != pair:
                        continue
                    exit_fill = self._fill_engine.check_exit_conditions(
                        pos, float(series.high[bar_idx]),
                        float(series.low[bar_idx]), bar_time,
                    )
                    if exit_fill is not None:
                        pos.exit_fill = exit_fill
                        pos.closed_at = bar_time
                        pnl = self._compute_pnl(pos, exit_fill.fill_price)
                        self._portfolio.close_position(pos.id, pnl)
                        self._ledger.record_trade(
                            pos, exit_fill.fill_price, bar_time,
                            exit_bar=bar_idx,
                            regime=bar_regime,
                        )

                # --- Process pending order fills ---
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
                    self._portfolio.remove_order(order.id)

                # --- Skip alpha generation during warmup ---
                if bar_idx < _MIN_WARMUP_BARS:
                    continue

                # --- Build structure and generate candidates ---
                ltf_slice = series.slice(max(0, bar_idx - 200), bar_idx + 1)
                ltf_snapshot = build_structure_snapshot(
                    ltf_slice, self._cfg.structure, self._cfg.sessions,
                )

                htf_snapshot = ltf_snapshot  # default: use same TF
                htf_bias = None
                if htf_data and pair in htf_data:
                    htf_series = htf_data[pair]
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

                current_atr = atr_cache[pair][bar_idx] if bar_idx < len(atr_cache[pair]) else None
                median_atr = float(
                    sorted(atr_cache[pair][:bar_idx + 1])[len(atr_cache[pair][:bar_idx + 1]) // 2]
                ) if bar_idx > 0 else current_atr

                candidates = generate_candidates(
                    mtf_ctx, float(series.close[bar_idx]), bar_time,
                    risk_cfg=self._cfg.risk, session_cfg=self._cfg.sessions,
                    alpha_cfg=self._cfg.alpha,
                )

                if candidates:
                    risk_snap = self._dd_tracker.update(
                        self._portfolio.equity(current_prices), bar_time,
                    )

                    # Pre-selection review: filter candidates via approval pipeline
                    pre_reviews = self._approval.review_candidates(
                        candidates,
                        self._portfolio.open_positions,
                        self._dd_tracker.operational_state,
                        current_regime=bar_regime,
                    )
                    self._review_collector.add(pre_reviews)
                    approved = [r.candidate for r in pre_reviews if r.verdict.value == "accepted"]

                    # Selection with structured constraint capture
                    selection_reviews: list[CandidateReview] = []
                    intents = select_candidates(
                        approved, self._portfolio.open_positions,
                        self._portfolio.equity(current_prices),
                        self._cfg.risk, self._sizer,
                        current_atr=current_atr, median_atr=median_atr,
                        reviews=selection_reviews,
                    )
                    self._review_collector.add(selection_reviews)

                    intents = allocate_risk_budget(
                        intents, self._cfg.risk,
                        self._portfolio.equity(current_prices),
                        throttle_factor=risk_snap.throttle_factor,
                    )

                    # Update volatility slippage per-bar
                    if isinstance(self._fill_engine._slippage, VolatilitySlippage) and current_atr:
                        self._fill_engine._slippage.set_atr(current_atr)

                    for intent in intents:
                        order = intent_to_order(intent, OrderType.MARKET, bar_time)
                        self._portfolio.add_order(order)

            # --- Record equity point ---
            if current_prices:
                eq_point = self._portfolio.equity_point(bar_time, current_prices)
                self._ledger.record_equity(eq_point)

        metadata = {
            "pairs": [p.value for p in pairs],
            **self._review_collector.to_metadata(),
        }

        return BacktestResult(
            config_hash=config_hash,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=self._cfg.backtest.initial_capital,
            final_equity=self._portfolio.equity(current_prices) if current_prices else self._cfg.backtest.initial_capital,
            trades=self._ledger.trades,
            equity_curve=self._ledger.equity_curve,
            metadata=metadata,
        )

    def metrics(self, result: BacktestResult) -> PerformanceSummary:
        return compute_metrics(
            result.trades, result.equity_curve, result.initial_capital,
        )

    @staticmethod
    def _compute_pnl(pos: Position, exit_price: float) -> float:
        if pos.direction == Direction.LONG:
            return (exit_price - pos.entry_price) * pos.units
        return (pos.entry_price - exit_price) * pos.units
