from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from fx_smc_bot.research.classical_fx_portfolio import (
    CURRENCIES,
    INSTRUMENTS,
    NO_POSITION_CHANGE,
    RATE_DAY_COUNT_DENOMINATORS,
    SCENARIO_PARAMETERS,
    AccountingReconciliationError,
    ClassicalFxPortfolioEngine,
    CostBreakdown,
    CostScenario,
    ExecutionCostConfig,
    MarketQuote,
    PortfolioConfig,
    PortfolioInputError,
    RiskEstimate,
    apply_no_trade_band,
    calculate_financing,
    compute_currency_exposures,
    construct_target_weights,
    estimate_lagged_risk,
    execute_rebalance,
    friday_flatten_targets,
    is_friday_flatten_due,
    reconcile_daily_accounting,
)


def _positions(value: float = 0.0) -> dict[str, float]:
    return dict.fromkeys(INSTRUMENTS, value)


def _signals(value: float = 0.0) -> dict[str, float]:
    return dict.fromkeys(INSTRUMENTS, value)


def _quotes() -> dict[str, MarketQuote]:
    return {instrument: MarketQuote(0.9999, 1.0001) for instrument in INSTRUMENTS}


def _rates() -> dict[str, float]:
    return {currency: 0.02 for currency in CURRENCIES}


def _risk(
    *,
    annualized_volatility: float = 0.10,
    daily_variance: float = 0.0001,
) -> RiskEstimate:
    covariance = np.eye(len(INSTRUMENTS), dtype=float) * daily_variance
    return RiskEstimate(
        decision_time=pd.Timestamp("2020-01-02"),
        information_end=pd.Timestamp("2020-01-01"),
        annualized_instrument_volatility=pd.Series(
            annualized_volatility, index=INSTRUMENTS, dtype=float
        ),
        daily_covariance=pd.DataFrame(covariance, index=INSTRUMENTS, columns=INSTRUMENTS),
        volatility_observations=60,
        covariance_observations=252,
    )


def _execution_costs() -> ExecutionCostConfig:
    return ExecutionCostConfig(
        commission_rate=0.00002,
        slippage_rate=0.00001,
        currency_conversion_rate=0.00003,
    )


def test_frozen_defaults_and_scenarios_are_exact() -> None:
    config = PortfolioConfig()
    assert config.ewma_lookback == 60
    assert config.ewma_decay == 0.94
    assert config.instrument_volatility_target == 0.10
    assert config.covariance_lookback == 252
    assert config.portfolio_volatility_target == 0.10
    assert config.maximum_gross_leverage == 3.0
    assert config.maximum_absolute_instrument_exposure == 0.50
    assert config.maximum_absolute_currency_exposure == 1.0
    assert config.no_trade_band == 0.05
    assert SCENARIO_PARAMETERS[CostScenario.BASE].financing_markup_annualized == 0.005
    assert SCENARIO_PARAMETERS[CostScenario.STRESS_1].spread_multiplier == 1.5
    assert SCENARIO_PARAMETERS[CostScenario.STRESS_2].slippage_multiplier == 2.0
    assert SCENARIO_PARAMETERS[CostScenario.STRESS_2].financing_markup_annualized == 0.015


def test_lagged_risk_uses_exact_windows_and_riskmetrics_ewma() -> None:
    index = pd.date_range("2018-01-01", periods=254, freq="D")
    daily_return = 0.01
    returns = pd.DataFrame(
        {
            "EURUSD": np.full(len(index), daily_return),
            "GBPUSD": np.linspace(-0.01, 0.01, len(index)),
        },
        index=index,
    )
    estimate = estimate_lagged_risk(returns, index[253])
    assert estimate.information_end == index[252]
    assert estimate.volatility_observations == 60
    assert estimate.covariance_observations == 252
    assert estimate.annualized_instrument_volatility["EURUSD"] == pytest.approx(
        daily_return * np.sqrt(252)
    )
    assert estimate.daily_covariance.shape == (2, 2)
    assert np.isfinite(estimate.daily_covariance.to_numpy()).all()


