"""Live state persistence for paper trading restart/resume.

Serializes and deserializes the trading session state (positions, orders,
equity, operational state, drawdown tracker internals, and config fingerprint)
to a JSON file for graceful restart and session continuity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.config import AppConfig, OperationalState

logger = logging.getLogger(__name__)


def config_fingerprint(cfg: AppConfig) -> str:
    """Deterministic hash of the risk + execution config for drift detection."""
    payload = cfg.risk.model_dump_json(exclude_none=True) + cfg.execution.model_dump_json(exclude_none=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(slots=True)
class LiveState:
    """Serializable snapshot of the paper trading session."""
    state_version: int = 3
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

    # DrawdownTracker internals for full resume
    peak_equity: float = 0.0
    initial_equity: float = 0.0
    day_start_equity: float = 0.0
    week_start_equity: float = 0.0
    current_day: int = -1
    current_week: int = -1
    cb_fire_count: int = 0
    cb_cooldown_until: str | None = None
    circuit_breaker_fired: bool = False

    # Config fingerprint for drift detection on resume
    config_fingerprint: str = ""

    # Forward-paper session metadata
    mode: str = "historical"
    last_bar_timestamp: str | None = None

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
        # Forward-compat: ignore unknown fields from older versions
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

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

    @classmethod
    def from_forward_session(
        cls,
        run_id: str,
        equity: float,
        cash: float,
        bars_processed: int,
        operational_state: OperationalState,
        dd_tracker: Any,
        cfg: AppConfig,
        positions: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        trades_today: int = 0,
        last_bar_timestamp: datetime | None = None,
    ) -> LiveState:
        """Capture full session state including DrawdownTracker internals."""
        cb_until = None
        if hasattr(dd_tracker, "_cb_cooldown_until") and dd_tracker._cb_cooldown_until is not None:
            cb_until = dd_tracker._cb_cooldown_until.isoformat()

        return cls(
            state_version=3,
            run_id=run_id,
            timestamp=datetime.utcnow().isoformat(),
            operational_state=operational_state.value,
            equity=equity,
            cash=cash,
            bars_processed=bars_processed,
            open_positions=positions or [],
            pending_orders=orders or [],
            consecutive_losses=dd_tracker.consecutive_losses,
            trades_today=trades_today,
            peak_equity=dd_tracker.peak_equity,
            initial_equity=dd_tracker.initial_equity,
            day_start_equity=dd_tracker._day_start_equity,
            week_start_equity=dd_tracker._week_start_equity,
            current_day=dd_tracker._current_day,
            current_week=dd_tracker._current_week,
            cb_fire_count=dd_tracker._cb_fire_count,
            cb_cooldown_until=cb_until,
            circuit_breaker_fired=dd_tracker.circuit_breaker_fired,
            config_fingerprint=config_fingerprint(cfg),
            mode="forward_paper",
            last_bar_timestamp=last_bar_timestamp.isoformat() if last_bar_timestamp else None,
        )

    def verify_config(self, cfg: AppConfig) -> bool:
        """Return True if the saved config fingerprint matches the current config."""
        if not self.config_fingerprint:
            return True
        return self.config_fingerprint == config_fingerprint(cfg)

    def restore_drawdown_tracker(self, dd_tracker: Any) -> None:
        """Rehydrate a DrawdownTracker from saved state."""
        dd_tracker._peak_equity = self.peak_equity or self.equity
        dd_tracker._day_start_equity = self.day_start_equity or self.equity
        dd_tracker._week_start_equity = self.week_start_equity or self.equity
        dd_tracker._current_day = self.current_day
        dd_tracker._current_week = self.current_week
        dd_tracker._consecutive_losses = self.consecutive_losses
        dd_tracker._cb_fire_count = self.cb_fire_count
        dd_tracker._circuit_breaker_fired = self.circuit_breaker_fired
        if self.cb_cooldown_until:
            dd_tracker._cb_cooldown_until = datetime.fromisoformat(self.cb_cooldown_until)
        if self.operational_state in (s.value for s in OperationalState):
            dd_tracker._state = OperationalState(self.operational_state)
