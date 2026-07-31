"""Deterministic portfolio construction and accounting for Gate F.0.

All notionals and costs are expressed in portfolio-NAV units unless a caller
supplies monetary NAV values. Risk inputs are strictly lagged: the observation
at the decision timestamp is never included in an estimate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import SupportsFloat, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.covariance import LedoitWolf  # type: ignore[import-untyped]

INSTRUMENTS = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
CURRENCIES = ("USD", "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF")
RATE_DAY_COUNT_DENOMINATORS: Mapping[str, int] = MappingProxyType(
    {
        "USD": 360,
        "EUR": 360,
        "CHF": 360,
        "GBP": 365,
        "JPY": 365,
        "AUD": 365,
        "NZD": 365,
        "CAD": 365,
    }
)
NO_POSITION_CHANGE = "NO_POSITION_CHANGE_WITH_RECORDED_REASON"
NEW_YORK = ZoneInfo("America/New_York")


class PortfolioInputError(ValueError):
    """Raised when a caller supplies an invalid, rather than missing, input."""


class AccountingReconciliationError(RuntimeError):
    """Raised on any non-zero accounting or position residual."""


@dataclass(frozen=True, slots=True)
class PortfolioUniverse:
    """Ordered F0 instrument subset and its exact currency legs."""

    instruments: tuple[str, ...] = INSTRUMENTS
    currencies: tuple[str, ...] = CURRENCIES

    def __post_init__(self) -> None:
        if not self.instruments or not self.currencies:
            raise PortfolioInputError("Portfolio universe must not be empty")
        if len(self.instruments) != len(set(self.instruments)):
            raise PortfolioInputError("Portfolio instrument universe contains duplicates")
        if len(self.currencies) != len(set(self.currencies)):
            raise PortfolioInputError("Portfolio currency universe contains duplicates")
        if not set(self.instruments).issubset(INSTRUMENTS):
            raise PortfolioInputError("Instrument is outside the frozen universe")
        if not set(self.currencies).issubset(CURRENCIES):
            raise PortfolioInputError("Currency is outside the frozen universe")
        required_currencies = {
            currency
            for instrument in self.instruments
            for currency in (instrument[:3], instrument[3:])
        }
        if set(self.currencies) != required_currencies:
            raise PortfolioInputError(
                "Portfolio currencies must exactly match the selected instrument legs"
            )


LEGACY_PORTFOLIO_UNIVERSE = PortfolioUniverse()


def _resolve_universe(universe: PortfolioUniverse | None) -> PortfolioUniverse:
    return universe or LEGACY_PORTFOLIO_UNIVERSE


class CostScenario(str, Enum):
    """Frozen Gate F.0 executable-cost scenarios."""

    BASE = "base"
    STRESS_1 = "stress_1"
    STRESS_2 = "stress_2"


@dataclass(frozen=True, slots=True)
class ScenarioParameters:
    spread_multiplier: float
    slippage_multiplier: float
    financing_markup_annualized: float


SCENARIO_PARAMETERS: Mapping[CostScenario, ScenarioParameters] = MappingProxyType(
    {
        CostScenario.BASE: ScenarioParameters(1.0, 1.0, 0.005),
        CostScenario.STRESS_1: ScenarioParameters(1.5, 1.5, 0.010),
        CostScenario.STRESS_2: ScenarioParameters(2.0, 2.0, 0.015),
    }
)


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    ewma_lookback: int = 60
    ewma_decay: float = 0.94
    instrument_volatility_target: float = 0.10
    covariance_lookback: int = 252
    portfolio_volatility_target: float = 0.10
    annualization_days: int = 252
    maximum_gross_leverage: float = 3.0
    maximum_absolute_instrument_exposure: float = 0.50
    maximum_absolute_currency_exposure: float = 1.00
    no_trade_band: float = 0.05

    def __post_init__(self) -> None:
        positive = (
            self.ewma_lookback,
            self.instrument_volatility_target,
            self.covariance_lookback,
            self.portfolio_volatility_target,
            self.annualization_days,
            self.maximum_gross_leverage,
            self.maximum_absolute_instrument_exposure,
            self.maximum_absolute_currency_exposure,
        )
        if any(value <= 0 for value in positive):
            raise PortfolioInputError("Portfolio risk parameters must be positive")
        if not 0.0 < self.ewma_decay < 1.0:
            raise PortfolioInputError("EWMA decay must be strictly between zero and one")
        if not 0.0 <= self.no_trade_band < 1.0:
            raise PortfolioInputError("No-trade band must be in [0, 1)")


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """Executable bid and ask in quote currency per base currency unit."""

    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def is_valid(self) -> bool:
        return (
            math.isfinite(self.bid)
            and math.isfinite(self.ask)
            and self.bid > 0.0
            and self.ask > self.bid
        )


@dataclass(frozen=True, slots=True)
class RiskEstimate:
    """A fully lagged volatility and covariance snapshot."""

    decision_time: pd.Timestamp
    information_end: pd.Timestamp
    annualized_instrument_volatility: pd.Series
    daily_covariance: pd.DataFrame
    volatility_observations: int
    covariance_observations: int


@dataclass(frozen=True, slots=True)
class ExecutionCostConfig:
    commission_rate: float
    slippage_rate: float
    currency_conversion_rate: float

    def __post_init__(self) -> None:
        values = (self.commission_rate, self.slippage_rate, self.currency_conversion_rate)
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise PortfolioInputError("Execution cost rates must be finite and non-negative")
        if self.slippage_rate == 0.0:
            raise PortfolioInputError("Zero slippage is forbidden by the Gate F.0 contract")


@dataclass(frozen=True, slots=True)
class TradeExecution:
    instrument: str
    direction: str
    notional_change: float
    turnover: float
    bid: float
    ask: float
    side_quote: float
    fill_price: float
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    currency_conversion_cost: float

    @property
    def total_cost(self) -> float:
        return (
            self.spread_cost
            + self.commission_cost
            + self.slippage_cost
            + self.currency_conversion_cost
        )


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    spread: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    financing_markup: float = 0.0
    currency_conversion: float = 0.0

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value < 0.0 for value in self.values()):
            raise PortfolioInputError("Costs must be finite and non-negative")

    def values(self) -> tuple[float, ...]:
        return (
            self.spread,
            self.commission,
            self.slippage,
            self.financing_markup,
            self.currency_conversion,
        )

    @property
    def total(self) -> float:
        return sum(self.values())

    @classmethod
    def from_executions(
        cls,
        executions: Sequence[TradeExecution],
        *,
        financing_markup: float = 0.0,
    ) -> CostBreakdown:
        return cls(
            spread=math.fsum(row.spread_cost for row in executions),
            commission=math.fsum(row.commission_cost for row in executions),
            slippage=math.fsum(row.slippage_cost for row in executions),
            financing_markup=financing_markup,
            currency_conversion=math.fsum(row.currency_conversion_cost for row in executions),
        )


@dataclass(frozen=True, slots=True)
class FinancingResult:
    instrument: str
    signed_notional: float
    calendar_days: int
    base_currency: str
    quote_currency: str
    base_day_count_denominator: int
    quote_day_count_denominator: int
    base_day_count_fraction: float
    quote_day_count_fraction: float
    markup_day_count_fraction: float
    base_leg_return: float
    quote_leg_return: float
    financing_return: float
    markup_cost: float

    @property
    def day_count_fraction(self) -> float:
        """Backward-compatible alias for the separately charged markup fraction."""

        return self.markup_day_count_fraction

    @property
    def rate_differential(self) -> float:
        """Annualized simple-rate differential before currency day-count scaling."""

        direction = 1.0 if self.signed_notional >= 0.0 else -1.0
        if self.calendar_days == 0 or self.signed_notional == 0.0:
            return 0.0
        base_rate = self.base_leg_return / (self.signed_notional * self.base_day_count_fraction)
        quote_rate = self.quote_leg_return / (-self.signed_notional * self.quote_day_count_fraction)
        return direction * (base_rate - quote_rate)

    @property
    def net_financing(self) -> float:
        return self.financing_return - self.markup_cost


@dataclass(frozen=True, slots=True)
class RebalanceResult:
    positions_before: Mapping[str, float]
    desired_positions: Mapping[str, float]
    positions_after: Mapping[str, float]
    currency_exposures: Mapping[str, float]
    executions: tuple[TradeExecution, ...]
    scenario: CostScenario
    turnover: float
    costs: CostBreakdown
    action: str
    reasons: tuple[str, ...] = ()
    position_reconciliation_residual: float = 0.0
    currency_leg_reconciliation_residual: float = 0.0


@dataclass(frozen=True, slots=True)
class DailyAccounting:
    opening_nav: float
    closing_nav: float
    gross_trading_pnl: float
    financing_return: float
    costs: CostBreakdown
    net_pnl: float
    net_return: float
    opening_cash: float
    closing_cash: float
    residuals: Mapping[str, float] = field(default_factory=dict)


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(cast(SupportsFloat, value)))
    except (TypeError, ValueError):
        return False


def _validate_return_frame(returns: pd.DataFrame) -> None:
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise PortfolioInputError("Returns must use a DatetimeIndex")
    if returns.empty or returns.columns.empty:
        raise PortfolioInputError("Returns must not be empty")
    if not returns.index.is_monotonic_increasing or not returns.index.is_unique:
        raise PortfolioInputError("Return timestamps must be strictly increasing and unique")
    if not returns.columns.is_unique:
        raise PortfolioInputError("Return columns must be unique")


def _ewma_annualized_volatility(
    observations: pd.DataFrame,
    *,
    decay: float,
    annualization_days: int,
) -> pd.Series:
    values = observations.to_numpy(dtype=float)
    if not bool(np.isfinite(values).all()):
        raise PortfolioInputError("EWMA window contains missing or non-finite returns")
    weights = np.power(decay, np.arange(len(values) - 1, -1, -1, dtype=float))
    weights /= weights.sum()
    variances = np.sum(np.square(values) * weights[:, None], axis=0)
    volatility = np.sqrt(variances * annualization_days)
    return pd.Series(volatility, index=observations.columns, dtype=float)


def estimate_lagged_risk(
    returns: pd.DataFrame,
    decision_time: pd.Timestamp | datetime | str,
    config: PortfolioConfig | None = None,
) -> RiskEstimate:
    """Estimate 60-day EWMA volatility and 252-day Ledoit-Wolf covariance.

    Only rows with timestamps strictly before ``decision_time`` are eligible.
    Complete windows are mandatory; missing values are never filled.
    """

    config = config or PortfolioConfig()
    _validate_return_frame(returns)
    decision = pd.Timestamp(decision_time)
    history = returns.loc[returns.index < decision]
    required = max(config.ewma_lookback, config.covariance_lookback)
    if len(history) < required:
        raise PortfolioInputError(f"At least {required} strictly prior observations are required")
    covariance_window = history.tail(config.covariance_lookback)
    volatility_window = history.tail(config.ewma_lookback)
    covariance_values = covariance_window.to_numpy(dtype=float)
    if not bool(np.isfinite(covariance_values).all()):
        raise PortfolioInputError("Covariance window contains missing or non-finite returns")
    volatilities = _ewma_annualized_volatility(
        volatility_window,
        decay=config.ewma_decay,
        annualization_days=config.annualization_days,
    )
    covariance_array = LedoitWolf(assume_centered=False).fit(covariance_values).covariance_
    covariance = pd.DataFrame(
        covariance_array,
        index=returns.columns,
        columns=returns.columns,
        dtype=float,
    )
    return RiskEstimate(
        decision_time=decision,
        information_end=pd.Timestamp(history.index[-1]),
        annualized_instrument_volatility=volatilities,
        daily_covariance=covariance,
        volatility_observations=config.ewma_lookback,
        covariance_observations=config.covariance_lookback,
    )


def split_instrument(
    instrument: str,
    universe: PortfolioUniverse | None = None,
) -> tuple[str, str]:
    resolved = _resolve_universe(universe)
    if instrument not in resolved.instruments:
        raise PortfolioInputError(f"Instrument is outside the frozen universe: {instrument}")
    return instrument[:3], instrument[3:]


def compute_currency_exposures(
    positions: Mapping[str, float],
    *,
    universe: PortfolioUniverse | None = None,
) -> dict[str, float]:
    """Translate signed pair notionals into positive base and negative quote legs."""

    resolved = _resolve_universe(universe)
    exposures = dict.fromkeys(resolved.currencies, 0.0)
    for instrument, value in positions.items():
        if not _finite(value):
            raise PortfolioInputError(f"Non-finite position for {instrument}")
        base, quote = split_instrument(instrument, resolved)
        notional = float(value)
        exposures[base] += notional
        exposures[quote] -= notional
    return exposures


def _validate_complete_mapping(
    values: Mapping[str, float],
    name: str,
    universe: PortfolioUniverse | None = None,
) -> np.ndarray:
    resolved = _resolve_universe(universe)
    missing = [instrument for instrument in resolved.instruments if instrument not in values]
    if missing:
        raise PortfolioInputError(f"{name} is incomplete: {', '.join(missing)}")
    extras = set(values).difference(resolved.instruments)
    if extras:
        raise PortfolioInputError(f"{name} contains instruments outside the universe")
    array = np.asarray(
        [float(values[instrument]) for instrument in resolved.instruments], dtype=float
    )
    if not bool(np.isfinite(array).all()):
        raise PortfolioInputError(f"{name} contains non-finite values")
    return array


def construct_target_weights(
    signals: Mapping[str, float],
    risk: RiskEstimate,
    config: PortfolioConfig | None = None,
    *,
    universe: PortfolioUniverse | None = None,
) -> dict[str, float]:
    """Apply instrument targeting, portfolio targeting, then all frozen caps."""

    config = config or PortfolioConfig()
    resolved = _resolve_universe(universe)
    instruments = resolved.instruments
    signal_array = _validate_complete_mapping(signals, "Signals", resolved)
    if bool(np.any(np.abs(signal_array) > 1.0)):
        raise PortfolioInputError("Signal strengths must be in [-1, 1]")
    try:
        volatility = risk.annualized_instrument_volatility.loc[list(instruments)].to_numpy(
            dtype=float
        )
        covariance = risk.daily_covariance.loc[list(instruments), list(instruments)].to_numpy(
            dtype=float
        )
    except KeyError as exc:
        raise PortfolioInputError("Risk estimate does not cover the frozen universe") from exc
    if (
        not bool(np.isfinite(volatility).all())
        or not bool(np.isfinite(covariance).all())
        or bool(np.any(volatility <= 0.0))
    ):
        raise PortfolioInputError("Risk estimate contains invalid volatility or covariance")
    if not bool(np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-15)):
        raise PortfolioInputError("Covariance matrix must be symmetric")

    instrument_scaled = signal_array * config.instrument_volatility_target / volatility
    variance = float(instrument_scaled @ covariance @ instrument_scaled)
    if variance < -1e-15:
        raise PortfolioInputError("Covariance matrix produces negative portfolio variance")
    if variance <= 0.0 or not bool(np.any(instrument_scaled)):
        return dict.fromkeys(instruments, 0.0)
    annualized_volatility = math.sqrt(max(0.0, variance) * config.annualization_days)
    target = instrument_scaled * (config.portfolio_volatility_target / annualized_volatility)

    provisional = dict(zip(instruments, target, strict=True))
    currency = compute_currency_exposures(provisional, universe=resolved)
    gross = float(np.abs(target).sum())
    maximum_instrument = float(np.abs(target).max(initial=0.0))
    maximum_currency = max((abs(value) for value in currency.values()), default=0.0)
    constraint_scale = min(
        1.0,
        config.maximum_gross_leverage / gross if gross > 0.0 else 1.0,
        (
            config.maximum_absolute_instrument_exposure / maximum_instrument
            if maximum_instrument > 0.0
            else 1.0
        ),
        (
            config.maximum_absolute_currency_exposure / maximum_currency
            if maximum_currency > 0.0
            else 1.0
        ),
    )
    return {
        instrument: float(value * constraint_scale)
        for instrument, value in zip(instruments, target, strict=True)
    }


def apply_no_trade_band(
    current_positions: Mapping[str, float],
    desired_positions: Mapping[str, float],
    threshold: float = 0.05,
    *,
    universe: PortfolioUniverse | None = None,
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Keep a position when its required change is strictly inside the frozen band."""

    resolved = _resolve_universe(universe)
    current = _validate_complete_mapping(current_positions, "Current positions", resolved)
    desired = _validate_complete_mapping(desired_positions, "Desired positions", resolved)
    if not 0.0 <= threshold < 1.0:
        raise PortfolioInputError("No-trade threshold must be in [0, 1)")
    result: dict[str, float] = {}
    held: list[str] = []
    for index, instrument in enumerate(resolved.instruments):
        change = abs(desired[index] - current[index])
        band = threshold * abs(current[index])
        at_boundary = math.isclose(change, band, rel_tol=1e-12, abs_tol=1e-15)
        inside = current[index] != 0.0 and change < band and not at_boundary
        if inside:
            result[instrument] = float(current[index])
            held.append(instrument)
        else:
            result[instrument] = float(desired[index])
    return result, tuple(held)