def test_lagged_risk_cannot_see_decision_or_future_returns() -> None:
    rng = np.random.default_rng(1729)
    index = pd.date_range("2018-01-01", periods=270, freq="D")
    returns = pd.DataFrame(
        rng.normal(0.0, 0.01, size=(len(index), 3)),
        index=index,
        columns=["EURUSD", "GBPUSD", "USDJPY"],
    )
    decision = index[260]
    baseline = estimate_lagged_risk(returns, decision)
    changed = returns.copy()
    changed.loc[changed.index >= decision, :] = 1000.0
    replay = estimate_lagged_risk(changed, decision)
    pd.testing.assert_series_equal(
        baseline.annualized_instrument_volatility,
        replay.annualized_instrument_volatility,
    )
    pd.testing.assert_frame_equal(baseline.daily_covariance, replay.daily_covariance)


def test_lagged_risk_rejects_incomplete_and_missing_windows() -> None:
    short = pd.DataFrame(
        {"EURUSD": np.ones(251)},
        index=pd.date_range("2019-01-01", periods=251, freq="D"),
    )
    with pytest.raises(PortfolioInputError, match="252"):
        estimate_lagged_risk(short, "2020-01-01")
    complete = pd.concat(
        [
            short,
            pd.DataFrame(
                {"EURUSD": [np.nan]},
                index=[pd.Timestamp("2019-09-09")],
            ),
        ]
    )
    with pytest.raises(PortfolioInputError, match="missing"):
        estimate_lagged_risk(complete, "2020-01-01")


def test_currency_exposures_are_base_positive_quote_negative() -> None:
    positions = _positions()
    positions["EURUSD"] = 0.40
    positions["USDJPY"] = -0.25
    exposures = compute_currency_exposures(positions)
    assert exposures["EUR"] == pytest.approx(0.40)
    assert exposures["USD"] == pytest.approx(-0.65)
    assert exposures["JPY"] == pytest.approx(0.25)
    assert sum(exposures.values()) == pytest.approx(0.0, abs=1e-15)


def test_target_construction_hits_portfolio_target_when_caps_do_not_bind() -> None:
    signals = _signals()
    signals["EURUSD"] = 1.0
    config = PortfolioConfig(
        maximum_gross_leverage=10.0,
        maximum_absolute_instrument_exposure=2.0,
        maximum_absolute_currency_exposure=2.0,
    )
    covariance = np.eye(len(INSTRUMENTS)) * (0.10 / np.sqrt(252)) ** 2
    risk = _risk()
    risk = RiskEstimate(
        risk.decision_time,
        risk.information_end,
        risk.annualized_instrument_volatility,
        pd.DataFrame(covariance, index=INSTRUMENTS, columns=INSTRUMENTS),
        60,
        252,
    )
    target = construct_target_weights(signals, risk, config)
    vector = np.asarray([target[name] for name in INSTRUMENTS])
    annualized_volatility = np.sqrt(vector @ covariance @ vector * 252)
    assert annualized_volatility == pytest.approx(0.10)
    assert target["EURUSD"] == pytest.approx(1.0)


def test_all_portfolio_caps_bind_without_reversing_signals() -> None:
    signals = {name: (1.0 if index % 2 == 0 else -1.0) for index, name in enumerate(INSTRUMENTS)}
    target = construct_target_weights(signals, _risk(daily_variance=1e-12))
    currency = compute_currency_exposures(target)
    assert sum(abs(value) for value in target.values()) <= 3.0 + 1e-12
    assert max(abs(value) for value in target.values()) <= 0.50 + 1e-12
    assert max(abs(value) for value in currency.values()) <= 1.0 + 1e-12
    for name in INSTRUMENTS:
        assert np.sign(target[name]) == np.sign(signals[name])


def test_currency_cap_uses_pair_legs_after_risk_scaling() -> None:
    config = PortfolioConfig(
        maximum_gross_leverage=100.0,
        maximum_absolute_instrument_exposure=100.0,
        maximum_absolute_currency_exposure=0.20,
    )
    signals = _signals()
    signals["EURUSD"] = 1.0
    signals["GBPUSD"] = 1.0
    target = construct_target_weights(signals, _risk(daily_variance=1e-8), config)
    maximum_currency = max(abs(value) for value in compute_currency_exposures(target).values())
    assert maximum_currency == pytest.approx(0.20)


def test_no_trade_band_is_strict_and_zero_current_has_no_band() -> None:
    current = _positions()
    current["EURUSD"] = 0.20
    desired = current.copy()
    desired["EURUSD"] = 0.209
    desired["GBPUSD"] = 0.001
    after, held = apply_no_trade_band(current, desired)
    assert after["EURUSD"] == 0.20
    assert after["GBPUSD"] == 0.001
    assert held == ("EURUSD",)

    equality = current.copy()
    equality["EURUSD"] = 0.21
    after_equality, held_equality = apply_no_trade_band(current, equality)
    assert after_equality["EURUSD"] == 0.21
    assert "EURUSD" not in held_equality


