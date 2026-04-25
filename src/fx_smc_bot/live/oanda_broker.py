"""OANDA v20 REST API broker adapter for demo and live trading.

Implements the BrokerAdapter protocol against OANDA's REST API.
Supports practice (demo) and live accounts. The strategy logic and
risk management remain unchanged — only the execution layer differs.

Requires:
  - OANDA_API_KEY environment variable
  - OANDA_ACCOUNT_ID environment variable
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import (
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    PositionState,
)
from fx_smc_bot.live.broker import AccountState

logger = logging.getLogger(__name__)

_PAIR_TO_OANDA: dict[TradingPair, str] = {
    TradingPair.EURUSD: "EUR_USD",
    TradingPair.GBPUSD: "GBP_USD",
    TradingPair.USDJPY: "USD_JPY",
    TradingPair.GBPJPY: "GBP_JPY",
}

_OANDA_TO_PAIR: dict[str, TradingPair] = {v: k for k, v in _PAIR_TO_OANDA.items()}


class OandaBrokerAdapter:
    """Real broker adapter for OANDA practice and live accounts.

    This adapter translates between the internal Order/Position/Fill
    domain and the OANDA v20 REST API. SL/TP are managed server-side
    by OANDA, which means the broker handles exit execution.
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        practice: bool = True,
    ) -> None:
        base = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
        self._base_url = base
        self._account_id = account_id
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._account_url = f"{base}/v3/accounts/{account_id}"
        self._known_trade_ids: set[str] = set()
        self._closed_since_last: list[Fill] = []
        self._practice = practice

    def connect(self) -> bool:
        """Verify connectivity by fetching account summary."""
        try:
            resp = httpx.get(
                f"{self._account_url}/summary",
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            acct = resp.json().get("account", {})
            balance = float(acct.get("balance", 0))
            logger.info(
                "OANDA connected: account=%s balance=%.2f currency=%s",
                self._account_id, balance, acct.get("currency", "?"),
            )
            return True
        except Exception:
            logger.exception("OANDA connection failed")
            return False

    def submit_order(self, order: Order) -> str:
        """Submit a market or limit order to OANDA.

        Converts internal Order to OANDA order spec with SL/TP.
        OANDA uses positive units for long, negative for short.
        """
        instrument = _PAIR_TO_OANDA.get(order.pair)
        if not instrument:
            raise ValueError(f"Unsupported pair: {order.pair}")

        units = order.units if order.direction == Direction.LONG else -order.units
        units_str = str(int(round(units)))

        order_body: dict[str, Any] = {
            "type": "MARKET",
            "instrument": instrument,
            "units": units_str,
            "timeInForce": "FOK",
        }

        if order.stop_loss > 0:
            order_body["stopLossOnFill"] = {"price": f"{order.stop_loss:.5f}"}
        if order.take_profit > 0:
            order_body["takeProfitOnFill"] = {"price": f"{order.take_profit:.5f}"}

        if order.order_type == OrderType.LIMIT:
            order_body["type"] = "LIMIT"
            order_body["price"] = f"{order.requested_price:.5f}"
            order_body["timeInForce"] = "GTC"

        payload = {"order": order_body}

        try:
            resp = httpx.post(
                f"{self._account_url}/orders",
                headers=self._headers,
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            result = resp.json()

            if "orderFillTransaction" in result:
                fill_tx = result["orderFillTransaction"]
                trade_ids = [t["tradeID"] for t in fill_tx.get("tradeOpened", {}).get("tradeIDs", [])]
                if not trade_ids:
                    trade_id = fill_tx.get("id", uuid.uuid4().hex[:12])
                else:
                    trade_id = trade_ids[0]
                self._known_trade_ids.add(str(trade_id))
                logger.info("OANDA order filled: trade_id=%s instrument=%s units=%s",
                            trade_id, instrument, units_str)
                return str(trade_id)

            if "orderCreateTransaction" in result:
                oid = result["orderCreateTransaction"].get("id", "")
                logger.info("OANDA order created (pending): id=%s", oid)
                return str(oid)

            logger.warning("OANDA order response unexpected: %s", result)
            return str(result.get("relatedTransactionIDs", ["unknown"])[0])

        except httpx.HTTPStatusError as e:
            error_body = e.response.json() if e.response else {}
            logger.error("OANDA order rejected: %s %s", e.response.status_code, error_body)
            raise
        except Exception:
            logger.exception("OANDA submit_order failed")
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        try:
            resp = httpx.put(
                f"{self._account_url}/orders/{order_id}/cancel",
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.info("OANDA order cancelled: %s", order_id)
            return True
        except Exception:
            logger.exception("OANDA cancel_order failed: %s", order_id)
            return False

    def close_trade(self, trade_id: str) -> bool:
        """Close an open trade (used for manual close / kill switch)."""
        try:
            resp = httpx.put(
                f"{self._account_url}/trades/{trade_id}/close",
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            self._known_trade_ids.discard(trade_id)
            logger.info("OANDA trade closed: %s", trade_id)
            return True
        except Exception:
            logger.exception("OANDA close_trade failed: %s", trade_id)
            return False

    def get_positions(self) -> list[Position]:
        """Query all open trades from OANDA and map to Position objects."""
        try:
            resp = httpx.get(
                f"{self._account_url}/openTrades",
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            trades = resp.json().get("trades", [])
        except Exception:
            logger.exception("OANDA get_positions failed")
            return []

        positions: list[Position] = []
        for t in trades:
            instrument = t.get("instrument", "")
            pair = _OANDA_TO_PAIR.get(instrument)
            if pair is None:
                continue

            units = float(t.get("currentUnits", 0))
            direction = Direction.LONG if units > 0 else Direction.SHORT

            pos = Position(
                id=str(t.get("id", "")),
                pair=pair,
                direction=direction,
                state=PositionState.OPEN,
                entry_price=float(t.get("price", 0)),
                stop_loss=float(t.get("stopLossOrder", {}).get("price", 0)) if t.get("stopLossOrder") else 0.0,
                take_profit=float(t.get("takeProfitOrder", {}).get("price", 0)) if t.get("takeProfitOrder") else 0.0,
                units=abs(units),
                opened_at=_parse_oanda_time(t.get("openTime")),
                pnl=float(t.get("unrealizedPL", 0)),
            )
            positions.append(pos)
            self._known_trade_ids.add(str(t.get("id", "")))

        return positions

    def get_account(self) -> AccountState:
        """Query account summary from OANDA."""
        try:
            resp = httpx.get(
                f"{self._account_url}/summary",
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            acct = resp.json().get("account", {})
        except Exception:
            logger.exception("OANDA get_account failed")
            return AccountState(
                equity=0, cash=0, unrealized_pnl=0,
                open_position_count=0, pending_order_count=0,
            )

        return AccountState(
            equity=float(acct.get("NAV", 0)),
            cash=float(acct.get("balance", 0)),
            unrealized_pnl=float(acct.get("unrealizedPL", 0)),
            open_position_count=int(acct.get("openTradeCount", 0)),
            pending_order_count=int(acct.get("pendingOrderCount", 0)),
            timestamp=datetime.utcnow(),
        )

    def process_bar(
        self,
        pair: TradingPair,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: datetime,
    ) -> list[Fill]:
        """Check for trades closed by OANDA since last check.

        OANDA manages SL/TP execution server-side. This method polls
        for recently closed trades and converts them to Fill objects.
        """
        fills: list[Fill] = []

        try:
            resp = httpx.get(
                f"{self._account_url}/transactions",
                headers=self._headers,
                params={"type": "ORDER_FILL", "count": 20},
                timeout=10.0,
            )
            resp.raise_for_status()

            for tx in resp.json().get("transactions", []):
                trade_id = tx.get("tradesClosed", [{}])[0].get("tradeID", "") if tx.get("tradesClosed") else ""
                if not trade_id or trade_id not in self._known_trade_ids:
                    continue

                reason_str = tx.get("reason", "").upper()
                if "STOP_LOSS" in reason_str:
                    reason = FillReason.STOP_LOSS_HIT
                elif "TAKE_PROFIT" in reason_str:
                    reason = FillReason.TAKE_PROFIT_HIT
                else:
                    reason = FillReason.MANUAL_CLOSE

                fills.append(Fill(
                    order_id=trade_id,
                    fill_price=float(tx.get("price", close)),
                    units=abs(float(tx.get("units", 0))),
                    spread_cost=float(tx.get("halfSpreadCost", 0)) * 2,
                    slippage=0.0,
                    timestamp=_parse_oanda_time(tx.get("time")) or timestamp,
                    reason=reason,
                ))
                self._known_trade_ids.discard(trade_id)

        except Exception:
            logger.debug("OANDA process_bar transaction check skipped", exc_info=True)

        return fills

    def close_all(self) -> int:
        """Emergency: close all open trades. Returns count closed."""
        positions = self.get_positions()
        closed = 0
        for pos in positions:
            if self.close_trade(pos.id):
                closed += 1
        return closed


def _parse_oanda_time(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
