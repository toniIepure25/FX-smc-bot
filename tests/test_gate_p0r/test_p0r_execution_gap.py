from __future__ import annotations

from pathlib import Path

from fx_smc_bot.research.strategy_alpha import HISTORICAL_WINDOWS, load_candidate_specs
from fx_smc_bot.research.strategy_alpha_aggregation import (
    blocked_aggregate_result,
    contains_forbidden_row_level_keys,
)
from fx_smc_bot.research.strategy_alpha_execution import (
    candidate_coverage_classification,
    permitted_coverage_records,
    zero_trade_funnels,
)

REPO = Path(__file__).resolve().parents[2]


def test_zero_trade_funnels_explain_no_executable_sample() -> None:
    candidates = load_candidate_specs(REPO)
    funnels = zero_trade_funnels(candidates)

    assert len(funnels) == 4
    assert all(funnel.trades_accepted_into_aggregate_sample == 0 for funnel in funnels)
    assert all("missing_data" in funnel.rejection_counts for funnel in funnels)
    assert all("DATA_PRESENT_NOT_CERTIFIED" in funnel.root_causes for funnel in funnels)


def test_permitted_coverage_does_not_mark_any_candidate_fully_covered() -> None:
    candidates = load_candidate_specs(REPO)
    records = permitted_coverage_records(candidates)
    classifications = candidate_coverage_classification(records)

    assert len(records) == len(candidates) * 3 * len(HISTORICAL_WINDOWS)
    assert set(classifications) == {candidate.candidate_id for candidate in candidates}
    assert "FULLY_COVERED" not in classifications.values()


def test_blocked_aggregate_result_is_not_row_level() -> None:
    record = blocked_aggregate_result("SMC_A_SWEEP_REVERSAL_V1", "combined").to_record()

    assert record["trade_count"] == 0
    assert record["execution_status"] == "NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE"
    assert not contains_forbidden_row_level_keys(record)


def test_row_level_keys_are_rejected() -> None:
    payload = {"candidate_id": "x", "trades": [{"trade_id": "t1", "entry_price": 1.0}]}

    assert contains_forbidden_row_level_keys(payload)
