"""Alert model and sink protocol for operational notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class AlertEvent:
    level: str
    message: str
    timestamp: datetime
    category: str = "general"
    data: dict | None = None


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