def is_friday_flatten_due(timestamp: datetime | pd.Timestamp) -> bool:
    """Return whether New York local time is Friday at or after 16:55."""

    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        raise PortfolioInputError("Friday-flat timestamps must be timezone-aware")
    local = value.to_pydatetime().astimezone(NEW_YORK)
    return local.weekday() == 4 and (local.hour, local.minute) >= (16, 55)


def friday_flatten_targets(
    desired_positions: Mapping[str, float],
    timestamp: datetime | pd.Timestamp,
    *,
    universe: PortfolioUniverse | None = None,
) -> dict[str, float]:
    """Force every desired pair notional to zero once the Friday deadline is due."""

    resolved = _resolve_universe(universe)
    desired = _validate_complete_mapping(desired_positions, "Desired positions", resolved)
    if is_friday_flatten_due(timestamp):
        return dict.fromkeys(resolved.instruments, 0.0)
    return dict(zip(resolved.instruments, desired, strict=True))


def _missing_rebalance_inputs(
    signals: Mapping[str, float],
    current_positions: Mapping[str, float],
    quotes: Mapping[str, MarketQuote],
    rates: Mapping[str, float],
    risk: RiskEstimate,
    universe: PortfolioUniverse | None = None,
) -> tuple[str, ...]:
    resolved = _resolve_universe(universe)
    reasons: list[str] = []
    for instrument in resolved.instruments:
        if instrument not in signals or not _finite(signals.get(instrument)):
            reasons.append(f"MISSING_SIGNAL:{instrument}")
        if instrument not in current_positions or not _finite(current_positions.get(instrument)):
            reasons.append(f"MISSING_CURRENT_POSITION:{instrument}")
        quote = quotes.get(instrument)
        if quote is None or not quote.is_valid():
            reasons.append(f"MISSING_OR_INVALID_BID_ASK:{instrument}")
    for currency in resolved.currencies:
        if currency not in rates or not _finite(rates.get(currency)):
            reasons.append(f"MISSING_RATE:{currency}")
    try:
        volatility = risk.annualized_instrument_volatility.loc[list(resolved.instruments)]
        covariance = risk.daily_covariance.loc[
            list(resolved.instruments), list(resolved.instruments)
        ]
        if not bool(np.isfinite(volatility.to_numpy(dtype=float)).all()):
            reasons.append("MISSING_VOLATILITY")
        if not bool(np.isfinite(covariance.to_numpy(dtype=float)).all()):
            reasons.append("MISSING_COVARIANCE")
    except KeyError:
        reasons.append("INCOMPLETE_RISK_UNIVERSE")
    return tuple(reasons)


