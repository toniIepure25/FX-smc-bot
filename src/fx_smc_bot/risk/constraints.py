"""Risk constraints: per-trade, per-pair, portfolio-level, and operational caps.

Each constraint implements the ConstraintChecker protocol and returns
(passed: bool, reason: str | None).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from fx_smc_bot.config import PAIR_CURRENCIES, RiskConfig
from fx_smc_bot.domain import Direction, Position, PositionIntent, TradeCandidate
from fx_smc_bot.risk.exposure import compute_currency_exposures


@runtime_checkable
class ConstraintChecker(Protocol):
    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        """Return (True, None) if constraint passes, else (False, reason)."""
        ...


class MaxTradeRiskConstraint:
    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        if intent.risk_fraction > risk_cfg.base_risk_per_trade * 1.5:
            return False, f"Trade risk {intent.risk_fraction:.4f} exceeds 1.5x base"
        return True, None


class MaxConcurrentPositionsConstraint:
    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        open_count = sum(1 for p in open_positions if p.is_open)
        if open_count >= risk_cfg.max_concurrent_positions:
            return False, f"Already {open_count} open positions (max {risk_cfg.max_concurrent_positions})"
        return True, None


class MaxPairPositionsConstraint:
    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        pair = intent.candidate.pair
        pair_count = sum(1 for p in open_positions if p.is_open and p.pair == pair)
        if pair_count >= risk_cfg.max_per_pair_positions:
            return False, f"Already {pair_count} positions for {pair.value}"
        return True, None


class MaxPortfolioRiskConstraint:
    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        total_risk = intent.risk_fraction
        for p in open_positions:
            if p.is_open and equity > 0:
                pos_risk = abs(p.entry_price - p.stop_loss) * p.units / equity
                total_risk += pos_risk
        if total_risk > risk_cfg.max_portfolio_risk:
            return False, f"Portfolio risk {total_risk:.4f} exceeds max {risk_cfg.max_portfolio_risk}"
        return True, None


class CurrencyExposureConstraint:
    """Rejects trades that would exceed per-currency net exposure limits."""

    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        exposures = compute_currency_exposures(
            [p for p in open_positions if p.is_open]
        )
        pair = intent.candidate.pair
        base, quote = PAIR_CURRENCIES[pair]
        sign = 1.0 if intent.candidate.direction == Direction.LONG else -1.0
        units = intent.units

        new_base = abs(exposures.get(base, 0.0) + sign * units)
        new_quote = abs(exposures.get(quote, 0.0) - sign * units)
        limit = risk_cfg.max_currency_exposure * 100_000

        if new_base > limit:
            return False, f"{base} exposure {new_base:.0f} would exceed limit {limit:.0f}"
        if new_quote > limit:
            return False, f"{quote} exposure {new_quote:.0f} would exceed limit {limit:.0f}"
        return True, None


class DirectionalConcentrationConstraint:
    """Limits the fraction of open positions in one direction."""

    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        open_pos = [p for p in open_positions if p.is_open]
        if not open_pos:
            return True, None
        direction = intent.candidate.direction
        same_dir = sum(1 for p in open_pos if p.direction == direction)
        total = len(open_pos) + 1
        ratio = (same_dir + 1) / total
        if ratio > risk_cfg.max_directional_concentration:
            return False, f"Directional concentration {ratio:.0%} exceeds {risk_cfg.max_directional_concentration:.0%}"
        return True, None


class MaxDailyTradesConstraint:
    """Caps trades opened per calendar day (stateful counter)."""

    def __init__(self) -> None:
        self._current_day: int = -1
        self._day_count: int = 0

    def record_trade(self, timestamp: datetime) -> None:
        day = timestamp.toordinal()
        if day != self._current_day:
            self._current_day = day
            self._day_count = 0
        self._day_count += 1

    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        if self._day_count >= risk_cfg.max_trades_per_day:
            return False, f"Daily trade limit reached ({risk_cfg.max_trades_per_day})"
        return True, None


class DailyStopConstraint:
    """Enforces a daily loss lockout: no new trades after daily_loss_lockout pct."""

    def __init__(self) -> None:
        self._locked = False
        self._current_day: int = -1

    def update(self, daily_drawdown: float, timestamp: datetime, limit: float) -> bool:
        day = timestamp.toordinal()
        if day != self._current_day:
            self._current_day = day
            self._locked = False
        if daily_drawdown >= limit:
            self._locked = True
        return self._locked

    @property
    def is_locked(self) -> bool:
        return self._locked

    def check(
        self,
        intent: PositionIntent,
        open_positions: list[Position],
        risk_cfg: RiskConfig,
        equity: float,
    ) -> tuple[bool, str | None]:
        if self._locked:
            return False, "Daily stop triggered -- trading locked for today"
        return True, None


DEFAULT_CONSTRAINTS: list[ConstraintChecker] = [
    MaxTradeRiskConstraint(),
    MaxConcurrentPositionsConstraint(),
    MaxPairPositionsConstraint(),
    MaxPortfolioRiskConstraint(),
]


def build_full_constraints() -> list[ConstraintChecker]:
    """Build the full professional constraint stack."""
    return [
        MaxTradeRiskConstraint(),
        MaxConcurrentPositionsConstraint(),
        MaxPairPositionsConstraint(),
        MaxPortfolioRiskConstraint(),
        CurrencyExposureConstraint(),
        DirectionalConcentrationConstraint(),
        DailyStopConstraint(),
        MaxDailyTradesConstraint(),
    ]


def check_all_constraints(
    intent: PositionIntent,
    open_positions: list[Position],
    risk_cfg: RiskConfig,
    equity: float,
    constraints: list[ConstraintChecker] | None = None,
) -> tuple[bool, list[str]]:
    """Run all constraints and return (all_passed, list_of_failure_reasons)."""
    constraints = constraints or DEFAULT_CONSTRAINTS
    reasons: list[str] = []
    for c in constraints:
        passed, reason = c.check(intent, open_positions, risk_cfg, equity)
        if not passed and reason:
            reasons.append(reason)
    return len(reasons) == 0, reasons
