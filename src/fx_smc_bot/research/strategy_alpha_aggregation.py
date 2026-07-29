"""Gate P0-R aggregate-only result helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from fx_smc_bot.research.strategy_alpha import canonical_json_sha256

ROW_LEVEL_FORBIDDEN_KEYS = {
    "signal_id",
    "order_id",
    "trade_id",
    "timestamp",
    "entry_timestamp",
    "exit_timestamp",
    "entry_price",
    "exit_price",
    "individual_pnl",
    "pnl",
}


@dataclass(frozen=True, slots=True)
class AggregateResult:
    candidate_id: str
    window: str
    label: str
    execution_status: str
    trade_count: int
    gross_expectancy_r: float
    net_expectancy_r: float
    day_cluster_ci: tuple[float, float] | None
    profit_factor: float | None
    sharpe: float | None
    probabilistic_sharpe: float | None
    deflated_sharpe: float | None
    max_drawdown_r: float | None
    cost_drag_r: float | None
    stress_1_5x_net_expectancy_r: float | None
    stress_2_0x_net_expectancy_r: float | None
    risk_0_25_pct_return: float | None
    risk_0_50_pct_return: float | None
    matched_benchmark_alpha: float | None
    unadjusted_p_value: float | None
    holm_adjusted_p_value: float | None
    reason: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def blocked_aggregate_result(candidate_id: str, window: str) -> AggregateResult:
    return AggregateResult(
        candidate_id=candidate_id,
        window=window,
        label="EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY",
        execution_status="NOT_EXECUTED_INCOMPLETE_PERMITTED_DATA_COVERAGE",
        trade_count=0,
        gross_expectancy_r=0.0,
        net_expectancy_r=0.0,
        day_cluster_ci=None,
        profit_factor=None,
        sharpe=None,
        probabilistic_sharpe=None,
        deflated_sharpe=None,
        max_drawdown_r=None,
        cost_drag_r=None,
        stress_1_5x_net_expectancy_r=None,
        stress_2_0x_net_expectancy_r=None,
        risk_0_25_pct_return=None,
        risk_0_50_pct_return=None,
        matched_benchmark_alpha=None,
        unadjusted_p_value=None,
        holm_adjusted_p_value=None,
        reason="Candidate lacks full permitted historical bid/ask coverage certification.",
    )


def contains_forbidden_row_level_keys(payload: Any) -> bool:
    if isinstance(payload, dict):
        keys = {str(key).lower() for key in payload}
        if keys & ROW_LEVEL_FORBIDDEN_KEYS:
            return True
        return any(contains_forbidden_row_level_keys(value) for value in payload.values())
    if isinstance(payload, list):
        return any(contains_forbidden_row_level_keys(item) for item in payload)
    return False


def aggregate_schema_hash(payload: Any) -> str:
    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): shape(child) for key, child in sorted(value.items())}
        if isinstance(value, list):
            return [shape(value[0])] if value else []
        return type(value).__name__

    return canonical_json_sha256(shape(payload))


def aggregate_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return canonical_json_sha256(json.loads(encoded))
