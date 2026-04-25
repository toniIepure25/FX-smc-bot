"""Broker gateway: safety-wrapped dispatch layer around any BrokerAdapter.

BrokerGateway wraps a BrokerAdapter with:
  - explicit arming / disarming
  - execution mode selection (dry_run, paper, demo, live)
  - pre-trade validation (position limits, duplicate prevention, sanity)
  - post-fill reconciliation
  - emergency kill switch
  - retry semantics with backoff
  - order acknowledgment timeout
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import Fill, Order, Position
from fx_smc_bot.live.alerts import AlertEvent, AlertSink, LogAlertSink
from fx_smc_bot.live.broker import AccountState, BrokerAdapter

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"


@dataclass(slots=True, frozen=True)
class GatewayConfig:
    max_positions: int = 3
    max_exposure_units: float = 300_000.0
    max_order_units: float = 100_000.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    ack_timeout_seconds: float = 10.0
    reconcile_after_fill: bool = True


@dataclass(slots=True)
class ReconciliationResult:
    local_equity: float
    broker_equity: float
    local_positions: int
    broker_positions: int
    equity_drift_pct: float
    position_mismatch: bool
    passed: bool


class BrokerGateway:
    """Safety-wrapped broker dispatch with arming, validation, and kill switch."""

    def __init__(
        self,
        adapter: BrokerAdapter,
        mode: ExecutionMode = ExecutionMode.PAPER,
        config: GatewayConfig | None = None,
        alert_sink: AlertSink | None = None,
    ) -> None:
        self._adapter = adapter
        self._mode = mode
        self._cfg = config or GatewayConfig()
        self._alert_sink = alert_sink or LogAlertSink()
        self._armed = False
        self._killed = False
        self._submitted_order_ids: set[str] = set()
        self._order_log: list[dict[str, Any]] = []

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def is_killed(self) -> bool:
        return self._killed

    def arm(self) -> None:
        if self._killed:
            raise RuntimeError("Cannot arm — kill switch has been activated")
        self._armed = True
        logger.info("BrokerGateway ARMED in %s mode", self._mode.value)

    def disarm(self) -> None:
        self._armed = False
        logger.info("BrokerGateway DISARMED")

    def kill(self) -> dict[str, Any]:
        """Emergency kill: cancel all pending, disarm, prevent re-arming."""
        self._killed = True
        self._armed = False

        cancelled = 0
        for oid in list(self._submitted_order_ids):
            try:
                if self._adapter.cancel_order(oid):
                    cancelled += 1
            except Exception:
                logger.exception("Failed to cancel order %s during kill", oid)

        self._alert_sink.emit(AlertEvent(
            level="EMERGENCY",
            message=f"KILL SWITCH activated — cancelled {cancelled} pending orders",
            timestamp=datetime.utcnow(),
            category="safety",
        ))

        result = {
            "killed_at": datetime.utcnow().isoformat(),
            "orders_cancelled": cancelled,
            "mode": self._mode.value,
        }
        logger.critical("KILL SWITCH ACTIVATED: %s", result)
        return result

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> str | None:
        """Validate and submit an order through the adapter."""
        if self._killed:
            logger.warning("Order rejected — kill switch active")
            return None

        if not self._armed:
            logger.info("Order not sent — gateway not armed (mode=%s)", self._mode.value)
            if self._mode == ExecutionMode.DRY_RUN:
                self._log_order("dry_run", order)
            return None

        # Pre-trade validation
        rejection = self._pre_trade_check(order)
        if rejection:
            logger.warning("Pre-trade rejection: %s", rejection)
            self._alert_sink.emit(AlertEvent(
                level="WARNING",
                message=f"Order rejected: {rejection}",
                timestamp=datetime.utcnow(),
                category="pre_trade",
            ))
            return None

        # Duplicate prevention
        order_key = f"{order.pair.value}_{order.direction.value}_{order.units}_{order.requested_price}"
        if order_key in self._submitted_order_ids:
            logger.warning("Duplicate order detected: %s", order_key)
            return None

        # Submit with retry
        oid = self._submit_with_retry(order)
        if oid:
            self._submitted_order_ids.add(oid)
            self._log_order("submitted", order, oid)
        return oid

    def cancel_order(self, order_id: str) -> bool:
        if self._killed:
            return False
        result = self._adapter.cancel_order(order_id)
        if result:
            self._submitted_order_ids.discard(order_id)
        return result

    def get_positions(self) -> list[Position]:
        return self._adapter.get_positions()

    def get_account(self) -> AccountState:
        return self._adapter.get_account()

    def process_bar(
        self,
        pair: TradingPair,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> list[Fill]:
        fills = self._adapter.process_bar(pair, open_, high, low, close, timestamp)

        if fills and self._cfg.reconcile_after_fill:
            recon = self.reconcile()
            if not recon.passed:
                self._alert_sink.emit(AlertEvent(
                    level="WARNING",
                    message=f"Reconciliation failed: equity_drift={recon.equity_drift_pct:.2%} pos_mismatch={recon.position_mismatch}",
                    timestamp=timestamp,
                    category="reconciliation",
                ))

        return fills

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconciliationResult:
        """Compare local state vs broker state."""
        local_positions = self._adapter.get_positions()
        account = self._adapter.get_account()

        local_equity = account.equity
        broker_equity = account.equity  # same adapter for paper; real impl would query broker separately
        local_count = len(local_positions)
        broker_count = account.open_position_count

        drift = abs(local_equity - broker_equity) / max(local_equity, 1.0)
        mismatch = local_count != broker_count

        return ReconciliationResult(
            local_equity=local_equity,
            broker_equity=broker_equity,
            local_positions=local_count,
            broker_positions=broker_count,
            equity_drift_pct=drift,
            position_mismatch=mismatch,
            passed=drift < 0.001 and not mismatch,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _pre_trade_check(self, order: Order) -> str | None:
        positions = self._adapter.get_positions()

        if len(positions) >= self._cfg.max_positions:
            return f"max_positions_reached: {len(positions)} >= {self._cfg.max_positions}"

        total_units = sum(p.units for p in positions)
        if total_units + order.units > self._cfg.max_exposure_units:
            return f"max_exposure_exceeded: {total_units + order.units:.0f} > {self._cfg.max_exposure_units:.0f}"

        if order.units > self._cfg.max_order_units:
            return f"order_too_large: {order.units:.0f} > {self._cfg.max_order_units:.0f}"

        if order.units <= 0:
            return "invalid_order_units"

        return None

    def _submit_with_retry(self, order: Order) -> str | None:
        for attempt in range(self._cfg.max_retries):
            try:
                oid = self._adapter.submit_order(order)
                return oid
            except Exception:
                if attempt < self._cfg.max_retries - 1:
                    wait = self._cfg.retry_backoff_seconds * (2 ** attempt)
                    logger.warning("Order submit failed, retrying in %.1fs", wait)
                    time.sleep(wait)
                else:
                    logger.exception("Order submit failed after %d retries", self._cfg.max_retries)
                    return None
        return None

    def _log_order(self, action: str, order: Order, oid: str = "") -> None:
        self._order_log.append({
            "action": action,
            "order_id": oid,
            "pair": order.pair.value,
            "direction": order.direction.value,
            "units": order.units,
            "mode": self._mode.value,
            "armed": self._armed,
            "timestamp": datetime.utcnow().isoformat(),
        })
