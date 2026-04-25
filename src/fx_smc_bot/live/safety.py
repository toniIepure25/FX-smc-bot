"""Safety controller: startup checks, watchdog, no-trade windows, hard limits.

Sits between the ForwardPaperRunner and the execution layer to enforce
operational safety constraints that are independent of the risk model.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from fx_smc_bot.config import AppConfig
from fx_smc_bot.data.market_calendar import is_high_impact_window, is_market_open
from fx_smc_bot.live.alerts import AlertEvent, AlertSink, LogAlertSink
from fx_smc_bot.live.state import LiveState, config_fingerprint

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NoTradeWindow:
    """Time window where order submission is blocked."""
    name: str
    start: time
    end: time
    days_of_week: tuple[int, ...] = (0, 1, 2, 3, 4)  # Mon-Fri


# Rollover window: daily FX rollover around 21:00-22:00 UTC
DEFAULT_NO_TRADE_WINDOWS: list[NoTradeWindow] = [
    NoTradeWindow("daily_rollover", time(21, 45), time(22, 15)),
]


@dataclass(slots=True)
class StartupCheckResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


class SafetyController:
    """Operational safety controller for forward paper and demo modes."""

    def __init__(
        self,
        config: AppConfig,
        alert_sink: AlertSink | None = None,
        no_trade_windows: list[NoTradeWindow] | None = None,
        max_positions_hard: int = 5,
        max_exposure_hard: float = 500_000.0,
        heartbeat_timeout_minutes: int = 180,
    ) -> None:
        self._cfg = config
        self._alert = alert_sink or LogAlertSink()
        self._no_trade_windows = no_trade_windows or DEFAULT_NO_TRADE_WINDOWS
        self._max_positions_hard = max_positions_hard
        self._max_exposure_hard = max_exposure_hard
        self._heartbeat_timeout = timedelta(minutes=heartbeat_timeout_minutes)
        self._last_bar_time: datetime | None = None
        self._auto_paused = False

    # ------------------------------------------------------------------
    # Startup checks
    # ------------------------------------------------------------------

    def run_startup_checks(
        self,
        state_path: Path | None = None,
        feed_connected: bool = True,
        account_equity: float = 0.0,
    ) -> StartupCheckResult:
        """Run all startup sanity checks before the session begins."""
        result = StartupCheckResult(passed=True)

        # Config fingerprint
        fp = config_fingerprint(self._cfg)
        result.checks["config_fingerprint"] = True
        result.messages.append(f"Config fingerprint: {fp}")

        # State consistency
        if state_path and state_path.exists():
            try:
                saved = LiveState.load(state_path)
                config_ok = saved.verify_config(self._cfg)
                result.checks["state_config_match"] = config_ok
                if not config_ok:
                    result.messages.append("WARNING: Config fingerprint mismatch vs saved state")
                    result.passed = False

                checksum_ok = self._verify_state_checksum(state_path)
                result.checks["state_integrity"] = checksum_ok
                if not checksum_ok:
                    result.messages.append("WARNING: State file integrity check failed")
                    result.passed = False
            except Exception as e:
                result.checks["state_load"] = False
                result.messages.append(f"State load failed: {e}")
                result.passed = False
        else:
            result.checks["state_file"] = True
            result.messages.append("No prior state — fresh start")

        # Feed availability
        result.checks["feed_connected"] = feed_connected
        if not feed_connected:
            result.messages.append("Feed not connected")
            result.passed = False

        # Account balance
        min_equity = self._cfg.backtest.initial_capital * 0.1
        equity_ok = account_equity >= min_equity or account_equity == 0.0
        result.checks["account_equity"] = equity_ok
        if not equity_ok:
            result.messages.append(f"Account equity {account_equity:.2f} below minimum {min_equity:.2f}")
            result.passed = False

        # Market open
        now = datetime.utcnow()
        market_ok = is_market_open(now)
        result.checks["market_open"] = True  # informational, not blocking
        result.messages.append(f"Market open: {market_ok}")

        return result

    # ------------------------------------------------------------------
    # Runtime checks
    # ------------------------------------------------------------------

    def is_order_allowed(self, timestamp: datetime) -> tuple[bool, str]:
        """Check whether order submission is allowed at this timestamp."""
        if self._auto_paused:
            return False, "auto_paused_by_watchdog"

        if not is_market_open(timestamp):
            return False, "market_closed"

        if is_high_impact_window(timestamp):
            return False, "high_impact_event_window"

        for ntw in self._no_trade_windows:
            if timestamp.weekday() not in ntw.days_of_week:
                continue
            t = timestamp.time()
            if ntw.start <= ntw.end:
                if ntw.start <= t <= ntw.end:
                    return False, f"no_trade_window: {ntw.name}"
            else:
                # Crosses midnight
                if t >= ntw.start or t <= ntw.end:
                    return False, f"no_trade_window: {ntw.name}"

        return True, "allowed"

    def check_hard_limits(
        self,
        open_positions: int,
        total_exposure_units: float,
    ) -> tuple[bool, str]:
        """Check position and exposure hard limits (separate from risk constraints)."""
        if open_positions >= self._max_positions_hard:
            return False, f"hard_position_limit: {open_positions} >= {self._max_positions_hard}"
        if total_exposure_units >= self._max_exposure_hard:
            return False, f"hard_exposure_limit: {total_exposure_units:.0f} >= {self._max_exposure_hard:.0f}"
        return True, "within_limits"

    # ------------------------------------------------------------------
    # Heartbeat watchdog
    # ------------------------------------------------------------------

    def on_bar_received(self, timestamp: datetime) -> None:
        """Record the latest bar arrival for watchdog monitoring."""
        self._last_bar_time = timestamp
        if self._auto_paused:
            self._auto_paused = False
            logger.info("Watchdog: bars resuming — auto-pause lifted")

    def check_watchdog(self, wall_clock: datetime) -> bool:
        """Return True if the feed watchdog is healthy. Auto-pauses on timeout."""
        if self._last_bar_time is None:
            return True
        if not is_market_open(wall_clock):
            return True

        age = wall_clock - self._last_bar_time
        if age > self._heartbeat_timeout:
            if not self._auto_paused:
                self._auto_paused = True
                self._alert.emit(AlertEvent(
                    level="CRITICAL",
                    message=f"Watchdog: no bar for {age} — auto-pausing",
                    timestamp=wall_clock,
                    category="safety",
                ))
            return False
        return True

    # ------------------------------------------------------------------
    # State integrity
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_state_checksum(path: Path) -> bool:
        """Basic integrity check: file is valid JSON and has required fields."""
        try:
            with open(path) as f:
                data = json.load(f)
            required = {"state_version", "run_id", "equity", "operational_state"}
            return required.issubset(data.keys())
        except Exception:
            return False
