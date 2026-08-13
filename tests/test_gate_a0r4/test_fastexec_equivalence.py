"""Prove the fast execution path is bit-for-bit identical to the certified engine."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from fx_smc_bot.research.a0r3d_certified_subset import simulate_state_machine
from fx_smc_bot.research.v2.fastexec import simulate_fast, simulate_multi


def _random_frame(seed: int, n: int, jpy: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-03-01 00:00", periods=n, freq="1min", tz="UTC")
    base = 110.0 if jpy else 1.10
    tick = 0.01 if jpy else 0.0001
    mid = base + np.cumsum(rng.standard_normal(n) * 2 * tick)
    rng_bar = np.abs(rng.standard_normal(n)) * 2 * tick + tick
    mo = np.empty(n)
    mo[0] = mid[0]
    mo[1:] = mid[:-1]
    mh = np.maximum(mo, mid) + rng_bar
    ml = np.minimum(mo, mid) - rng_bar
    hs = (0.5 + np.abs(rng.standard_normal(n))) * tick
    return pd.DataFrame({
        "timestamp": idx,
        "bid_open": mo - hs, "bid_high": mh - hs, "bid_low": ml - hs, "bid_close": mid - hs,
        "ask_open": mo + hs, "ask_high": mh + hs, "ask_low": ml + hs, "ask_close": mid + hs,
    })


def _random_signal(seed: int, n: int) -> pd.Series:
    rng = np.random.default_rng(seed + 999)
    raw = rng.choice([-1, 0, 0, 1], size=n)
    return pd.Series(raw.astype(int))


_CFGS = [
    {"holding_horizon": 3, "exit_rule": "time_exit", "stop_rule": "none",
     "stop_bps": 0.0, "target_bps": 0.0},
    {"holding_horizon": 5, "exit_rule": "opposite_signal", "stop_rule": "none",
     "stop_bps": 0.0, "target_bps": 0.0},
    {"holding_horizon": 10, "exit_rule": "time_exit", "stop_rule": "fixed_bps",
     "stop_bps": 15.0, "target_bps": 20.0},
]


@pytest.mark.parametrize("seed", [1, 2, 3, 7])
@pytest.mark.parametrize("jpy", [False, True])
@pytest.mark.parametrize("cfg_idx", [0, 1, 2])
@pytest.mark.parametrize("mult", [1.0, 1.5, 2.0])
def test_fast_matches_certified(seed: int, jpy: bool, cfg_idx: int, mult: float) -> None:
    frame = _random_frame(seed, 2500, jpy)
    signal = _random_signal(seed, len(frame))
    cfg = _CFGS[cfg_idx]
    d_ref, t_ref = simulate_state_machine(frame, signal, cfg, cost_multiplier=mult)
    d_fast, t_fast = simulate_fast(frame, signal, cfg, cost_multiplier=mult)
    # daily frames identical (dates + numerics)
    assert list(d_ref["date"]) == list(d_fast["date"])
    for col in ("gross_bps", "cost_bps", "net_bps", "turnover"):
        assert np.allclose(d_ref[col].to_numpy(), d_fast[col].to_numpy(), atol=1e-9, rtol=0)
    # trades identical
    assert len(t_ref) == len(t_fast)
    for a, b in zip(t_ref, t_fast, strict=True):
        assert a["side"] == b["side"]
        assert a["exit_reason"] == b["exit_reason"]
        assert a["entry_timestamp"] == b["entry_timestamp"]
        assert a["exit_timestamp"] == b["exit_timestamp"]
        assert abs(a["net_bps"] - b["net_bps"]) < 1e-9


@pytest.mark.parametrize("seed", [1, 5])
@pytest.mark.parametrize("cfg_idx", [0, 1, 2])
def test_simulate_multi_matches_per_multiplier(seed: int, cfg_idx: int) -> None:
    frame = _random_frame(seed, 2500, seed % 2 == 0)
    signal = _random_signal(seed, len(frame))
    cfg = _CFGS[cfg_idx]
    multi = simulate_multi(frame, signal, cfg, cost_multipliers=(1.0, 1.5, 2.0))
    for mult in (1.0, 1.5, 2.0):
        d_ref, t_ref = simulate_fast(frame, signal, cfg, cost_multiplier=mult)
        d_m, t_m = multi[mult]
        assert list(d_ref["date"]) == list(d_m["date"])
        for col in ("gross_bps", "cost_bps", "net_bps", "turnover"):
            assert np.allclose(d_ref[col].to_numpy(), d_m[col].to_numpy(), atol=1e-9, rtol=0)
        assert len(t_ref) == len(t_m)
        for x, y in zip(t_ref, t_m, strict=True):
            assert x["exit_reason"] == y["exit_reason"]
            assert abs(x["net_bps"] - y["net_bps"]) < 1e-9


def test_fast_empty_frame() -> None:
    cols = ["timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
            "ask_open", "ask_high", "ask_low", "ask_close"]
    frame = pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    d, t = simulate_fast(frame, pd.Series([], dtype=int), _CFGS[0], cost_multiplier=1.0)
    assert t == [] and len(d) == 0
