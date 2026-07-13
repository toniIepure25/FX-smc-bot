"""Configurable prop-account challenge Monte Carlo simulation.

Estimates pass/fail probabilities for prop trading challenges using
dependence-preserving bootstrap of real trade sequences. Separated
from alpha discovery: alpha quality must be evaluated before
prop-rule optimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from pydantic import BaseModel, Field


class PropAccountProfile(BaseModel):
    """YAML-compatible profile for a prop trading challenge."""

    name: str = "Generic Challenge"
    starting_balance: float = Field(default=100_000.0, ge=1_000)
    phase1_profit_target: float = Field(default=0.08, ge=0.0)
    phase2_profit_target: float = Field(default=0.05, ge=0.0)
    daily_max_loss: float = Field(default=0.05, ge=0.0)
    total_max_loss: float = Field(default=0.10, ge=0.0)
    drawdown_type: Literal["balance", "equity"] = "balance"
    min_trading_days: int = Field(default=5, ge=0)
    max_trading_days: int = Field(default=0, ge=0)
    consistency_rule: bool = False
    best_day_max_pct: float = Field(default=0.0, ge=0.0)
    weekend_holding_allowed: bool = True
    news_restriction: bool = False
    leverage: float = Field(default=100.0, ge=1.0)
    commission_per_lot: float = Field(default=3.5, ge=0.0)
    spread_pips: float = Field(default=1.5, ge=0.0)
    payout_pct: float = Field(default=0.80, ge=0.0, le=1.0)


@dataclass(frozen=True, slots=True)
class SimulationOutcome:
    """Result of a single Monte Carlo path."""

    passed_phase1: bool
    passed_phase2: bool
    reached_payout: bool
    daily_loss_breach: bool
    total_loss_breach: bool
    trading_days: int
    final_pnl_pct: float
    max_drawdown_pct: float
    failure_mode: str


@dataclass(slots=True)
class PropSimulationResult:
    """Aggregated Monte Carlo simulation results."""

    profile_name: str = ""
    n_paths: int = 0
    risk_per_trade: float = 0.0
    phase1_pass_rate: float = 0.0
    phase2_pass_rate: float = 0.0
    payout_rate: float = 0.0
    daily_breach_rate: float = 0.0
    total_breach_rate: float = 0.0
    median_trading_days: float = 0.0
    mean_max_drawdown: float = 0.0
    p10_max_drawdown: float = 0.0
    p90_max_drawdown: float = 0.0
    most_common_failure: str = ""
    median_final_pnl_pct: float = 0.0
    p10_final_pnl_pct: float = 0.0
    p90_final_pnl_pct: float = 0.0
    outcomes: list[SimulationOutcome] = field(default_factory=list)


def simulate_prop_challenge(
    daily_pnl_pcts: NDArray[np.float64],
    profile: PropAccountProfile,
    n_paths: int = 10_000,
    risk_per_trade: float = 0.005,
    block_size: int = 5,
    seed: int = 42,
) -> PropSimulationResult:
    """Run Monte Carlo prop challenge simulation.

    Parameters
    ----------
    daily_pnl_pcts : array of daily PnL as fraction of equity
    profile : prop account rules
    n_paths : number of bootstrap paths
    risk_per_trade : used for labeling only (actual risk is in daily_pnl_pcts)
    block_size : bootstrap block size (preserves short-term dependence)
    """
    rng = np.random.default_rng(seed)
    n = len(daily_pnl_pcts)

    if n < block_size:
        return PropSimulationResult(
            profile_name=profile.name, n_paths=0,
            risk_per_trade=risk_per_trade,
        )

    outcomes: list[SimulationOutcome] = []

    for _ in range(n_paths):
        path = _bootstrap_path(daily_pnl_pcts, n, block_size, rng)
        outcome = _simulate_one_path(path, profile)
        outcomes.append(outcome)

    return _aggregate_outcomes(outcomes, profile, risk_per_trade)


def _bootstrap_path(
    data: NDArray[np.float64],
    target_length: int,
    block_size: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Generate one bootstrap path using block resampling."""
    n = len(data)
    n_blocks = (target_length + block_size - 1) // block_size
    max_start = n - block_size

    if max_start <= 0:
        return data.copy()

    starts = rng.integers(0, max_start + 1, size=n_blocks)
    path = np.concatenate([data[s:s + block_size] for s in starts])
    return path[:target_length]