def test_bid_ask_execution_is_side_correct_and_reconciles_costs() -> None:
    current = _positions()
    desired = _positions()
    desired["EURUSD"] = 0.30
    desired["GBPUSD"] = -0.20
    executions, costs = execute_rebalance(
        current,
        desired,
        _quotes(),
        CostScenario.BASE,
        _execution_costs(),
    )
    buy, sell = executions
    assert buy.direction == "BUY"
    assert buy.side_quote == buy.ask
    assert buy.fill_price > buy.ask
    assert sell.direction == "SELL"
    assert sell.side_quote == sell.bid
    assert sell.fill_price < sell.bid
    assert sum(row.turnover for row in executions) == pytest.approx(0.50)
    assert costs.total == pytest.approx(sum(row.total_cost for row in executions))


def test_cost_stress_multiplies_only_spread_and_slippage() -> None:
    desired = _positions()
    desired["EURUSD"] = 0.50
    _, base = execute_rebalance(
        _positions(), desired, _quotes(), CostScenario.BASE, _execution_costs()
    )
    _, stress = execute_rebalance(
        _positions(), desired, _quotes(), CostScenario.STRESS_2, _execution_costs()
    )
    assert stress.spread == pytest.approx(2.0 * base.spread)
    assert stress.slippage == pytest.approx(2.0 * base.slippage)
    assert stress.commission == base.commission
    assert stress.currency_conversion == base.currency_conversion


def test_financing_direction_sign_markup_and_actual_calendar_days() -> None:
    start = datetime(2020, 1, 3, 17, 0, tzinfo=UTC)
    end = datetime(2020, 1, 6, 17, 0, tzinfo=UTC)
    long = calculate_financing("EURUSD", 0.50, 0.03, 0.01, start, end, CostScenario.BASE)
    short = calculate_financing("EURUSD", -0.50, 0.03, 0.01, start, end, CostScenario.STRESS_2)
    assert long.calendar_days == 3
    assert long.day_count_fraction == pytest.approx(3 / 365)
    assert long.base_day_count_denominator == 360
    assert long.quote_day_count_denominator == 360
    assert long.financing_return == pytest.approx(0.50 * 0.02 * 3 / 360)
    assert short.financing_return == pytest.approx(-long.financing_return)
    assert long.markup_cost == pytest.approx(0.50 * 0.005 * 3 / 365)
    assert short.markup_cost == pytest.approx(0.50 * 0.015 * 3 / 365)
    assert long.net_financing == pytest.approx(long.financing_return - long.markup_cost)


@pytest.mark.parametrize(
    ("instrument", "base_denominator", "quote_denominator"),
    [
        ("EURUSD", 360, 360),
        ("USDJPY", 360, 365),
        ("GBPUSD", 365, 360),
        ("AUDJPY", 365, 365),
        ("USDCAD", 360, 365),
        ("USDCHF", 360, 360),
    ],
)
def test_financing_uses_currency_leg_day_counts(
    instrument: str,
    base_denominator: int,
    quote_denominator: int,
) -> None:
    days = 7
    signed_notional = 0.80
    base_rate = 0.041
    quote_rate = 0.017
    result = calculate_financing(
        instrument,
        signed_notional,
        base_rate,
        quote_rate,
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 8, tzinfo=UTC),
        CostScenario.STRESS_1,
    )
    assert result.base_day_count_denominator == base_denominator
    assert result.quote_day_count_denominator == quote_denominator
    assert result.base_leg_return == pytest.approx(
        signed_notional * base_rate * days / base_denominator
    )
    assert result.quote_leg_return == pytest.approx(
        -signed_notional * quote_rate * days / quote_denominator
    )
    assert result.financing_return == pytest.approx(
        result.base_leg_return + result.quote_leg_return
    )
    assert result.markup_cost == pytest.approx(signed_notional * 0.01 * days / 365)


