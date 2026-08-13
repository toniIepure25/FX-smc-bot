"""Vectorised-preprocessing fast path for the certified V2 execution kernel.

The certified engine (``a0r3d_certified_subset.simulate_state_machine``) iterates with
``DataFrame.iterrows`` and per-row timezone conversion. That is fine for the sparse
compacted windows it was designed for, but intractable for dense signals over ~1.08M M1
bars across 2015-2017. This module preserves the *exact* control flow and arithmetic of
the certified engine while removing the pandas per-row overhead: all OHLC, the NY
minute-of-day, the NY date and the UTC timestamps are precomputed as arrays and the loop
uses numpy scalar indexing only.

This is a pure engineering-performance optimisation, not a semantic change. Its output is
pinned bit-for-bit to the certified engine by ``tests/test_gate_a0r4/test_fastexec_equivalence.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import (
    BASE_COMMISSION_SLIPPAGE_BPS_PER_FILL as _BASE_CS,
)
from fx_smc_bot.research.a0r3d_certified_subset import NY

_NO_ENTRY_LO, _NO_ENTRY_HI = 16 * 60 + 30, 17 * 60 + 30      # 16:30 <= m < 17:30
_FLAT_LO, _FLAT_HI = 16 * 60 + 45, 17 * 60 + 30              # 16:45 <= m < 17:30


def _prep(frame: pd.DataFrame) -> dict[str, Any]:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    ny = ts.dt.tz_convert(NY)
    return {
        "bo": frame["bid_open"].to_numpy(dtype=float),
        "bh": frame["bid_high"].to_numpy(dtype=float),
        "bl": frame["bid_low"].to_numpy(dtype=float),
        "bc": frame["bid_close"].to_numpy(dtype=float),
        "ao": frame["ask_open"].to_numpy(dtype=float),
        "ah": frame["ask_high"].to_numpy(dtype=float),
        "al": frame["ask_low"].to_numpy(dtype=float),
        "ac": frame["ask_close"].to_numpy(dtype=float),
        "ny_min": (ny.dt.hour * 60 + ny.dt.minute).to_numpy(dtype=int),
        "ny_date": ny.dt.strftime("%Y-%m-%d").to_numpy(),
        "ts_index": pd.DatetimeIndex(ts),
    }


def _spread_bps(ac: float, bc: float) -> float:
    mid = (ac + bc) / 2.0
    if mid <= 0:
        return 0.0
    return (ac - bc) / mid * 10_000.0


def simulate_fast(
    frame: pd.DataFrame,
    signal: pd.Series,
    config: dict[str, Any],
    *,
    cost_multiplier: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Bit-for-bit equivalent of the certified simulate_state_machine, but fast."""

    n = len(frame)
    if n == 0:
        empty = pd.DataFrame(columns=["date", "gross_bps", "cost_bps", "net_bps", "turnover"])
        return empty, []

    a = _prep(frame)
    bo, bh, bl, bc = a["bo"], a["bh"], a["bl"], a["bc"]
    ao, ah, al, ac = a["ao"], a["ah"], a["al"], a["ac"]
    ny_min, ny_date, ts_index = a["ny_min"], a["ny_date"], a["ts_index"]
    sig = signal.to_numpy(dtype=int)

    holding = int(config.get("holding_horizon") or 1)
    stop_rule = str(config.get("stop_rule") or "none")
    exit_rule = str(config.get("exit_rule") or "time_exit")
    target_bps = float(config.get("target_bps", 0.0) or 0.0)
    stop_bps = float(config.get("stop_bps", 0.0) or 0.0)

    g_arr = np.zeros(n, dtype=float)
    c_arr = np.zeros(n, dtype=float)
    t_arr = np.zeros(n, dtype=float)

    trades: list[dict[str, Any]] = []
    pending = 0
    has_pos = False
    p_side = 0
    p_entry = 0.0
    p_idx = 0
    p_spread = 0.0
    p_ts = 0

    for i in range(n):
        m = ny_min[i]
        flat = _FLAT_LO <= m < _FLAT_HI
        no_entry = _NO_ENTRY_LO <= m < _NO_ENTRY_HI
        gross = 0.0
        cost = 0.0
        turn = 0.0

        if has_pos:
            should_exit = False
            event = "horizon"
            exit_reason = ""
            bars_held = i - p_idx
            if flat:
                should_exit = True
                event = "flat"
                exit_reason = "mandatory_flat"
            elif exit_rule == "time_exit" and bars_held >= holding:
                should_exit = True
                event = "horizon"
                exit_reason = "horizon"
            elif exit_rule == "opposite_signal" and pending == -p_side:
                should_exit = True
                event = "flip"
                exit_reason = "opposite_signal"

            target_hit = False
            stop_hit = False
            if target_bps > 0:
                if p_side > 0:
                    target_hit = bh[i] >= p_entry * (1.0 + target_bps / 10_000.0)
                else:
                    target_hit = al[i] <= p_entry * (1.0 - target_bps / 10_000.0)
            if stop_rule != "none" and stop_bps > 0:
                if p_side > 0:
                    stop_hit = bl[i] <= p_entry * (1.0 - stop_bps / 10_000.0)
                else:
                    stop_hit = ah[i] >= p_entry * (1.0 + stop_bps / 10_000.0)
            if target_hit or stop_hit:
                should_exit = True
                event = "stop" if stop_hit else "target"
                exit_reason = "same_bar_adverse_stop" if stop_hit and target_hit else event

            if should_exit:
                exit_price = _fill(bo, bh, bl, ao, ah, al, i, p_side, event)
                gross = _ret_bps(p_side, p_entry, exit_price)
                exit_spread = _spread_bps(ac[i], bc[i])
                cost = (
                    max(cost_multiplier - 1.0, 0.0) * (p_spread + exit_spread) / 2.0
                    + cost_multiplier * _BASE_CS * 2.0
                )
                turn = 2.0
                trades.append({
                    "entry_timestamp": ts_index[p_ts].isoformat(),
                    "exit_timestamp": ts_index[i].isoformat(),
                    "side": "long" if p_side > 0 else "short",
                    "exit_reason": exit_reason,
                    "gross_bps": round(gross, 9),
                    "cost_bps": round(cost, 9),
                    "net_bps": round(gross - cost, 9),
                })
                has_pos = False

        if (not has_pos) and pending and not no_entry:
            side = int(pending)
            p_entry = ao[i] if side > 0 else bo[i]
            p_side = side
            p_idx = i
            p_spread = _spread_bps(ac[i], bc[i])
            p_ts = i
            has_pos = True
            turn += 1.0

        g_arr[i] = gross
        c_arr[i] = cost
        t_arr[i] = turn
        pending = int(sig[i])

    if has_pos:
        j = n - 1
        exit_price = bo[j] if p_side > 0 else ao[j]
        gross = _ret_bps(p_side, p_entry, exit_price)
        exit_spread = _spread_bps(ac[j], bc[j])
        cost = (
            max(cost_multiplier - 1.0, 0.0) * (p_spread + exit_spread) / 2.0
            + cost_multiplier * _BASE_CS * 2.0
        )
        trades.append({
            "entry_timestamp": ts_index[p_ts].isoformat(),
            "exit_timestamp": ts_index[j].isoformat(),
            "side": "long" if p_side > 0 else "short",
            "exit_reason": "delayed_valid_exit_at_dataset_end",
            "gross_bps": round(gross, 9),
            "cost_bps": round(cost, 9),
            "net_bps": round(gross - cost, 9),
        })
        # append an extra daily component row at the last bar (matches certified engine)
        extra = pd.DataFrame({
            "date": [ny_date[j]], "gross_bps": [gross], "cost_bps": [cost],
            "net_bps": [gross - cost], "turnover": [2.0],
        })
    else:
        extra = None

    comp = pd.DataFrame({
        "date": ny_date, "gross_bps": g_arr, "cost_bps": c_arr,
        "net_bps": g_arr - c_arr, "turnover": t_arr,
    })
    if extra is not None:
        comp = pd.concat([comp, extra], ignore_index=True)
    daily = comp.groupby("date", as_index=False).agg(
        gross_bps=("gross_bps", "sum"),
        cost_bps=("cost_bps", "sum"),
        net_bps=("net_bps", "sum"),
        turnover=("turnover", "sum"),
    )
    return daily, trades


