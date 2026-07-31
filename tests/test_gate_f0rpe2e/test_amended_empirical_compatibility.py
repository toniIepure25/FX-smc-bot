from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from fx_smc_bot.research import classical_fx_data as market_data
from fx_smc_bot.research.classical_fx_f0rp import (
    AMENDED_CURRENCY_ORDER,
    AMENDED_INSTRUMENT_ORDER,
)
from fx_smc_bot.research.classical_fx_portfolio import (
    CURRENCIES,
    INSTRUMENTS,
    ClassicalFxPortfolioEngine,
    MarketQuote,
    PortfolioUniverse,
    RiskEstimate,
)

AMENDED_UNIVERSE = PortfolioUniverse(
    instruments=AMENDED_INSTRUMENT_ORDER,
    currencies=AMENDED_CURRENCY_ORDER,
)


def _risk(instruments: tuple[str, ...]) -> RiskEstimate:
    covariance = np.eye(len(instruments), dtype=float) * 0.0001
    return RiskEstimate(
        decision_time=pd.Timestamp("2016-12-30"),
        information_end=pd.Timestamp("2016-12-29"),
        annualized_instrument_volatility=pd.Series(0.10, index=instruments, dtype=float),
        daily_covariance=pd.DataFrame(covariance, index=instruments, columns=instruments),
        volatility_observations=60,
        covariance_observations=252,
    )


def test_amended_market_plan_and_authorizations_are_exact_subsets(tmp_path: Path) -> None:
    plan = market_data.development_plan(instruments=AMENDED_INSTRUMENT_ORDER)

    assert plan["instruments"] == list(AMENDED_INSTRUMENT_ORDER)
    assert plan["partition_tasks"] == 1_512
    assert plan["pair_months"] == 756
    assert {task["instrument"] for task in plan["tasks"]} == set(AMENDED_INSTRUMENT_ORDER)
    assert all("NZD" not in task["partition_id"] for task in plan["tasks"])
    market_data.verify_development_plan(plan)

    clean_root = tmp_path / "clean"
    repository_root = tmp_path / "repo"
    clean_root.mkdir()
    repository_root.mkdir()
    bundle = market_data.development_authorizations(
        clean_root,
        repository_root,
        instruments=AMENDED_INSTRUMENT_ORDER,
    )
    assert bundle.provider.authorized_instruments == frozenset(AMENDED_INSTRUMENT_ORDER)
    assert bundle.provider.authorized_currencies == frozenset(AMENDED_CURRENCY_ORDER)
    assert len(bundle.provider.authorized_partition_set) == 1_512
    assert "NZDUSD" not in bundle.provider.authorized_instruments
    assert "NZD" not in bundle.provider.authorized_currencies


def test_amended_acquisition_schedules_no_unauthorized_provider_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    requested: list[str] = []
    fake_authorizations = SimpleNamespace(
        provider=SimpleNamespace(clean_room_root=tmp_path / "clean")
    )

    monkeypatch.setattr(
        market_data,
        "development_authorizations",
        lambda *args, **kwargs: fake_authorizations,
    )
    monkeypatch.setattr(market_data, "require_storage_reserve", lambda *args: {})

    def record_partition(repository_root, authorizations, partition, runner, usage_probe):
        requested.append(partition.instrument)
        return {"status": "F0_RAW_COMPLETE"}

    monkeypatch.setattr(market_data, "_acquire_partition", record_partition)
    result = market_data.acquire_development_market(
        tmp_path / "clean",
        tmp_path / "repo",
        execute_provider=True,
        instruments=AMENDED_INSTRUMENT_ORDER,
    )

    assert result["status"] == "F0_RAW_COMPLETE"
    assert result["planned_partitions"] == result["completed_partitions"] == 1_512
    assert set(requested) == set(AMENDED_INSTRUMENT_ORDER)
    assert len(requested) == 1_512
    assert "NZDUSD" not in requested


def test_amended_portfolio_engine_requires_only_nine_pairs_and_seven_rates() -> None:
    instruments = AMENDED_UNIVERSE.instruments
    currencies = AMENDED_UNIVERSE.currencies
    engine = ClassicalFxPortfolioEngine(universe=AMENDED_UNIVERSE)
    signals = dict.fromkeys(instruments, 0.0)
    signals["EURUSD"] = 1.0
    positions = dict.fromkeys(instruments, 0.0)
    quotes = {name: MarketQuote(0.9999, 1.0001) for name in instruments}
    rates = dict.fromkeys(currencies, 0.02)

    result = engine.rebalance(
        decision_time=datetime(2016, 12, 29, 22, 5, tzinfo=UTC),
        signals=signals,
        current_positions=positions,
        quotes=quotes,
        published_rates=rates,
        risk=_risk(instruments),
    )

    assert result.action == "REBALANCED"
    assert tuple(result.positions_after) == instruments
    assert tuple(result.currency_exposures) == currencies
    assert "NZDUSD" not in result.positions_after
    assert "NZD" not in result.currency_exposures
    assert not any("NZD" in reason for reason in result.reasons)
    assert result.position_reconciliation_residual == 0.0
    assert result.currency_leg_reconciliation_residual == 0.0


def test_legacy_defaults_are_unchanged() -> None:
    assert market_data.development_plan()["partition_tasks"] == 1_680
    assert market_data.development_plan()["pair_months"] == 840
    assert tuple(market_data.development_plan()["instruments"]) == INSTRUMENTS
    assert ClassicalFxPortfolioEngine().universe.instruments == INSTRUMENTS
    assert ClassicalFxPortfolioEngine().universe.currencies == CURRENCIES