def execute_rebalance(
    current_positions: Mapping[str, float],
    desired_positions: Mapping[str, float],
    quotes: Mapping[str, MarketQuote],
    scenario: CostScenario,
    costs: ExecutionCostConfig,
    *,
    universe: PortfolioUniverse | None = None,
) -> tuple[tuple[TradeExecution, ...], CostBreakdown]:
    """Execute pair-notional changes at side-correct stressed bid/ask prices."""

    resolved = _resolve_universe(universe)
    current = _validate_complete_mapping(current_positions, "Current positions", resolved)
    desired = _validate_complete_mapping(desired_positions, "Desired positions", resolved)
    parameters = SCENARIO_PARAMETERS[scenario]
    rows: list[TradeExecution] = []
    for index, instrument in enumerate(resolved.instruments):
        change = float(desired[index] - current[index])
        if change == 0.0:
            continue
        quote = quotes.get(instrument)
        if quote is None or not quote.is_valid():
            raise PortfolioInputError(f"Missing or invalid executable quote for {instrument}")
        mid = quote.mid
        direction = "BUY" if change > 0.0 else "SELL"
        side_quote = quote.ask if change > 0.0 else quote.bid
        stressed_spread = abs(side_quote - mid) * parameters.spread_multiplier
        slippage = mid * costs.slippage_rate * parameters.slippage_multiplier
        fill_price = (
            mid + stressed_spread + slippage if change > 0.0 else mid - stressed_spread - slippage
        )
        turnover = abs(change)
        rows.append(
            TradeExecution(
                instrument=instrument,
                direction=direction,
                notional_change=change,
                turnover=turnover,
                bid=quote.bid,
                ask=quote.ask,
                side_quote=side_quote,
                fill_price=fill_price,
                spread_cost=turnover * stressed_spread / mid,
                commission_cost=turnover * costs.commission_rate,
                slippage_cost=turnover * costs.slippage_rate * parameters.slippage_multiplier,
                currency_conversion_cost=turnover * costs.currency_conversion_rate,
            )
        )
    executions = tuple(rows)
    return executions, CostBreakdown.from_executions(executions)


