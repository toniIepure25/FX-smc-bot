"""Alert model, severity levels, sink protocol, and concrete sinks.

Provides structured alerting for the forward paper runner and live
monitoring stack: log-based, file-based (JSONL audit), webhook-based
(Slack / Discord / Telegram), and an in-memory collector for tests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class AlertSeverity(IntEnum):
    """Ordered severity levels for alert routing and filtering."""
    INFO = 0
    WARNING = 1
    CRITICAL = 2
    EMERGENCY = 3


@dataclass(slots=True, frozen=True)
class AlertEvent:
    level: str
    message: str
    timestamp: datetime
    category: str = "general"
    data: dict | None = None

    @property
    def severity(self) -> AlertSeverity:
        return _LEVEL_MAP.get(self.level.upper(), AlertSeverity.INFO)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


_LEVEL_MAP: dict[str, AlertSeverity] = {
    "INFO": AlertSeverity.INFO,
    "WARNING": AlertSeverity.WARNING,
    "CRITICAL": AlertSeverity.CRITICAL,
    "EMERGENCY": AlertSeverity.EMERGENCY,
}


@runtime_checkable
class AlertSink(Protocol):
    def emit(self, alert: AlertEvent) -> None: ...


class LogAlertSink:
    """Default alert sink that logs to Python logging."""

    def emit(self, alert: AlertEvent) -> None:
        log_fn = getattr(logger, alert.level.lower(), logger.info)
        log_fn("[%s] %s: %s", alert.category, alert.level, alert.message)


class CollectingAlertSink:
    """Collects alerts in memory (useful for testing and review)."""

    def __init__(self) -> None:
        self._alerts: list[AlertEvent] = []

    def emit(self, alert: AlertEvent) -> None:
        self._alerts.append(alert)

    @property
    def alerts(self) -> list[AlertEvent]:
        return list(self._alerts)

    def clear(self) -> None:
        self._alerts.clear()


class FileAlertSink:
    """Appends alerts to a JSONL file for audit-quality persistence."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, alert: AlertEvent) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(alert.to_dict(), default=str) + "\n")


class WebhookAlertSink:
    """Posts alerts to a webhook URL (Slack / Discord / generic).

    Uses ``httpx`` if available; falls back to logging a warning.
    Only alerts at or above ``min_severity`` are dispatched.
    """

    def __init__(
        self,
        url: str,
        min_severity: AlertSeverity = AlertSeverity.WARNING,
    ) -> None:
        self._url = url
        self._min_severity = min_severity

    def emit(self, alert: AlertEvent) -> None:
        if alert.severity < self._min_severity:
            return
        payload = {
            "text": f"[{alert.level}] [{alert.category}] {alert.message}",
            "timestamp": alert.timestamp.isoformat(),
        }
        try:
            import httpx
            httpx.post(self._url, json=payload, timeout=5.0)
        except ImportError:
            logger.warning("httpx not installed — webhook alert not sent: %s", alert.message)
        except Exception:
            logger.exception("Failed to send webhook alert")


_RO_TZ = ZoneInfo("Europe/Bucharest")


def _now_ro() -> datetime:
    return datetime.now(_RO_TZ)


