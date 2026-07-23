from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fx_smc_bot.research.gate_c4_event_alpha import (
    ALLOWED_PAIR,
    GateC4Paths,
    apply_outcomes,
    assert_development_request,
    ensure_no_prohibited_metrics,
    extract_events,
    holm_adjust,
    mark_non_overlapping,
    paired_permutation_p_value,
    stable_json_hash,
    validate_preregistration,
)


def _synthetic_bidask_frame(n: int = 80) -> pd.DataFrame:
    ts = pd.date_range("2015-01-05 00:00:00Z", periods=n, freq="5min")
    mid = np.linspace(120.0, 120.2, n)
    spread = 0.02
    return pd.DataFrame(
        {
            "timestamp": ts,
            "bid_open": mid - spread / 2,
            "bid_high": mid + 0.02 - spread / 2,
            "bid_low": mid - 0.02 - spread / 2,
            "bid_close": mid + 0.005 - spread / 2,
            "ask_open": mid + spread / 2,
            "ask_high": mid + 0.02 + spread / 2,
            "ask_low": mid - 0.02 + spread / 2,
            "ask_close": mid + 0.005 + spread / 2,
        }
    )


def test_development_request_rejects_non_usdjpy_and_holdout_years() -> None:
    assert_development_request(ALLOWED_PAIR, (2015, 2016))
    with pytest.raises(ValueError, match="USDJPY"):
        assert_development_request("EURUSD", (2015,))
    with pytest.raises(ValueError, match="validation/holdout"):
        assert_development_request(ALLOWED_PAIR, (2020,))


def test_preregistration_hash_detects_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = GateC4Paths(root=tmp_path)
    prereg_path = paths.results_dir / "preregistration.json"
    core = {"allowed_pair": "USDJPY", "primary_horizons_minutes": {"x": 60}}
    prereg_path.parent.mkdir(parents=True)
    prereg_path.write_text(
        json.dumps({"core": core, "preregistration_hash": stable_json_hash(core)})
    )

    def fake_run(*_args: object, **_kwargs: object) -> object:
        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("fx_smc_bot.research.gate_c4_event_alpha.subprocess.run", fake_run)
    validate_preregistration(paths)

    altered = {
        "core": {**core, "allowed_pair": "EURUSD"},
        "preregistration_hash": stable_json_hash(core),
    }
    prereg_path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_preregistration(paths)


def test_apply_outcomes_uses_next_bar_and_executable_bid_ask() -> None:
    df = _synthetic_bidask_frame()
    for side, expected in (("LONG", (df.loc[14, "bid_close"] - df.loc[2, "ask_open"]) * 1000),):
        events = pd.DataFrame(
            [
                {
                    "event_id": f"evt-{side}",
                    "family": "liquidity_sweep_mss_fvg_reversal",
                    "direction": side,
                    "confirmation_index": 1,
                    "confirmation_timestamp": df.loc[1, "timestamp"],
                    "earliest_entry_index": 2,
                    "earliest_entry_timestamp": df.loc[2, "timestamp"],
                    "year": 2015,
                    "month": 1,
                    "session": "asia",
                    "utc_date": "2015-01-05",
                    "primary_horizon_minutes": 60,
                }
            ]
        )
        out = apply_outcomes(
            df.assign(
                mid_open=(df.bid_open + df.ask_open) / 2,
                mid_close=(df.bid_close + df.ask_close) / 2,
            ),
            events,
        )
        assert out.loc[0, "earliest_entry_timestamp"] == df.loc[2, "timestamp"]
        assert out.loc[0, "primary_executable_markout_points"] == pytest.approx(expected)


def test_mark_non_overlapping_embargoes_primary_horizon() -> None:
    ts = pd.to_datetime(
        [
            "2015-01-01 00:00:00Z",
            "2015-01-01 00:30:00Z",
            "2015-01-01 01:10:00Z",
        ],
        utc=True,
    )
    events = pd.DataFrame(
        {
            "family": ["opening_range_london"] * 3,
            "confirmation_timestamp": ts,
            "earliest_entry_timestamp": ts + pd.Timedelta(minutes=5),
            "primary_horizon_minutes": [60, 60, 60],
        }
    )
    out = mark_non_overlapping(events)
    assert out["non_overlap_primary"].tolist() == [True, False, True]


def test_extract_events_is_deterministic_on_same_input() -> None:
    df = _synthetic_bidask_frame(120)
    mid_cols = {
        "mid_open": (df.bid_open + df.ask_open) / 2,
        "mid_high": (df.bid_high + df.ask_high) / 2,
        "mid_low": (df.bid_low + df.ask_low) / 2,
        "mid_close": (df.bid_close + df.ask_close) / 2,
    }
    df = df.assign(**mid_cols)
    df["spread"] = df.ask_open - df.bid_open
    df["atr"] = 0.03
    df["pre_event_volatility"] = 0.0001
    df["pre_event_trend"] = 0.1
    df["range_position"] = 0.5
    df["year"] = df.timestamp.dt.year
    df["month"] = df.timestamp.dt.month
    df["utc_date"] = df.timestamp.dt.date.astype(str)
    df["session"] = "asia"
    df["prev_day_high"] = 120.15
    df["prev_day_low"] = 119.95
    df.loc[60, "mid_high"] = 120.25
    df.loc[60, "mid_close"] = 120.12
    one = extract_events(df)
    two = extract_events(df)
    assert one["event_id"].tolist() == two["event_id"].tolist()


def test_inference_helpers_are_bounded_and_monotone() -> None:
    p_value = paired_permutation_p_value(np.array([1.0, 2.0, 3.0]), seed=7, iterations=200)
    assert 0.0 <= p_value <= 1.0
    adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.20})
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"]


def test_prohibited_metric_key_detection() -> None:
    assert ensure_no_prohibited_metrics({"primary_estimand": {"mean": 1.0}}) == []
    hits = ensure_no_prohibited_metrics({"sharpe": 1.0, "nested": {"equity_curve": []}})
    assert hits == ["equity_curve", "sharpe"]