def test_financing_short_reverses_both_currency_legs_but_not_markup() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 1, 4, tzinfo=UTC)
    long = calculate_financing("GBPUSD", 0.6, 0.05, 0.02, start, end)
    short = calculate_financing("GBPUSD", -0.6, 0.05, 0.02, start, end)
    assert short.base_leg_return == pytest.approx(-long.base_leg_return)
    assert short.quote_leg_return == pytest.approx(-long.quote_leg_return)
    assert short.financing_return == pytest.approx(-long.financing_return)
    assert short.markup_cost == pytest.approx(long.markup_cost)


def test_frozen_currency_day_count_map_is_complete_and_exact() -> None:
    assert RATE_DAY_COUNT_DENOMINATORS == {
        "USD": 360,
        "EUR": 360,
        "CHF": 360,
        "GBP": 365,
        "JPY": 365,
        "AUD": 365,
        "NZD": 365,
        "CAD": 365,
    }


def test_financing_uses_dates_not_elapsed_24_hour_blocks() -> None:
    result = calculate_financing(
        "USDJPY",
        1.0,
        0.04,
        0.01,
        datetime(2020, 1, 1, 23, 59, tzinfo=UTC),
        datetime(2020, 1, 2, 0, 1, tzinfo=UTC),
    )
    assert result.calendar_days == 1


def test_friday_flat_rule_is_timezone_aware_and_forces_zero() -> None:
    before = datetime(2020, 1, 3, 21, 54, tzinfo=UTC)
    deadline = datetime(2020, 1, 3, 21, 55, tzinfo=UTC)
    assert not is_friday_flatten_due(before)
    assert is_friday_flatten_due(deadline)
    desired = _positions(0.10)
    assert friday_flatten_targets(desired, before) == desired
    assert friday_flatten_targets(desired, deadline) == _positions()
    with pytest.raises(PortfolioInputError, match="timezone-aware"):
        is_friday_flatten_due(datetime(2020, 1, 3, 16, 55))


def test_missing_required_input_fails_closed_with_recorded_reason() -> None:
    engine = ClassicalFxPortfolioEngine(execution_costs=_execution_costs())
    current = _positions()
    current["EURUSD"] = 0.20
    quotes = _quotes()
    del quotes["GBPUSD"]
    result = engine.rebalance(
        decision_time=datetime(2020, 1, 2, 22, 5, tzinfo=UTC),
        signals=_signals(1.0),
        current_positions=current,
        quotes=quotes,
        published_rates=_rates(),
        risk=_risk(),
    )
    assert result.action == NO_POSITION_CHANGE
    assert result.positions_after == current
    assert result.executions == ()
    assert result.turnover == 0.0
    assert result.reasons == ("MISSING_OR_INVALID_BID_ASK:GBPUSD",)


def test_zero_spread_quote_is_a_missing_required_execution_input() -> None:
    quotes = _quotes()
    quotes["EURUSD"] = MarketQuote(1.0, 1.0)
    result = ClassicalFxPortfolioEngine().rebalance(
        decision_time=datetime(2020, 1, 2, 22, 5, tzinfo=UTC),
        signals=_signals(),
        current_positions=_positions(),
        quotes=quotes,
        published_rates=_rates(),
        risk=_risk(),
    )
    assert result.action == NO_POSITION_CHANGE
    assert "MISSING_OR_INVALID_BID_ASK:EURUSD" in result.reasons


def test_missing_rate_and_covariance_are_explicit_fail_closed_reasons() -> None:
    rates = _rates()
    del rates["CHF"]
    risk = _risk()
    covariance = risk.daily_covariance.copy()
    covariance.loc["EURUSD", "EURUSD"] = np.nan
    broken_risk = RiskEstimate(
        risk.decision_time,
        risk.information_end,
        risk.annualized_instrument_volatility,
        covariance,
        60,
        252,
    )
    result = ClassicalFxPortfolioEngine().rebalance(
        decision_time=datetime(2020, 1, 2, 22, 5, tzinfo=UTC),
        signals=_signals(),
        current_positions=_positions(),
        quotes=_quotes(),
        published_rates=rates,
        risk=broken_risk,
    )
    assert "MISSING_RATE:CHF" in result.reasons
    assert "MISSING_COVARIANCE" in result.reasons
    assert result.action == NO_POSITION_CHANGE


