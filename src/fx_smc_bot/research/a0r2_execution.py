"""Synthetic-only A0R2 side-correct execution accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    commission: float = 0.0
    slippage: float = 0.0
    stress_1: float = 0.0
    stress_2: float = 0.0


def _rollover_mask(timestamp: pd.Series) -> pd.Series:
    eastern = pd.to_datetime(timestamp, utc=True).dt.tz_convert("America/New_York")
    local_time = eastern.dt.time
    return (local_time >= time(16, 30)) & (local_time <= time(17, 30))


def execute_side_correct(
    bars: pd.DataFrame,
    signal: pd.Series,
    *,
    costs: ExecutionCosts,
) -> pd.DataFrame:
    """Apply one-bar latency, bid/ask execution, costs and rollover flattening."""
    required = {"timestamp", "bid_close", "ask_close"}
    if not required <= set(bars.columns):
        raise ValueError("A0R2_EXECUTION_INPUT_COLUMNS_MISSING")
    out = bars[["timestamp", "bid_close", "ask_close"]].copy()
    out["requested_signal"] = signal.reindex(out.index).fillna(0).astype(int)
    out["position"] = out["requested_signal"].shift(1).fillna(0).astype(int)
    out.loc[_rollover_mask(out["timestamp"]), "position"] = 0
    previous_position = out["position"].shift(1).fillna(0).astype(int)
    out["entry_price"] = 0.0
    out.loc[out["position"] > previous_position, "entry_price"] = out["ask_close"]
    out.loc[out["position"] < previous_position, "entry_price"] = out["bid_close"]
    mid = (out["bid_close"] + out["ask_close"]) / 2.0
    gross = previous_position * mid.diff().fillna(0.0)
    turnover = (out["position"] - previous_position).abs()
    spread_cost = turnover * (out["ask_close"] - out["bid_close"]) / 2.0
    fixed_cost = turnover * (costs.commission + costs.slippage + costs.stress_1 + costs.stress_2)
    out["gross_return"] = gross
    out["net_return"] = gross - spread_cost - fixed_cost
    out["mandatory_rollover_flat"] = _rollover_mask(out["timestamp"])
    out["synthetic_fill_used"] = False
    return out