def _simulate_one_path(
    daily_pnls: NDArray[np.float64],
    profile: PropAccountProfile,
) -> SimulationOutcome:
    """Simulate one prop challenge path through Phase 1 and Phase 2."""
    balance = profile.starting_balance
    peak = balance
    day_start_balance = balance
    daily_breach = False
    total_breach = False
    failure_mode = ""

    phase1_target = profile.starting_balance * (1 + profile.phase1_profit_target)
    total_limit = profile.total_max_loss * profile.starting_balance

    passed_p1 = False
    passed_p2 = False
    p1_balance = 0.0
    trading_days = 0
    max_dd_pct = 0.0
    best_day_pnl = 0.0

    for i, pnl_pct in enumerate(daily_pnls):
        pnl = day_start_balance * pnl_pct
        trading_days += 1

        if abs(pnl) > 0:
            if pnl > best_day_pnl:
                best_day_pnl = pnl

        daily_limit = profile.daily_max_loss * day_start_balance
        if pnl < -daily_limit:
            daily_breach = True
            failure_mode = "daily_loss_breach"
            break

        balance += pnl
        day_start_balance = balance
        if balance > peak:
            peak = balance

        dd = peak - balance
        dd_pct = dd / peak if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        if dd > total_limit:
            total_breach = True
            failure_mode = "total_loss_breach"
            break

        if profile.max_trading_days > 0 and trading_days >= profile.max_trading_days:
            if not passed_p1:
                failure_mode = "max_days_exceeded"
                break

        if not passed_p1 and balance >= phase1_target:
            passed_p1 = True
            p1_balance = balance
            if trading_days < profile.min_trading_days:
                continue

        if passed_p1 and not passed_p2:
            phase2_target = p1_balance * (1 + profile.phase2_profit_target)
            if balance >= phase2_target:
                if trading_days >= profile.min_trading_days:
                    passed_p2 = True

    if profile.consistency_rule and profile.best_day_max_pct > 0:
        total_profit = balance - profile.starting_balance
        if total_profit > 0 and best_day_pnl / total_profit > profile.best_day_max_pct:
            passed_p2 = False
            failure_mode = "consistency_rule"

    if not failure_mode and not passed_p1:
        failure_mode = "target_not_reached"

    final_pnl_pct = (balance - profile.starting_balance) / profile.starting_balance
    reached_payout = passed_p1 and passed_p2

    return SimulationOutcome(
        passed_phase1=passed_p1,
        passed_phase2=passed_p2,
        reached_payout=reached_payout,
        daily_loss_breach=daily_breach,
        total_loss_breach=total_breach,
        trading_days=trading_days,
        final_pnl_pct=final_pnl_pct,
        max_drawdown_pct=max_dd_pct,
        failure_mode=failure_mode,
    )


def _aggregate_outcomes(
    outcomes: list[SimulationOutcome],
    profile: PropAccountProfile,
    risk_per_trade: float,
) -> PropSimulationResult:
    """Aggregate individual path outcomes into summary statistics."""
    n = len(outcomes)
    if n == 0:
        return PropSimulationResult(profile_name=profile.name)

    p1_pass = sum(1 for o in outcomes if o.passed_phase1) / n
    p2_pass = sum(1 for o in outcomes if o.passed_phase2) / n
    payout = sum(1 for o in outcomes if o.reached_payout) / n
    daily_br = sum(1 for o in outcomes if o.daily_loss_breach) / n
    total_br = sum(1 for o in outcomes if o.total_loss_breach) / n

    trading_days = np.array([o.trading_days for o in outcomes])
    max_dds = np.array([o.max_drawdown_pct for o in outcomes])
    final_pnls = np.array([o.final_pnl_pct for o in outcomes])

    failure_modes: dict[str, int] = {}
    for o in outcomes:
        if o.failure_mode:
            failure_modes[o.failure_mode] = failure_modes.get(o.failure_mode, 0) + 1
    most_common = max(failure_modes, key=lambda k: failure_modes[k]) if failure_modes else ""

    return PropSimulationResult(
        profile_name=profile.name,
        n_paths=n,
        risk_per_trade=risk_per_trade,
        phase1_pass_rate=p1_pass,
        phase2_pass_rate=p2_pass,
        payout_rate=payout,
        daily_breach_rate=daily_br,
        total_breach_rate=total_br,
        median_trading_days=float(np.median(trading_days)),
        mean_max_drawdown=float(np.mean(max_dds)),
        p10_max_drawdown=float(np.percentile(max_dds, 10)),
        p90_max_drawdown=float(np.percentile(max_dds, 90)),
        most_common_failure=most_common,
        median_final_pnl_pct=float(np.median(final_pnls)),
        p10_final_pnl_pct=float(np.percentile(final_pnls, 10)),
        p90_final_pnl_pct=float(np.percentile(final_pnls, 90)),
        outcomes=outcomes,
    )
