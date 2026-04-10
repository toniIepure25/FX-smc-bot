"""Live state persistence for paper trading restart/resume.

Serializes and deserializes the trading session state (positions, orders,
equity, operational state) to a JSON file for graceful restart.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.config import OperationalState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveState:
    """Serializable snapshot of the paper trading session."""
    state_version: int = 2
    run_id: str = ""
    timestamp: str = ""
    operational_state: str = OperationalState.ACTIVE.value
    equity: float = 0.0
    cash: float = 0.0
    bars_processed: int = 0
    trades_today: int = 0
    consecutive_losses: int = 0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    pending_orders: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)
        logger.debug("State saved to %s", path)

    @classmethod
    def load(cls, path: Path | str) -> LiveState:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"State file not found: {path}")
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_broker(
        cls,
        run_id: str,
        equity: float,
        cash: float,
        bars_processed: int,
        operational_state: OperationalState,
        positions: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        consecutive_losses: int = 0,
        trades_today: int = 0,
    ) -> LiveState:
        return cls(
            run_id=run_id,
            timestamp=datetime.utcnow().isoformat(),
            operational_state=operational_state.value,
            equity=equity,
            cash=cash,
            bars_processed=bars_processed,
            open_positions=positions or [],
            pending_orders=orders or [],
            consecutive_losses=consecutive_losses,
            trades_today=trades_today,
        )
