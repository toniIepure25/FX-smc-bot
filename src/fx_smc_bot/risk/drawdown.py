"""Drawdown tracking, throttling, and operational risk state.

Maintains peak equity, daily/weekly drawdown, consecutive-loss dampening,
and an operational state machine (ACTIVE -> THROTTLED -> LOCKED -> STOPPED).
"""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import OperationalState, RiskConfig
from fx_smc_bot.domain import RiskSnapshot


class DrawdownTracker:
    """Stateful tracker for portfolio drawdown across a backtest or live session."""

    def __init__(self, initial_equity: float, risk_cfg: RiskConfig) -> None:
        self._risk_cfg = risk_cfg
        self._peak_equity = initial_equity
        self._day_start_equity = initial_equity
        self._week_start_equity = initial_equity
        self._current_day: int = -1
        self._current_week: int = -1
        self._consecutive_losses: int = 0
        self._state = OperationalState.ACTIVE

    @property
    def operational_state(self) -> OperationalState:
        return self._state

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def record_trade_result(self, pnl: float) -> None:
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def update(self, equity: float, timestamp: datetime) -> RiskSnapshot:
        """Update tracker with current equity and return a snapshot."""
        day_num = timestamp.toordinal()
        week_num = timestamp.isocalendar()[1]

        if day_num != self._current_day:
            self._day_start_equity = equity
            self._current_day = day_num
            if self._state == OperationalState.LOCKED:
                self._state = OperationalState.ACTIVE

        if week_num != self._current_week:
            self._week_start_equity = equity
            self._current_week = week_num

        if equity > self._peak_equity:
            self._peak_equity = equity

        daily_dd = 0.0
        if self._day_start_equity > 0:
            daily_dd = max(0.0, (self._day_start_equity - equity) / self._day_start_equity)

        weekly_dd = 0.0
        if self._week_start_equity > 0:
            weekly_dd = max(0.0, (self._week_start_equity - equity) / self._week_start_equity)

        self._update_state(daily_dd, weekly_dd)
        throttle = self._compute_throttle(daily_dd, weekly_dd)

        return RiskSnapshot(
            timestamp=timestamp,
            equity=equity,
            open_risk=0.0,
            daily_drawdown=daily_dd,
            weekly_drawdown=weekly_dd,
            peak_equity=self._peak_equity,
            throttle_factor=throttle,
            open_position_count=0,
        )

    def _update_state(self, daily_dd: float, weekly_dd: float) -> None:
        cfg = self._risk_cfg
        if self._state == OperationalState.STOPPED:
            return

        if daily_dd >= cfg.daily_loss_lockout:
            self._state = OperationalState.LOCKED
        elif daily_dd >= cfg.max_daily_drawdown * 0.75 or weekly_dd >= cfg.max_weekly_drawdown * 0.75:
            self._state = OperationalState.THROTTLED
        elif self._state not in (OperationalState.LOCKED, OperationalState.STOPPED):
            self._state = OperationalState.ACTIVE

    def _compute_throttle(self, daily_dd: float, weekly_dd: float) -> float:
        """Throttle factor: 1.0 = full speed, 0.0 = no new trades."""
        if self._state in (OperationalState.LOCKED, OperationalState.STOPPED):
            return 0.0

        cfg = self._risk_cfg
        daily_throttle = 1.0
        if cfg.max_daily_drawdown > 0:
            daily_ratio = daily_dd / cfg.max_daily_drawdown
            daily_throttle = max(0.0, 1.0 - daily_ratio)

        weekly_throttle = 1.0
        if cfg.max_weekly_drawdown > 0:
            weekly_ratio = weekly_dd / cfg.max_weekly_drawdown
            weekly_throttle = max(0.0, 1.0 - weekly_ratio)

        base_throttle = min(daily_throttle, weekly_throttle)

        # Consecutive-loss dampening
        if self._consecutive_losses >= cfg.consecutive_loss_dampen_after:
            base_throttle *= cfg.consecutive_loss_dampen_factor

        return max(0.0, base_throttle)
