from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fx_smc_bot.config import FillPolicy, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    PositionState,
)
from fx_smc_bot.execution.fills import BidAskFillEngine
from fx_smc_bot.execution.slippage import ZeroSlippage
from fx_smc_bot.research.strategy_alpha import (
    aggregate_contains_row_level_fields,
    assert_historical_window,
    assert_no_sealed_holdout_path,
    deterministic_replay_hash,
    evaluate_candidates_aggregate_only,
    load_candidate_specs,
)

REPO = Path(__file__).resolve().parents[2]


def test_holdout_path_guard_blocks_sealed_years_and_holdout_names() -> None:
    with pytest.raises(ValueError, match="sealed holdout"):
        assert_no_sealed_holdout_path("data/real/USDJPY/2023/M1.parquet")
    with pytest.raises(ValueError, match="sealed holdout"):
        assert_no_sealed_holdout_path("results/holdout/outcomes.json")

    assert_no_sealed_holdout_path("configs/research/intraday_smc/sweep_reversal.yaml")


def test_historical_window_guard_blocks_holdout_overlap() -> None:
    assert_historical_window("2015-01-01", "2022-12-31")

    with pytest.raises(ValueError, match="Access DENIED"):
        assert_historical_window("2022-12-01", "2023-01-02")


def test_candidate_universe_is_exact_and_hashes_are_deterministic() -> None:
    candidates = load_candidate_specs(REPO)

    assert [candidate.candidate_id for candidate in candidates] == [
        "SMC_A_SWEEP_REVERSAL_V1",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1",
        "SMC_C_LONDON_OPENING_RANGE_V1",
        "SMC_C_NEWYORK_OPENING_RANGE_V1",
    ]
    assert all(len(candidate.config_raw_hash) == 64 for candidate in candidates)
    assert all(len(candidate.config_canonical_hash) == 64 for candidate in candidates)


def test_bidask_limit_orders_use_executable_side_after_creation() -> None:
    engine = BidAskFillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)
    long_order = Order(
        pair=TradingPair.EURUSD,
        direction=Direction.LONG,
        order_type=OrderType.LIMIT,
        state=OrderState.PENDING,
        requested_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        units=10_000,
        created_at=datetime(2026, 1, 2, 10, 0),
    )

    no_fill = engine.process_pending_orders(
        [long_order],
        1.0990,
        1.1010,
        1.0980,
        1.1000,
        1.1010,
        1.1020,
        1.1005,
        1.1015,
        datetime(2026, 1, 2, 10, 5),
    )
    assert no_fill == []

    fills = engine.process_pending_orders(
        [long_order],
        1.0990,
        1.1010,
        1.0980,
        1.1000,
        1.1005,
        1.1010,
        1.0995,
        1.1000,
        datetime(2026, 1, 2, 10, 10),
    )
    assert len(fills) == 1
    assert fills[0][1].fill_price == 1.1000


def test_bidask_same_bar_conflict_is_adverse_first() -> None:
    engine = BidAskFillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)
    position = Position(
        pair=TradingPair.EURUSD,
        direction=Direction.LONG,
        state=PositionState.OPEN,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        units=10_000,
        opened_at=datetime(2026, 1, 2, 10, 0),
    )

    fill = engine.check_exit_conditions_bidask(
        position,
        bid_high=1.1110,
        bid_low=1.0940,
        ask_high=1.1120,
        ask_low=1.0950,
        bar_time=datetime(2026, 1, 2, 10, 5),
    )

    assert fill is not None
    assert fill.reason == FillReason.STOP_LOSS_HIT


def test_aggregate_outputs_do_not_contain_row_level_trade_fields() -> None:
    candidates = load_candidate_specs(REPO)
    evaluation = evaluate_candidates_aggregate_only(candidates)

    assert not aggregate_contains_row_level_fields(evaluation)
    assert all(
        result["trade_count"] == 0
        for candidate_results in evaluation["results"].values()
        for result in candidate_results
    )


def test_deterministic_replay_hash_is_stable() -> None:
    payload = {"candidate_count": 4, "trade_count": 0, "seed": 1729}

    assert deterministic_replay_hash(payload) == deterministic_replay_hash(payload)