def calculate_financing(
    instrument: str,
    signed_notional: float,
    base_annual_rate: float,
    quote_annual_rate: float,
    held_from: datetime | pd.Timestamp,
    held_until: datetime | pd.Timestamp,
    scenario: CostScenario = CostScenario.BASE,
    *,
    universe: PortfolioUniverse | None = None,
) -> FinancingResult:
    """Calculate carry on each currency leg using its frozen day-count basis."""

    base_currency, quote_currency = split_instrument(instrument, universe)
    values = (signed_notional, base_annual_rate, quote_annual_rate)
    if any(not _finite(value) for value in values):
        raise PortfolioInputError("Financing inputs must be finite")
    start = pd.Timestamp(held_from)
    end = pd.Timestamp(held_until)
    if (start.tzinfo is None) != (end.tzinfo is None):
        raise PortfolioInputError("Financing timestamps must have matching timezone awareness")
    calendar_days = (end.date() - start.date()).days
    if calendar_days < 0:
        raise PortfolioInputError("Financing end must not precede financing start")
    base_denominator = RATE_DAY_COUNT_DENOMINATORS[base_currency]
    quote_denominator = RATE_DAY_COUNT_DENOMINATORS[quote_currency]
    base_fraction = calendar_days / base_denominator
    quote_fraction = calendar_days / quote_denominator
    markup_fraction = calendar_days / 365.0
    notional = float(signed_notional)
    absolute_notional = abs(notional)
    base_leg_return = notional * float(base_annual_rate) * base_fraction
    quote_leg_return = -notional * float(quote_annual_rate) * quote_fraction
    financing_return = base_leg_return + quote_leg_return
    markup_cost = (
        absolute_notional
        * SCENARIO_PARAMETERS[scenario].financing_markup_annualized
        * markup_fraction
    )
    return FinancingResult(
        instrument=instrument,
        signed_notional=notional,
        calendar_days=calendar_days,
        base_currency=base_currency,
        quote_currency=quote_currency,
        base_day_count_denominator=base_denominator,
        quote_day_count_denominator=quote_denominator,
        base_day_count_fraction=base_fraction,
        quote_day_count_fraction=quote_fraction,
        markup_day_count_fraction=markup_fraction,
        base_leg_return=base_leg_return,
        quote_leg_return=quote_leg_return,
        financing_return=financing_return,
        markup_cost=markup_cost,
    )


