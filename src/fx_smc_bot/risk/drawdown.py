"""Drawdown tracking, throttling, and operational risk state.

Maintains peak equity, daily/weekly drawdown, consecutive-loss dampening,
peak-to-trough circuit breaker, and an operational state machine
(ACTIVE -> THROTTLED -> LOCKED -> STOPPED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fx_smc_bot.config import OperationalState, RiskConfig
from fx_smc_bot.domain import RiskSnapshot


@dataclass(slots=True, frozen=True)
class StateTransition:
    """Record of a state machine transition for audit trail."""
    timestamp: datetime
    from_state: OperationalState
    to_state: OperationalState
    reason: str
    equity: float = 0.0
    peak_equity: float = 0.0


class DrawdownTracker:
    """Stateful tracker for portfolio drawdown across a backtest or live session."""

    def __init__(self, initial_equity: float, risk_cfg: RiskConfig) -> None:
        self._risk_cfg = risk_cfg
        self._initial_equity = initial_equity
        self._peak_equity = initial_equity
        self._day_start_equity = initial_equity
        self._week_start_equity = initial_equity
        self._current_day: int = -1
        self._current_week: int = -1
        self._consecutive_losses: int = 0
        self._state = OperationalState.ACTIVE
        self._state_transitions: list[StateTransition] = []
        self._throttle_activation_count: int = 0
        self._lockout_activation_count: int = 0
        self._circuit_breaker_fired: bool = False
        self._cb_cooldown_until: datetime | None = None
        self._cb_fire_count: int = 0

    @property
    def initial_equity(self) -> float:
        return self._initial_equity

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def operational_state(self) -> OperationalState:
        return self._state

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def state_history(self) -> list[StateTransition]:
        return list(self._state_transitions)

    @property
    def circuit_breaker_fired(self) -> bool:
        return self._circuit_breaker_fired

    @property
    def risk_event_counts(self) -> dict[str, int]:
        return {
            "throttle_activations": self._throttle_activation_count,
            "lockout_activations": self._lockout_activation_count,
            "circuit_breaker_fired": int(self._circuit_breaker_fired),
            "circuit_breaker_fire_count": self._cb_fire_count,
            "state_transitions": len(self._state_transitions),
        }

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
                self._transition(
                    OperationalState.ACTIVE, "new_day_reset",
                    timestamp, equity,
                )

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

        peak_dd = 0.0
        if self._peak_equity > 0:
            peak_dd = max(0.0, (self._peak_equity - equity) / self._peak_equity)

        self._update_state(daily_dd, weekly_dd, peak_dd, timestamp, equity)
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

    def _transition(
        self, new_state: OperationalState, reason: str,
        timestamp: datetime, equity: float,
    ) -> None:
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        self._state_transitions.append(StateTransition(
            timestamp=timestamp,
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            equity=equity,
            peak_equity=self._peak_equity,
        ))
        if new_state == OperationalState.THROTTLED:
            self._throttle_activation_count += 1
        elif new_state == OperationalState.LOCKED:
            self._lockout_activation_count += 1

    def _update_state(
        self, daily_dd: float, weekly_dd: float, peak_dd: float,
        timestamp: datetime, equity: float,
    ) -> None:
        cfg = self._risk_cfg

        # Cooldown-based CB recovery: reset HWM to current equity to avoid
        # immediate re-trigger from the same drawdown.
        if (self._state == OperationalState.STOPPED
                and cfg.circuit_breaker_cooldown_days > 0
                and self._cb_cooldown_until is not None
                and timestamp >= self._cb_cooldown_until):
            self._peak_equity = equity
            self._transition(
                OperationalState.ACTIVE,
                f"cb_cooldown_expired: resumed after {cfg.circuit_breaker_cooldown_days}d, hwm_reset={equity:.0f}",
                timestamp, equity,
            )
            self._cb_cooldown_until = None

        if self._state == OperationalState.STOPPED:
            return

        # Circuit breaker: peak-to-trough drawdown threshold
        if cfg.circuit_breaker_threshold > 0 and peak_dd >= cfg.circuit_breaker_threshold:
            self._circuit_breaker_fired = True
            self._cb_fire_count += 1
            if cfg.circuit_breaker_cooldown_days > 0:
                from datetime import timedelta
                self._cb_cooldown_until = timestamp + timedelta(days=cfg.circuit_breaker_cooldown_days)
            self._transition(
                OperationalState.STOPPED,
                f"circuit_breaker: peak_dd {peak_dd:.2%} >= {cfg.circuit_breaker_threshold:.2%}",
                timestamp, equity,
            )
            return

        if daily_dd >= cfg.daily_loss_lockout:
            self._transition(
                OperationalState.LOCKED,
                f"daily_lockout: {daily_dd:.2%} >= {cfg.daily_loss_lockout:.2%}",
                timestamp, equity,
            )
        elif daily_dd >= cfg.max_daily_drawdown * 0.75 or weekly_dd >= cfg.max_weekly_drawdown * 0.75:
            self._transition(
                OperationalState.THROTTLED,
                f"throttle: daily={daily_dd:.2%} weekly={weekly_dd:.2%}",
                timestamp, equity,
            )
        elif self._state not in (OperationalState.LOCKED, OperationalState.STOPPED):
            self._transition(
                OperationalState.ACTIVE, "conditions_normal",
                timestamp, equity,
            )

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

        if self._consecutive_losses >= cfg.consecutive_loss_dampen_after:
            base_throttle *= cfg.consecutive_loss_dampen_factor

        return max(0.0, base_throttle)
