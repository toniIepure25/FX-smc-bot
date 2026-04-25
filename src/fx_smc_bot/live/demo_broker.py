"""Demo broker adapter scaffold for MT4/MT5/cTrader integration.

Implements the BrokerAdapter protocol with stub methods that define
clear contracts, error handling, and connection lifecycle.  This is
the integration point for a real demo account — the strategy logic
remains unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import (
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    Position,
    PositionState,
)
from fx_smc_bot.live.broker import AccountState

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class DemoBrokerAdapter:
    """Scaffold for real broker demo account integration.

    All order/position methods raise NotImplementedError until the
    concrete broker client (e.g. MT5 Python API, cTrader Open API)
    is wired in.  The adapter contract is fully defined here.

    Connection lifecycle:
        adapter = DemoBrokerAdapter(config)
        adapter.connect()
        ... trading loop ...
        adapter.disconnect()
    """

    def __init__(
        self,
        broker_name: str = "mt5_demo",
        server: str = "",
        login: int = 0,
        password: str = "",
        lot_size: float = 100_000.0,
    ) -> None:
        self._broker_name = broker_name
        self._server = server
        self._login = login
        self._password = password
        self._lot_size = lot_size
        self._state = ConnectionState.DISCONNECTED
        self._last_heartbeat: datetime | None = None

    @property
    def connection_state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish connection to the demo account.

        Returns True on success.  Real implementation would:
          1. Initialize the broker API (e.g. mt5.initialize())
          2. Authenticate with server/login/password
          3. Verify account type is DEMO
          4. Set self._state = ConnectionState.CONNECTED
        """
        logger.info("DemoBrokerAdapter.connect(): stub — not implemented")
        self._state = ConnectionState.DISCONNECTED
        raise NotImplementedError(
            f"connect() not implemented for {self._broker_name}. "
            "Wire the broker-specific API client here."
        )

    def disconnect(self) -> None:
        """Gracefully close the broker connection."""
        logger.info("DemoBrokerAdapter.disconnect(): stub")
        self._state = ConnectionState.DISCONNECTED

    def reconnect(self) -> bool:
        """Attempt to re-establish a dropped connection."""
        self.disconnect()
        return self.connect()

    def heartbeat(self) -> datetime | None:
        """Return the last known server heartbeat time, or None."""
        return self._last_heartbeat

    # ------------------------------------------------------------------
    # BrokerAdapter protocol
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> str:
        """Submit an order to the demo account.

        Real implementation contract:
          - Convert Order to broker-native request (symbol, lot, sl, tp)
          - Lot conversion: order.units / self._lot_size
          - Handle OrderSendResult: check retcode for success
          - Return broker-assigned ticket/order ID as string
          - On failure: raise with retcode and comment
        """
        self._assert_connected()
        raise NotImplementedError(
            "submit_order() not implemented. "
            "Map Order -> broker request format here."
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by broker order ID.

        Returns True if successfully cancelled.
        """
        self._assert_connected()
        raise NotImplementedError("cancel_order() not implemented.")

    def get_positions(self) -> list[Position]:
        """Query all open positions from the broker.

        Real implementation contract:
          - Fetch positions via broker API
          - Map each to domain Position object
          - Include entry_price, sl, tp, units, direction
          - Handle symbol name mapping (broker uses "USDJPY", etc.)
        """
        self._assert_connected()
        raise NotImplementedError("get_positions() not implemented.")

    def get_account(self) -> AccountState:
        """Query current account state from the broker.

        Should return equity, cash (balance), unrealized PnL, counts.
        """
        self._assert_connected()
        raise NotImplementedError("get_account() not implemented.")

    def process_bar(
        self,
        pair: TradingPair,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> list[Fill]:
        """Process a bar through the broker.

        For a real demo broker, this is a no-op since the broker
        manages SL/TP execution server-side.  Instead, poll for
        closed positions and map them to Fill objects.
        """
        self._assert_connected()
        # In real implementation: query for any positions closed since last check
        return []

    # ------------------------------------------------------------------
    # Reconciliation helpers
    # ------------------------------------------------------------------

    def get_broker_equity(self) -> float:
        """Direct equity query for reconciliation."""
        account = self.get_account()
        return account.equity

    def get_broker_position_count(self) -> int:
        """Direct position count for reconciliation."""
        return len(self.get_positions())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_connected(self) -> None:
        if self._state != ConnectionState.CONNECTED:
            raise ConnectionError(
                f"DemoBrokerAdapter not connected (state={self._state.value}). "
                "Call connect() first."
            )