def reconcile_daily_accounting(
    *,
    opening_nav: float,
    gross_trading_pnl: float,
    financing_return: float,
    costs: CostBreakdown,
    opening_cash: float | None = None,
    reported_net_pnl: float | None = None,
    reported_closing_nav: float | None = None,
    reported_closing_cash: float | None = None,
) -> DailyAccounting:
    """Build and strictly reconcile the frozen gross-to-net accounting identity."""

    numeric = (opening_nav, gross_trading_pnl, financing_return)
    if any(not _finite(value) for value in numeric) or opening_nav <= 0.0:
        raise PortfolioInputError("NAV and PnL inputs must be finite and opening NAV positive")
    cash = float(opening_nav if opening_cash is None else opening_cash)
    if not _finite(cash):
        raise PortfolioInputError("Opening cash must be finite")
    net_pnl = float(gross_trading_pnl + financing_return - costs.total)
    closing_nav = float(opening_nav + net_pnl)
    closing_cash = float(cash + net_pnl)
    residuals = {
        "gross_to_net": 0.0,
        "nav": 0.0,
        "cash": 0.0,
        "cost": 0.0,
    }
    if reported_net_pnl is not None:
        residuals["gross_to_net"] = float(reported_net_pnl - net_pnl)
    if reported_closing_nav is not None:
        residuals["nav"] = float(reported_closing_nav - closing_nav)
    if reported_closing_cash is not None:
        residuals["cash"] = float(reported_closing_cash - closing_cash)
    nonzero = {name: value for name, value in residuals.items() if value != 0.0}
    if nonzero:
        raise AccountingReconciliationError(f"Non-zero accounting residuals: {nonzero}")
    return DailyAccounting(
        opening_nav=float(opening_nav),
        closing_nav=closing_nav,
        gross_trading_pnl=float(gross_trading_pnl),
        financing_return=float(financing_return),
        costs=costs,
        net_pnl=net_pnl,
        net_return=net_pnl / opening_nav,
        opening_cash=cash,
        closing_cash=closing_cash,
        residuals=MappingProxyType(residuals),
    )