def _to_ro(dt: datetime) -> str:
    """Format a datetime as Romania local time string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_RO_TZ).strftime("%d.%m.%Y %H:%M (Bucharest)")


class TelegramAlertSink:
    """Professional Telegram alert sink for the FX SMC trading bot.

    All user-facing timestamps are shown in Romania time (Europe/Bucharest).
    Market data timestamps remain in their original UTC form.
    Uses HTML parse mode for reliable formatting.
    """

    _EMOJI = {
        AlertSeverity.INFO: "\u2139\ufe0f",
        AlertSeverity.WARNING: "\u26a0\ufe0f",
        AlertSeverity.CRITICAL: "\U0001f6a8",
        AlertSeverity.EMERGENCY: "\U0001f198",
    }

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        min_severity: AlertSeverity = AlertSeverity.WARNING,
    ) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._min_severity = min_severity

    def _send(self, text: str, silent: bool = True) -> None:
        payload = {
            "chat_id": self._chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        try:
            import httpx
            httpx.post(self._url, json=payload, timeout=10.0)
        except ImportError:
            logger.warning("httpx not installed — Telegram alert not sent")
        except Exception:
            logger.exception("Failed to send Telegram message")

    def emit(self, alert: AlertEvent) -> None:
        if alert.severity < self._min_severity:
            return
        emoji = self._EMOJI.get(alert.severity, "")
        data = alert.data or {}
        ro_time = _to_ro(alert.timestamp)

        if alert.category == "trade_entry":
            text = self._format_trade_entry(data, ro_time)
        elif alert.category == "trade_exit":
            text = self._format_trade_exit(data, ro_time)
        elif alert.category == "daily_summary":
            text = self._format_daily_summary(data, ro_time)
        elif alert.category == "risk_state":
            text = self._format_risk_alert(emoji, alert, ro_time)
        elif alert.category == "lifecycle":
            text = self._format_lifecycle(emoji, alert, ro_time)
        else:
            text = (
                f"{emoji} <b>{alert.level}</b> | <code>{alert.category}</code>\n"
                f"{_html_escape(alert.message)}\n"
                f"<i>{ro_time}</i>"
            )

        silent = alert.severity < AlertSeverity.CRITICAL
        self._send(text, silent=silent)

    def _format_trade_entry(self, d: dict, ro_time: str) -> str:
        direction = d.get("direction", "?").upper()
        arrow = "\U0001f7e2" if direction == "LONG" else "\U0001f534"
        return (
            f"{arrow} <b>NEW TRADE — {d.get('pair', 'USDJPY')}</b>\n"
            f"\n"
            f"Direction: <b>{direction}</b>\n"
            f"Entry: <code>{d.get('entry', 0):.3f}</code>\n"
            f"Stop Loss: <code>{d.get('sl', 0):.3f}</code>\n"
            f"Take Profit: <code>{d.get('tp', 0):.3f}</code>\n"
            f"Risk/Reward: <b>{d.get('rr', 0):.1f}R</b>\n"
            f"Units: <code>{d.get('units', 0):,.0f}</code>\n"
            f"\n"
            f"<i>{ro_time}</i>"
        )

    def _format_trade_exit(self, d: dict, ro_time: str) -> str:
        pnl = d.get("pnl", 0)
        won = pnl > 0
        icon = "\u2705" if won else "\u274c"
        result = "WIN" if won else "LOSS"
        return (
            f"{icon} <b>TRADE CLOSED — {d.get('pair', 'USDJPY')}</b>\n"
            f"\n"
            f"Result: <b>{result}</b>\n"
            f"Entry: <code>{d.get('entry', 0):.3f}</code>\n"
            f"Exit: <code>{d.get('exit', 0):.3f}</code>\n"
            f"PnL: <b>{'+'if pnl>0 else ''}${pnl:,.2f}</b>\n"
            f"Duration: {d.get('duration', '?')}\n"
            f"Reason: {d.get('reason', '?')}\n"
            f"\n"
            f"<i>{ro_time}</i>"
        )

    def _format_daily_summary(self, d: dict, ro_time: str) -> str:
        pnl = d.get("pnl", 0)
        icon = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
        return (
            f"{icon} <b>DAILY REPORT — {d.get('date', 'Today')}</b>\n"
            f"{'=' * 28}\n"
            f"\n"
            f"Equity: <b>${d.get('equity', 0):,.2f}</b>\n"
            f"Day PnL: <b>{'+'if pnl>=0 else ''}${pnl:,.2f}</b>\n"
            f"Trades today: {d.get('trades', 0)}\n"
            f"Open positions: {d.get('open_positions', 0)}\n"
            f"\n"
            f"Win rate: {d.get('win_rate', 0):.0%}\n"
            f"Max drawdown: {d.get('drawdown', 0):.2%}\n"
            f"Total trades: {d.get('total_trades', 0)}\n"
            f"Total PnL: <b>{'+'if d.get('total_pnl',0)>=0 else ''}${d.get('total_pnl', 0):,.2f}</b>\n"
            f"\n"
            f"Status: <code>{d.get('status', 'active')}</code>\n"
            f"Feed: <code>{d.get('feed_status', 'connected')}</code>\n"
            f"\n"
            f"<i>{ro_time}</i>"
        )

    def _format_risk_alert(self, emoji: str, alert: AlertEvent, ro_time: str) -> str:
        return (
            f"{emoji} <b>RISK ALERT</b>\n"
            f"\n"
            f"{_html_escape(alert.message)}\n"
            f"\n"
            f"<i>{ro_time}</i>"
        )

    def _format_lifecycle(self, emoji: str, alert: AlertEvent, ro_time: str) -> str:
        return (
            f"{emoji} <b>SYSTEM</b>\n"
            f"\n"
            f"{_html_escape(alert.message)}\n"
            f"\n"
            f"<i>{ro_time}</i>"
        )

    def send_report(self, text: str) -> None:
        self._send(text, silent=True)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class AlertRouter:
    """Fan-out alerts to multiple sinks with optional deduplication.

    Deduplication suppresses repeated alerts of the same ``category``
    within a configurable cooldown window.
    """

    def __init__(
        self,
        sinks: list[AlertSink] | None = None,
        dedup_cooldown_seconds: float = 300.0,
    ) -> None:
        self._sinks: list[AlertSink] = list(sinks or [])
        self._cooldown = timedelta(seconds=dedup_cooldown_seconds)
        self._last_emitted: dict[str, datetime] = {}

    def add_sink(self, sink: AlertSink) -> None:
        self._sinks.append(sink)

    _NO_DEDUP = frozenset({
        "trade_entry", "trade_exit", "daily_summary", "crash",
    })

    def emit(self, alert: AlertEvent) -> None:
        if alert.category not in self._NO_DEDUP:
            key = f"{alert.category}:{alert.level}"
            last = self._last_emitted.get(key)
            if last is not None and (alert.timestamp - last) < self._cooldown:
                return
            self._last_emitted[key] = alert.timestamp
        for sink in self._sinks:
            try:
                sink.emit(alert)
            except Exception:
                logger.exception("AlertSink failed: %s", type(sink).__name__)