def simulate_multi(
    frame: pd.DataFrame,
    signal: pd.Series,
    config: dict[str, Any],
    *,
    cost_multipliers: tuple[float, ...] = (1.0, 1.5, 2.0),
) -> dict[float, tuple[pd.DataFrame, list[dict[str, Any]]]]:
    """Run the event loop ONCE and derive every cost scenario analytically.

    The entry/exit schedule and gross returns are independent of the cost multiplier
    (which only enters ``_round_trip_cost_bps``), so this returns results identical to
    calling :func:`simulate_fast` once per multiplier, at ~1/len(multipliers) the cost.
    """

    n = len(frame)
    if n == 0:
        empty = pd.DataFrame(columns=["date", "gross_bps", "cost_bps", "net_bps", "turnover"])
        return {m: (empty.copy(), []) for m in cost_multipliers}

    a = _prep(frame)
    bo, bh, bl, bc = a["bo"], a["bh"], a["bl"], a["bc"]
    ao, ah, al, ac = a["ao"], a["ah"], a["al"], a["ac"]
    ny_min, ny_date, ts_index = a["ny_min"], a["ny_date"], a["ts_index"]
    sig = signal.to_numpy(dtype=int)

    holding = int(config.get("holding_horizon") or 1)
    stop_rule = str(config.get("stop_rule") or "none")
    exit_rule = str(config.get("exit_rule") or "time_exit")
    target_bps = float(config.get("target_bps", 0.0) or 0.0)
    stop_bps = float(config.get("stop_bps", 0.0) or 0.0)

    g_arr = np.zeros(n, dtype=float)      # gross bps at each bar (mult-independent)
    overlay = np.zeros(n, dtype=float)    # (entry_spread + exit_spread)/2 at each exit bar
    is_exit = np.zeros(n, dtype=float)    # 1.0 at each round-trip completion bar
    t_arr = np.zeros(n, dtype=float)

    # per-trade record: (entry_i, exit_i, side, reason, gross, entry_spread, exit_spread)
    trade_recs: list[tuple[int, int, int, str, float, float, float]] = []
    pending = 0
    has_pos = False
    p_side = 0
    p_entry = 0.0
    p_idx = 0
    p_spread = 0.0
    p_ts = 0

    for i in range(n):
        m = ny_min[i]
        flat = _FLAT_LO <= m < _FLAT_HI
        no_entry = _NO_ENTRY_LO <= m < _NO_ENTRY_HI
        turn = 0.0

        if has_pos:
            should_exit = False
            event = "horizon"
            exit_reason = ""
            bars_held = i - p_idx
            if flat:
                should_exit, event, exit_reason = True, "flat", "mandatory_flat"
            elif exit_rule == "time_exit" and bars_held >= holding:
                should_exit, event, exit_reason = True, "horizon", "horizon"
            elif exit_rule == "opposite_signal" and pending == -p_side:
                should_exit, event, exit_reason = True, "flip", "opposite_signal"

            target_hit = False
            stop_hit = False
            if target_bps > 0:
                if p_side > 0:
                    target_hit = bh[i] >= p_entry * (1.0 + target_bps / 10_000.0)
                else:
                    target_hit = al[i] <= p_entry * (1.0 - target_bps / 10_000.0)
            if stop_rule != "none" and stop_bps > 0:
                if p_side > 0:
                    stop_hit = bl[i] <= p_entry * (1.0 - stop_bps / 10_000.0)
                else:
                    stop_hit = ah[i] >= p_entry * (1.0 + stop_bps / 10_000.0)
            if target_hit or stop_hit:
                should_exit = True
                event = "stop" if stop_hit else "target"
                exit_reason = "same_bar_adverse_stop" if stop_hit and target_hit else event

            if should_exit:
                exit_price = _fill(bo, bh, bl, ao, ah, al, i, p_side, event)
                gross = _ret_bps(p_side, p_entry, exit_price)
                exit_spread = _spread_bps(ac[i], bc[i])
                g_arr[i] += gross
                overlay[i] += (p_spread + exit_spread) / 2.0
                is_exit[i] += 1.0
                t_arr[i] += 2.0
                trade_recs.append((p_ts, i, p_side, exit_reason, gross, p_spread, exit_spread))
                has_pos = False

        if (not has_pos) and pending and not no_entry:
            side = int(pending)
            p_entry = ao[i] if side > 0 else bo[i]
            p_side, p_idx, p_ts = side, i, i
            p_spread = _spread_bps(ac[i], bc[i])
            has_pos = True
            turn += 1.0

        t_arr[i] += turn
        pending = int(sig[i])

    tail = None
    if has_pos:
        j = n - 1
        exit_price = bo[j] if p_side > 0 else ao[j]
        gross = _ret_bps(p_side, p_entry, exit_price)
        exit_spread = _spread_bps(ac[j], bc[j])
        tail = (p_ts, j, p_side, "delayed_valid_exit_at_dataset_end", gross, p_spread, exit_spread)

    out: dict[float, tuple[pd.DataFrame, list[dict[str, Any]]]] = {}
    for mult in cost_multipliers:
        c_arr = np.maximum(mult - 1.0, 0.0) * overlay + is_exit * (mult * _BASE_CS * 2.0)
        comp = pd.DataFrame({
            "date": ny_date, "gross_bps": g_arr, "cost_bps": c_arr,
            "net_bps": g_arr - c_arr, "turnover": t_arr,
        })
        trades = [
            _trade_dict(ts_index, rec, mult) for rec in trade_recs
        ]
        if tail is not None:
            tg = tail[4]
            tc = max(mult - 1.0, 0.0) * (tail[5] + tail[6]) / 2.0 + mult * _BASE_CS * 2.0
            extra = pd.DataFrame({
                "date": [ny_date[tail[1]]], "gross_bps": [tg], "cost_bps": [tc],
                "net_bps": [tg - tc], "turnover": [2.0],
            })
            comp = pd.concat([comp, extra], ignore_index=True)
            trades = [*trades, _trade_dict(ts_index, tail, mult)]
        daily = comp.groupby("date", as_index=False).agg(
            gross_bps=("gross_bps", "sum"), cost_bps=("cost_bps", "sum"),
            net_bps=("net_bps", "sum"), turnover=("turnover", "sum"),
        )
        out[mult] = (daily, trades)
    return out