class ClassicalFxPortfolioEngine:
    """Pure, deterministic orchestration of F.0 construction and accounting."""

    def __init__(
        self,
        config: PortfolioConfig | None = None,
        execution_costs: ExecutionCostConfig | None = None,
        universe: PortfolioUniverse | None = None,
    ) -> None:
        self.config = config or PortfolioConfig()
        self.universe = _resolve_universe(universe)
        self.execution_costs = execution_costs or ExecutionCostConfig(
            commission_rate=0.00002,
            slippage_rate=0.00001,
            currency_conversion_rate=0.00001,
        )

    def estimate_risk(
        self,
        returns: pd.DataFrame,
        decision_time: pd.Timestamp | datetime | str,
    ) -> RiskEstimate:
        return estimate_lagged_risk(returns, decision_time, self.config)

    def rebalance(
        self,
        *,
        decision_time: datetime | pd.Timestamp,
        signals: Mapping[str, float],
        current_positions: Mapping[str, float],
        quotes: Mapping[str, MarketQuote],
        published_rates: Mapping[str, float],
        risk: RiskEstimate,
        scenario: CostScenario = CostScenario.BASE,
    ) -> RebalanceResult:
        """Construct and execute one daily rebalance, failing closed on missing input."""

        reasons = _missing_rebalance_inputs(
            signals, current_positions, quotes, published_rates, risk, self.universe
        )
        if reasons:
            try:
                unchanged_array = _validate_complete_mapping(
                    current_positions, "Current positions", self.universe
                )
            except PortfolioInputError:
                unchanged_array = np.zeros(len(self.universe.instruments), dtype=float)
            unchanged = dict(zip(self.universe.instruments, unchanged_array, strict=True))
            currency = compute_currency_exposures(unchanged, universe=self.universe)
            return RebalanceResult(
                positions_before=MappingProxyType(unchanged.copy()),
                desired_positions=MappingProxyType(unchanged.copy()),
                positions_after=MappingProxyType(unchanged.copy()),
                currency_exposures=MappingProxyType(currency),
                executions=(),
                scenario=scenario,
                turnover=0.0,
                costs=CostBreakdown(),
                action=NO_POSITION_CHANGE,
                reasons=reasons,
            )

        current_array = _validate_complete_mapping(
            current_positions, "Current positions", self.universe
        )
        before = dict(zip(self.universe.instruments, current_array, strict=True))
        desired = construct_target_weights(signals, risk, self.config, universe=self.universe)
        desired = friday_flatten_targets(desired, decision_time, universe=self.universe)
        after, inside_band = apply_no_trade_band(
            before, desired, self.config.no_trade_band, universe=self.universe
        )
        # The Friday rule has priority over the ordinary no-trade band.
        if is_friday_flatten_due(decision_time):
            after = dict.fromkeys(self.universe.instruments, 0.0)
            inside_band = ()
        executions, execution_costs = execute_rebalance(
            before,
            after,
            quotes,
            scenario,
            self.execution_costs,
            universe=self.universe,
        )
        reconstructed = before.copy()
        for row in executions:
            reconstructed[row.instrument] += row.notional_change
        position_residual = max(
            (abs(reconstructed[name] - after[name]) for name in self.universe.instruments),
            default=0.0,
        )
        currency = compute_currency_exposures(after, universe=self.universe)
        reconstructed_currency = compute_currency_exposures(reconstructed, universe=self.universe)
        currency_residual = max(
            (
                abs(reconstructed_currency[name] - currency[name])
                for name in self.universe.currencies
            ),
            default=0.0,
        )
        if position_residual != 0.0 or currency_residual != 0.0:
            raise AccountingReconciliationError("Non-zero position or currency-leg residual")
        action_reasons = tuple(f"NO_TRADE_BAND:{name}" for name in inside_band)
        return RebalanceResult(
            positions_before=MappingProxyType(before),
            desired_positions=MappingProxyType(desired),
            positions_after=MappingProxyType(after),
            currency_exposures=MappingProxyType(currency),
            executions=executions,
            scenario=scenario,
            turnover=math.fsum(row.turnover for row in executions),
            costs=execution_costs,
            action="REBALANCED" if executions else NO_POSITION_CHANGE,
            reasons=action_reasons or (() if executions else ("TARGET_EQUALS_CURRENT",)),
            position_reconciliation_residual=position_residual,
            currency_leg_reconciliation_residual=currency_residual,
        )

    def account_day(
        self,
        *,
        opening_nav: float,
        gross_trading_pnl: float,
        financing: Sequence[FinancingResult],
        rebalance: RebalanceResult,
        opening_cash: float | None = None,
    ) -> DailyAccounting:
        financing_return = math.fsum(row.financing_return for row in financing)
        financing_markup = math.fsum(row.markup_cost for row in financing)
        costs = CostBreakdown(
            spread=rebalance.costs.spread,
            commission=rebalance.costs.commission,
            slippage=rebalance.costs.slippage,
            financing_markup=financing_markup,
            currency_conversion=rebalance.costs.currency_conversion,
        )
        return reconcile_daily_accounting(
            opening_nav=opening_nav,
            gross_trading_pnl=gross_trading_pnl,
            financing_return=financing_return,
            costs=costs,
            opening_cash=opening_cash,
        )
