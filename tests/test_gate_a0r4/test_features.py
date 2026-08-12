"""Hand-computable feature-formula and causality tests."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from fx_smc_bot.research.v2 import features as fx
from tests.test_gate_a0r4.conftest import build_frame


def _ramp_frame(n: int = 40) -> pd.DataFrame:
    bars = [{"bid": 1.10 + 0.0001 * i, "ask": 1.1002 + 0.0001 * i} for i in range(n)]
    return build_frame(bars)


def test_wilder_atr_matches_manual_recursion() -> None:
    frame = build_frame([
        {"bid_open": 1.0, "bid_high": 1.2, "bid_low": 0.8, "bid_close": 1.0,
         "ask_open": 1.0, "ask_high": 1.2, "ask_low": 0.8, "ask_close": 1.0},
        {"bid_open": 1.0, "bid_high": 1.3, "bid_low": 0.9, "bid_close": 1.1,
         "ask_open": 1.0, "ask_high": 1.3, "ask_low": 0.9, "ask_close": 1.1},
        {"bid_open": 1.1, "bid_high": 1.4, "bid_low": 1.0, "bid_close": 1.2,
         "ask_open": 1.1, "ask_high": 1.4, "ask_low": 1.0, "ask_close": 1.2},
    ])
    atr = fx.wilder_atr(frame, period=2)
    # TR0 = 0.4; TR1 = max(0.4, |1.3-1.0|, |0.9-1.0|) = 0.4; TR2 = max(0.4,|1.4-1.1|,|1.0-1.1|)=0.4
    # i<period: mean of TR so far. i==period(2): seed = mean(TR[:2]) = 0.4.
    assert atr.iloc[0] == pytest.approx(0.4)
    assert atr.iloc[1] == pytest.approx(0.4)
    assert atr.iloc[2] == pytest.approx(0.4)


def test_rolling_zscore_is_zero_for_constant_series() -> None:
    s = pd.Series([5.0] * 30)
    z = fx.rolling_zscore(s, lookback=10, min_obs=3)
    assert float(np.abs(z).max()) == 0.0


def test_rolling_zscore_known_value() -> None:
    s = pd.Series([0.0, 0.0, 0.0, 3.0])
    z = fx.rolling_zscore(s, lookback=4, min_obs=2)
    # last window [0,0,0,3]: mean=0.75, std(ddof0)=sqrt(1.6875)=1.29904; z=(3-0.75)/1.29904
    assert z.iloc[-1] == pytest.approx((3 - 0.75) / np.sqrt(1.6875), abs=1e-9)


def test_returns_are_causal_no_future_leakage() -> None:
    frame = _ramp_frame(40)
    ret = fx.mid_return_over(frame, lookback=5)
    mutated = frame.copy()
    mutated.loc[mutated.index[20:], "mid_close"] *= 1.5
    ret_mut = fx.mid_return_over(mutated, lookback=5)
    # values strictly before index 20 must be unaffected by future mutation
    assert np.allclose(ret.to_numpy()[:20], ret_mut.to_numpy()[:20])


def test_model_feature_panel_has_no_nan_and_is_finite() -> None:
    frame = _ramp_frame(120)
    panel = fx.model_feature_panel(frame, lookback=10)
    assert not panel.isna().any().any()
    assert np.isfinite(panel.to_numpy()).all()


def test_session_mask_selects_expected_ny_hours() -> None:
    # 12:00-13:00 UTC in June is NY 08:00-09:00 -> new_york_open window includes hour 8
    ts = pd.date_range("2016-06-15 12:00", periods=3, freq="1min", tz="UTC")
    frame = pd.DataFrame({"timestamp": ts, "bid_close": 1.1, "ask_close": 1.1})
    mask = fx.session_mask(frame, "new_york_open")
    assert bool(mask.iloc[0])