def _trade_dict(ts_index, rec, mult):  # type: ignore[no-untyped-def]
    entry_i, exit_i, side, reason, gross, es, xs = rec
    cost = max(mult - 1.0, 0.0) * (es + xs) / 2.0 + mult * _BASE_CS * 2.0
    return {
        "entry_timestamp": ts_index[entry_i].isoformat(),
        "exit_timestamp": ts_index[exit_i].isoformat(),
        "side": "long" if side > 0 else "short",
        "exit_reason": reason,
        "gross_bps": round(gross, 9),
        "cost_bps": round(cost, 9),
        "net_bps": round(gross - cost, 9),
    }


def _fill(bo, bh, bl, ao, ah, al, i, side, event):  # type: ignore[no-untyped-def]
    if event in ("entry", "flat", "horizon", "flip"):
        if side > 0:
            return float(ao[i] if event == "entry" else bo[i])
        return float(bo[i] if event == "entry" else ao[i])
    if event == "target":
        return float(bh[i] if side > 0 else al[i])
    if event == "stop":
        return float(bl[i] if side > 0 else ah[i])
    raise ValueError(f"unknown fill event {event}")


def _ret_bps(side: int, entry: float, exit_price: float) -> float:
    if side > 0:
        return (exit_price - entry) / entry * 10_000.0
    return (entry - exit_price) / entry * 10_000.0