def test_engine_rebalance_has_zero_position_currency_and_cost_residuals() -> None:
    engine = ClassicalFxPortfolioEngine(execution_costs=_execution_costs())
    signals = _signals()
    signals["EURUSD"] = 1.0
    signals["USDJPY"] = -1.0
    result = engine.rebalance(
        decision_time=datetime(2020, 1, 2, 22, 5, tzinfo=UTC),
        signals=signals,
        current_positions=_positions(),
        quotes=_quotes(),
        published_rates=_rates(),
        risk=_risk(),
    )
    assert result.action == "REBALANCED"
    assert result.position_reconciliation_residual == 0.0
    assert result.currency_leg_reconciliation_residual == 0.0
    assert result.turnover == pytest.approx(sum(row.turnover for row in result.executions))
    assert result.costs == CostBreakdown.from_executions(result.executions)
    assert max(abs(value) for value in result.positions_after.values()) <= 0.50


def test_friday_flat_has_priority_over_no_trade_band() -> None:
    current = _positions()
    current["EURUSD"] = 0.20
    result = ClassicalFxPortfolioEngine(execution_costs=_execution_costs()).rebalance(
        decision_time=datetime(2020, 1, 3, 21, 55, tzinfo=UTC),
        signals=_signals(1.0),
        current_positions=current,
        quotes=_quotes(),
        published_rates=_rates(),
        risk=_risk(),
    )
    assert result.positions_after == _positions()
    assert len(result.executions) == 1
    assert result.executions[0].direction == "SELL"


def test_daily_accounting_exactly_reconciles_gross_to_net_nav_and_cash() -> None:
    costs = CostBreakdown(
        spread=1.0,
        commission=2.0,
        slippage=3.0,
        financing_markup=4.0,
        currency_conversion=5.0,
    )
    accounting = reconcile_daily_accounting(
        opening_nav=1000.0,
        opening_cash=900.0,
        gross_trading_pnl=30.0,
        financing_return=5.0,
        costs=costs,
    )
    assert accounting.net_pnl == 20.0
    assert accounting.closing_nav == 1020.0
    assert accounting.closing_cash == 920.0
    assert accounting.net_return == 0.02
    assert accounting.residuals == {"gross_to_net": 0.0, "nav": 0.0, "cash": 0.0, "cost": 0.0}


def test_any_nonzero_reported_accounting_residual_is_rejected() -> None:
    with pytest.raises(AccountingReconciliationError, match="Non-zero"):
        reconcile_daily_accounting(
            opening_nav=1000.0,
            gross_trading_pnl=10.0,
            financing_return=0.0,
            costs=CostBreakdown(spread=1.0),
            reported_net_pnl=9.000000000000002,
        )


def test_engine_account_day_combines_execution_and_financing_components() -> None:
    engine = ClassicalFxPortfolioEngine(execution_costs=_execution_costs())
    desired = _positions()
    desired["EURUSD"] = 0.50
    executions, execution_costs = execute_rebalance(
        _positions(), desired, _quotes(), CostScenario.BASE, _execution_costs()
    )
    exposures = compute_currency_exposures(desired)
    from fx_smc_bot.research.classical_fx_portfolio import RebalanceResult

    rebalance = RebalanceResult(
        positions_before=_positions(),
        desired_positions=desired,
        positions_after=desired,
        currency_exposures=exposures,
        executions=executions,
        scenario=CostScenario.BASE,
        turnover=0.50,
        costs=execution_costs,
        action="REBALANCED",
    )
    financing = calculate_financing(
        "EURUSD",
        0.50,
        0.03,
        0.01,
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 2, tzinfo=UTC),
    )
    accounting = engine.account_day(
        opening_nav=1.0,
        gross_trading_pnl=0.01,
        financing=[financing],
        rebalance=rebalance,
    )
    expected = 0.01 + financing.financing_return - execution_costs.total - financing.markup_cost
    assert accounting.net_pnl == pytest.approx(expected)
    assert accounting.costs.financing_markup == financing.markup_cost
    assert all(value == 0.0 for value in accounting.residuals.values())


def test_invalid_inputs_are_rejected_instead_of_silently_normalized() -> None:
    with pytest.raises(PortfolioInputError, match="Zero slippage"):
        ExecutionCostConfig(0.00001, 0.0, 0.00001)
    with pytest.raises(PortfolioInputError, match="outside the frozen universe"):
        compute_currency_exposures({"EURCAD": 0.1})
    invalid_signals = _signals()
    invalid_signals["EURUSD"] = 1.1
    with pytest.raises(PortfolioInputError, match=r"\[-1, 1\]"):
        construct_target_weights(invalid_signals, _risk())
