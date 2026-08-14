"""Tests for native M1 transport, parity contract, and firewall coverage of native URLs."""

from __future__ import annotations

import lzma
import struct
from datetime import date, datetime, timezone

import pytest

from fx_smc_bot.research.v3 import native_transport as nt
from fx_smc_bot.research.v3.firewall import NetworkHoldoutFirewallError, V3HoldoutFirewall

_CANDLE = struct.Struct(">5if")


def _synth_candles(day_ms_rows: list[tuple[int, int, int, int, int]]) -> bytes:
    """(time_sec, open_i, close_i, low_i, high_i) -> lzma-compressed candle payload."""

    raw = b"".join(_CANDLE.pack(t, o, c, low, high, 1.0) for t, o, c, low, high in day_ms_rows)
    return lzma.compress(raw)


def test_native_url_format_and_months_zero_indexed() -> None:
    u = nt.native_m1_url("EURUSD", date(2014, 6, 10), "BID")
    assert u.endswith("/EURUSD/2014/05/10/BID_candles_min_1.bi5")
    with pytest.raises(ValueError):
        nt.native_m1_url("EURUSD", date(2014, 6, 10), "MID")


def test_firewall_blocks_native_holdout_urls() -> None:
    fw = V3HoldoutFirewall()
    fw.guard_url(nt.native_m1_url("EURUSD", date(2017, 12, 29), "BID"))  # allowed
    for d in (date(2018, 1, 2), date(2019, 6, 3)):
        with pytest.raises(NetworkHoldoutFirewallError):
            fw.guard_url(nt.native_m1_url("EURUSD", d, "ASK"))


def test_decode_candle_seconds_timebase() -> None:
    day_ms = int(datetime(2014, 6, 10, tzinfo=timezone.utc).timestamp() * 1000)
    payload = _synth_candles([(0, 135925, 135923, 135923, 135925),
                              (60, 135925, 135924, 135923, 135927),
                              (120, 135925, 135919, 135919, 135927)])
    rows = nt.decode_candle_bi5(payload, day_ms, 100000)
    assert len(rows) == 3
    assert rows[0]["timestamp"] == day_ms
    assert rows[1]["timestamp"] == day_ms + 60_000  # 60s offset -> +1 minute
    assert abs(rows[0]["open"] - 1.35925) < 1e-9


def test_native_m1_day_requires_both_sides() -> None:
    bid = _synth_candles([(0, 135920, 135921, 135919, 135922)])
    ask = _synth_candles([(0, 135930, 135931, 135929, 135932)])
    rows = nt.native_m1_day(bid, ask, "EURUSD", date(2014, 6, 10))
    assert len(rows) == 1
    assert rows[0]["bid_close"] < rows[0]["ask_close"]


def _rows(prices: list[tuple[int, float]]) -> list[dict]:
    return [{"timestamp": ts, "bid_open": p, "bid_high": p, "bid_low": p, "bid_close": p,
             "ask_open": p, "ask_high": p, "ask_low": p, "ask_close": p} for ts, p in prices]


def test_parity_exact_and_missing() -> None:
    a = _rows([(0, 1.3), (60000, 1.31)])
    assert nt.compare_parity(a, list(a), "EURUSD")["verdict"] == nt.PARITY_PASS_EXACT
    assert nt.compare_parity(None, a, "EURUSD")["verdict"] == nt.PARITY_MISSING_NATIVE
    assert nt.compare_parity(a, None, "EURUSD")["verdict"] == nt.PARITY_MISSING_TICK


def test_parity_canonical_equivalent_vs_fail() -> None:
    base = _rows([(0, 1.35925), (60000, 1.35926)])
    # sub-precision perturbation (< 1e-5) -> canonical equivalent
    sub = _rows([(0, 1.359254), (60000, 1.359261)])
    assert nt.compare_parity(sub, base, "EURUSD")["verdict"] == nt.PARITY_PASS_CANONICAL
    # above-precision perturbation -> FAIL
    big = _rows([(0, 1.35935), (60000, 1.35936)])
    assert nt.compare_parity(big, base, "EURUSD")["verdict"] == nt.PARITY_FAIL


def test_parity_contract_is_precision_locked() -> None:
    c = nt.parity_contract()
    assert c["frozen_quote_precision"] == {"jpy_decimals": 3, "nonjpy_decimals": 5}
    assert c["no_loose_tolerance_after_results"] is True
    assert c["no_strategy_or_pnl_comparison"] is True


def test_fill_session_grid_flat_carry_forward() -> None:
    from fx_smc_bot.research.v3 import native_transport as nt
    rows = [
        {"timestamp": 0, "bid_open": 1.1, "bid_high": 1.1, "bid_low": 1.1, "bid_close": 1.1,
         "ask_open": 1.2, "ask_high": 1.2, "ask_low": 1.2, "ask_close": 1.2},
        # minute 60000 missing (no ticks)
        {"timestamp": 120000, "bid_open": 1.3, "bid_high": 1.3, "bid_low": 1.3, "bid_close": 1.3,
         "ask_open": 1.4, "ask_high": 1.4, "ask_low": 1.4, "ask_close": 1.4},
    ]
    filled = nt.fill_session_grid(rows)
    assert [r["timestamp"] for r in filled] == [0, 60000, 120000]
    gap = filled[1]
    assert gap["bid_open"] == gap["bid_high"] == gap["bid_low"] == gap["bid_close"] == 1.1
    # idempotent on an already-full grid
    assert nt.fill_session_grid(filled) == filled


def test_parity_passes_when_only_empty_minutes_differ() -> None:
    from fx_smc_bot.research.v3 import native_transport as nt
    full = [
        {"timestamp": t, "bid_open": 1.1, "bid_high": 1.1, "bid_low": 1.1, "bid_close": 1.1,
         "ask_open": 1.2, "ask_high": 1.2, "ask_low": 1.2, "ask_close": 1.2}
        for t in (0, 60000, 120000)
    ]
    sparse = [full[0], full[2]]  # native has the middle minute (flat), tick omits it
    assert nt.compare_parity(full, sparse, "EURUSD")["verdict"] == nt.PARITY_PASS_EXACT
