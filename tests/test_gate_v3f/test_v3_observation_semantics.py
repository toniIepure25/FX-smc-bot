"""Adversarial tests for V3 missing-observation semantics.

A clock-grid (imputed carry-forward) row must never become a real quote: no fill may occur
on it, it must not create a spurious zero market return, and it must not make stale cross-pair
legs look synchronized. These tests exercise the canonical schema + execution/feature/cross-pair
/MTF helpers on hand-built fixtures.
"""

from __future__ import annotations

import math
from datetime import date

from fx_smc_bot.research.v3 import canonical_m1 as cm


def _native(ts: int, mid: float, *, bid_vol: float, ask_vol: float) -> dict[str, float | int]:
    return {"timestamp": ts, "bid_open": mid - 5e-5, "bid_high": mid - 5e-5,
            "bid_low": mid - 5e-5, "bid_close": mid - 5e-5,
            "ask_open": mid + 5e-5, "ask_high": mid + 5e-5, "ask_low": mid + 5e-5,
            "ask_close": mid + 5e-5, "bid_volume": bid_vol, "ask_volume": ask_vol}


def _day_native(d: date, mids_vols: list[tuple[float, float]]) -> list[dict[str, float | int]]:
    # place minutes at 13:00 UTC so they are inside the (full) session window
    base = int(__import__("datetime").datetime(d.year, d.month, d.day, 13, 0,
              tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
    return [_native(base + i * 60000, m, bid_vol=v, ask_vol=v)
            for i, (m, v) in enumerate(mids_vols)]


D = date(2014, 6, 10)  # Monday full session


def test_imputed_row_is_not_executable_and_marked() -> None:
    # minute 1 has zero volume -> imputed carry-forward, not executable
    rows = cm.canonicalize_native_day(
        _day_native(D, [(1.10, 3.0), (1.10, 0.0), (1.11, 5.0)]), D)
    assert [r["is_imputed"] for r in rows] == [False, True, False]
    assert [r["executable_quote"] for r in rows] == [True, False, True]
    assert rows[1]["staleness_minutes"] == 1
    # carry-forward flat bar equals the previous close, not a new market print
    assert rows[1]["bid_close"] == rows[0]["bid_close"]


def test_no_fill_on_imputed_execution_waits_for_next_observed() -> None:
    rows = cm.canonicalize_native_day(
        _day_native(D, [(1.10, 3.0), (1.10, 0.0), (1.10, 0.0), (1.11, 5.0)]), D)
    # an intended fill at index 1 (imputed) must not execute; next executable is index 3
    assert not cm.is_executable(rows, 1)
    assert not cm.is_executable(rows, 2)
    assert cm.next_executable_index(rows, 1) == 3
    assert cm.next_executable_index(rows, 0) == 0


def test_imputed_row_is_not_a_zero_return() -> None:
    rows = cm.canonicalize_native_day(
        _day_native(D, [(1.10, 3.0), (1.10, 0.0), (1.21, 5.0)]), D)
    rets = cm.observed_return_series(rows)
    # the imputed minute contributes no return; the post-gap return is measured across the gap
    assert rets[1] is None
    assert rets[2] is not None and abs(rets[2] - math.log(1.21 / 1.10)) < 1e-9
    # a naive per-clock-minute return would have logged 0 then log(1.21/1.10); the imputed
    # zero-return is explicitly absent.
    assert 0.0 not in [r for r in rets if r is not None]


def test_bid_only_observation_is_not_executable() -> None:
    # ask volume 0 but bid volume >0 -> not executable (need both sides)
    rows = cm.canonicalize_native_day(
        [_native(int(__import__("datetime").datetime(2014, 6, 10, 13, 0,
                 tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000), 1.10,
                 bid_vol=4.0, ask_vol=0.0)], D)
    assert rows[0]["bid_observed"] is True
    assert rows[0]["ask_observed"] is False
    assert rows[0]["executable_quote"] is False
    assert rows[0]["is_imputed"] is True


def test_cross_pair_stale_leg_breaks_synchronization() -> None:
    # mandate example: EURUSD imputed at t, USDJPY & EURJPY observed at t -> not synchronized
    t = 1_000_000
    def row(exe: bool) -> dict[str, object]:
        return {"timestamp": t, "executable_quote": exe}
    legs = {
        "EURUSD": {t: row(False)},   # stale/imputed
        "USDJPY": {t: row(True)},
        "EURJPY": {t: row(True)},
    }
    assert cm.synchronized_observation(legs, t) is False
    legs["EURUSD"][t] = row(True)    # all fresh
    assert cm.synchronized_observation(legs, t) is True


def test_mtf_resample_carries_observation_coverage() -> None:
    # 5 minutes: 2 observed, 3 imputed -> M5 bar coverage_fraction 0.4, not 5 observations
    mids = [(1.10, 3.0), (1.10, 0.0), (1.10, 0.0), (1.10, 0.0), (1.11, 5.0)]
    rows = cm.canonicalize_native_day(_day_native(D, mids), D)
    m5 = cm.resample_mtf(rows, 5)
    assert len(m5) == 1
    assert m5[0]["observed_minutes"] == 2
    assert m5[0]["imputed_minutes"] == 3
    assert m5[0]["coverage_fraction"] == 0.4


def test_volume_preserved_as_provenance_not_in_canonical_alpha_fields() -> None:
    # native rows carry volume, but the CANONICAL schema exposes observation masks, not volume
    assert "volume" not in cm.CANONICAL_FIELDS
    assert "bid_observed" in cm.CANONICAL_FIELDS and "executable_quote" in cm.CANONICAL_FIELDS


def test_tick_and_native_masks_agree_on_thin_session() -> None:
    # native full grid with a zero-vol gap; tick sparse (omits the gap) -> masks must agree
    native = _day_native(D, [(1.10, 3.0), (1.10, 0.0), (1.11, 5.0)])
    tick = [{k: v for k, v in r.items() if k != "bid_volume" and k != "ask_volume"}
            for r in _day_native(D, [(1.10, 3.0), (1.11, 5.0)])]
    # shift the tick second minute to align with native minute index 2
    tick[1]["timestamp"] = native[2]["timestamp"]
    res = cm.observation_mask_parity(native, tick, D)
    assert res["verdict"] == "PASS"
    assert res["native_imputed"] == res["tick_imputed"]
