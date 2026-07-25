"""Placebo and baseline generators for strategy evaluation.

Implements null/placebo strategies that serve as controls to determine
whether SMC-specific elements (MSS, FVG, liquidity sweep) add
incremental value beyond simple session/momentum effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class PlaceboTrade:
    """A synthetic trade from a placebo/baseline strategy."""

    direction: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    pnl: float
    holding_bars: int
    timestamp: datetime | None = None


def random_direction_matched(
    timestamps: NDArray[np.datetime64],
    signal_bars: list[int],
    close: NDArray[np.float64],
    holding_bars: int = 20,
    seed: int = 42,
) -> list[PlaceboTrade]:
    """Random-direction entries at matched signal timestamps.

    Uses the same entry bars as the real strategy but randomizes direction.
    """
    rng = np.random.default_rng(seed)
    n = len(close)
    trades: list[PlaceboTrade] = []

    for bar_idx in signal_bars:
        if bar_idx + 1 >= n:
            continue
        direction = "long" if rng.random() < 0.5 else "short"
        entry_price = float(close[bar_idx + 1]) if bar_idx + 1 < n else float(close[bar_idx])
        exit_bar = min(bar_idx + holding_bars, n - 1)
        exit_price = float(close[exit_bar])

        if direction == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price

        ts = (
            timestamps[bar_idx].astype("datetime64[us]").astype(datetime)
            if bar_idx < len(timestamps)
            else None
        )
        trades.append(
            PlaceboTrade(
                direction=direction,
                entry_bar=bar_idx + 1,
                exit_bar=exit_bar,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                holding_bars=exit_bar - bar_idx - 1,
                timestamp=ts,
            )
        )

    return trades


def random_time_matched(
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    n_trades: int,
    holding_bars: int = 20,
    session_mask: NDArray[np.bool_] | None = None,
    seed: int = 42,
) -> list[PlaceboTrade]:
    """Random-time entries matched for session and holding period."""
    rng = np.random.default_rng(seed)
    n = len(close)
    if n <= holding_bars:
        return []

    if session_mask is not None:
        valid_bars = np.where(session_mask)[0]
        valid_bars = valid_bars[valid_bars < n - holding_bars]
    else:
        valid_bars = np.arange(0, n - holding_bars)

    if len(valid_bars) == 0:
        return []

    trades: list[PlaceboTrade] = []
    entries = rng.choice(valid_bars, size=min(n_trades, len(valid_bars)), replace=False)
    entries.sort()

    for bar_idx in entries:
        direction = "long" if rng.random() < 0.5 else "short"
        entry_price = float(close[bar_idx + 1])
        exit_bar = bar_idx + holding_bars
        exit_price = float(close[exit_bar])

        if direction == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price

        ts = (
            timestamps[bar_idx].astype("datetime64[us]").astype(datetime)
            if bar_idx < len(timestamps)
            else None
        )
        trades.append(
            PlaceboTrade(
                direction=direction,
                entry_bar=bar_idx + 1,
                exit_bar=exit_bar,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                holding_bars=holding_bars,
                timestamp=ts,
            )
        )

    return trades


def signal_inversion(
    signal_bars: list[int],
    signal_directions: list[str],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    holding_bars: int = 20,
) -> list[PlaceboTrade]:
    """Invert signal direction at matched timestamps."""
    n = len(close)
    trades: list[PlaceboTrade] = []

    for bar_idx, orig_dir in zip(signal_bars, signal_directions, strict=False):
        if bar_idx + 1 >= n:
            continue
        direction = "short" if orig_dir == "long" else "long"
        entry_price = float(close[bar_idx + 1])
        exit_bar = min(bar_idx + holding_bars, n - 1)
        exit_price = float(close[exit_bar])

        if direction == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price

        ts = (
            timestamps[bar_idx].astype("datetime64[us]").astype(datetime)
            if bar_idx < len(timestamps)
            else None
        )
        trades.append(PlaceboTrade(
            direction=direction,
            entry_bar=bar_idx + 1,
            exit_bar=exit_bar,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl, holding_bars=exit_bar - bar_idx - 1, timestamp=ts,
        ))

    return trades


def simple_momentum_baseline(
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    lookback: int = 20,
    holding_bars: int = 20,
    session_mask: NDArray[np.bool_] | None = None,
) -> list[PlaceboTrade]:
    """Simple momentum baseline: go long if price is above N-bar ago, short otherwise."""
    n = len(close)
    trades: list[PlaceboTrade] = []

    for i in range(lookback, n - holding_bars, holding_bars):
        if session_mask is not None and not session_mask[i]:
            continue

        direction = "long" if close[i] > close[i - lookback] else "short"
        entry_price = float(close[i + 1])
        exit_bar = i + holding_bars
        exit_price = float(close[exit_bar])

        if direction == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price

        ts = timestamps[i].astype("datetime64[us]").astype(datetime)
        trades.append(PlaceboTrade(
            direction=direction, entry_bar=i + 1, exit_bar=exit_bar,
            entry_price=entry_price, exit_price=exit_price,
            pnl=pnl, holding_bars=holding_bars, timestamp=ts,
        ))

    return trades


@dataclass(slots=True)
class AblationSpec:
    """Specification of one ablation variant."""

    name: str
    description: str
    config_overrides: dict


CANONICAL_ABLATIONS: list[AblationSpec] = [
    AblationSpec("full", "Full canonical model", {}),
    AblationSpec("no_session_filter", "Without session filter", {"session_filter": False}),
    AblationSpec("no_htf_filter", "Without HTF bias filter", {"htf_filter": False}),
    AblationSpec(
        "no_displacement",
        "Without displacement requirement",
        {"displacement_body_ratio": 0.0, "displacement_tr_ratio": 0.0},
    ),
    AblationSpec("no_mss", "Without MSS requirement", {"require_mss": False}),
    AblationSpec("no_fvg", "Without FVG requirement", {"require_fvg": False}),
    AblationSpec(
        "no_liquidity_type",
        "Without liquidity classification",
        {"eligible_level_types": ["equal_highs", "equal_lows"]},
    ),
    AblationSpec("fixed_stop", "Fixed pip stop (no ATR normalization)", {"fixed_stop_pips": 20.0}),
    AblationSpec(
        "opposing_liq_target",
        "Target at opposing liquidity",
        {"target_mode": "opposing_liquidity"},
    ),
    AblationSpec("cost_1_5x", "1.5x realistic costs", {"cost_multiplier": 1.5}),
    AblationSpec("cost_2x", "2x realistic costs", {"cost_multiplier": 2.0}),
    AblationSpec("cost_3x", "3x realistic costs", {"cost_multiplier": 3.0}),
    AblationSpec("conservative_fill", "Conservative fill policy", {"fill_policy": "conservative"}),
    AblationSpec("news_filter_on", "With news filter", {"news_filter": True}),
    AblationSpec("news_filter_off", "Without news filter", {"news_filter": False}),
]


def generate_ablation_matrix(
    strategy_name: str,
    pairs: list[str],
    sessions: list[str],
    custom_ablations: list[AblationSpec] | None = None,
) -> list[dict]:
    """Generate the full ablation experiment matrix."""
    ablations = list(CANONICAL_ABLATIONS)
    if custom_ablations:
        ablations.extend(custom_ablations)

    matrix: list[dict] = []
    for ablation in ablations:
        for pair in pairs:
            for session in sessions:
                matrix.append({
                    "strategy": strategy_name,
                    "ablation": ablation.name,
                    "description": ablation.description,
                    "pair": pair,
                    "session": session,
                    "config_overrides": ablation.config_overrides,
                })
    return matrix
