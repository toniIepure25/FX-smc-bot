"""Canonical V2 execution kernel.

Rather than fork the execution semantics, V2 reuses the *certified* side-correct event
state machine established and unit-tested in the A0R3D gate. That engine is the single
canonical implementation of the frozen execution contract:

* side-correct entry (long->ask, short->bid) and exit (long->bid, short->ask);
* minimum one completed M1 bar of signal latency;
* adverse-first same-bar stop/target ambiguity;
* intraday-only positions with rollover entry exclusion from 16:30 America/New_York,
  mandatory flat from 16:45, and new-entry resume at 17:30;
* actual bid/ask spread paid inside fills, plus a 0.10 bps commission/slippage per fill;
* 1.5x and 2.0x cost-stress overlays;
* missing quotes never create a synthetic fill.

V2 pins this behaviour with golden tests (see ``tests/test_gate_a0r4``) so any future
drift in the inherited engine is caught immediately.
"""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import (
    compact_execution_window as _compact_execution_window,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    daily_metrics as _daily_metrics,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    simulate_state_machine as _simulate_state_machine,
)
from fx_smc_bot.research.v2.spec import StrategySpec

STRESS_MULTIPLIERS: tuple[float, ...] = (1.0, 1.5, 2.0)


def spec_to_exec_cfg(spec: StrategySpec) -> dict[str, Any]:
    """Translate a StrategySpec's execution surface into the kernel config dict."""

    exe = spec.execution
    return {
        "holding_horizon": int(exe.holding_bars),
        "exit_rule": exe.exit_rule.value,
        "stop_rule": "none" if exe.stop_rule.value == "none" else exe.stop_rule.value,
        "stop_bps": float(exe.stop_bps),
        "target_bps": float(exe.target_bps),
    }


def compact_execution_window(
    frame: pd.DataFrame, signal: pd.Series, *, horizon: int
) -> tuple[pd.DataFrame, pd.Series]:
    """Reduce a frame to the bars needed around each non-zero signal (deterministic)."""

    return _compact_execution_window(frame, signal, horizon=horizon)


def simulate(
    frame: pd.DataFrame,
    signal: pd.Series,
    cfg: dict[str, Any],
    *,
    cost_multiplier: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Run the canonical side-correct event state machine at a cost multiplier."""

    return _simulate_state_machine(frame, signal, cfg, cost_multiplier=cost_multiplier)


def daily_metrics(daily: pd.DataFrame, trades: list[dict[str, Any]]) -> dict[str, float | int]:
    return _daily_metrics(daily, trades)


def evaluate(
    frame: pd.DataFrame,
    signal: pd.Series,
    spec: StrategySpec,
) -> dict[str, Any]:
    """Evaluate a signal through the kernel at base + stress cost multipliers.

    Returns per-multiplier daily metrics plus the base daily net-bps series (indexed by
    NY exit date) used by the statistical layer. This function does not decide anything;
    it only executes the frozen contract.
    """

    cfg = spec_to_exec_cfg(spec)
    horizon = int(cfg["holding_horizon"])
    exec_frame, exec_signal = compact_execution_window(frame, signal, horizon=horizon)
    out: dict[str, Any] = {"by_multiplier": {}}
    base_daily: pd.DataFrame | None = None
    for mult in STRESS_MULTIPLIERS:
        daily, trades = simulate(exec_frame, exec_signal, cfg, cost_multiplier=mult)
        out["by_multiplier"][f"{mult:.1f}x"] = daily_metrics(daily, trades)
        if mult == 1.0:
            base_daily = daily
    if base_daily is not None and len(base_daily):
        series = base_daily.set_index("date")["net_bps"]
    else:
        series = pd.Series(dtype=float)
    out["base_daily_net_bps"] = series
    return out
