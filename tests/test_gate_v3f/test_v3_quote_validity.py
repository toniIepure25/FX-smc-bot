"""Adversarial tests for the V3_SYNCHRONIZED_TICK_QUOTE_VALIDITY_V1 pre-outcome contract.

Proves the frozen quote-level data-quality rule cannot be gamed:
  * a raw crossed synchronized tick (ask < bid) is INVALID;
  * an invalid tick never contributes to OHLC;
  * an invalid tick never counts as observed/executable;
  * a minute with valid + invalid ticks uses the valid ticks only;
  * a minute with only invalid ticks becomes unobserved / non-executable;
  * a day with isolated invalid ticks can still certify (no day-level zero tolerance);
  * no price repair / clamp / swap occurs;
  * a zero-valid-observation day cannot certify;
  * terminal absence requires complete transport accounting (no absence from silence);
  * transient HTTP failures never imply absence;
  * 2018+ tick URLs are impossible.
"""

from __future__ import annotations

from datetime import date

import pytest

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3 import canonical_m1 as cm
from fx_smc_bot.research.v3.firewall import NetworkHoldoutFirewallError, V3HoldoutFirewall
from fx_smc_bot.research.v3.quote_validity import (
    QUOTE_VALIDITY_CONTRACT_ID,
    is_valid_quote,
    quote_validity_contract_hash,
)

# A fixed UTC minute-aligned base (2011-03-15 00:00:00 UTC) in ms (divisible by 60000).
_M0 = 1_299_996_780_000


def _tick(ts_ms: int, bid: float, ask: float) -> ap.Tick:
    return ap.Tick(ts_ms=ts_ms, bid=bid, ask=ask)


def _tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


# --- contract is pre-outcome and deterministic -----------------------------------------
def test_contract_hash_is_deterministic_and_preoutcome() -> None:
    assert QUOTE_VALIDITY_CONTRACT_ID == "V3_SYNCHRONIZED_TICK_QUOTE_VALIDITY_V1"
    h1 = quote_validity_contract_hash()
    h2 = quote_validity_contract_hash()
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)


# --- (1) a raw crossed synchronized tick is INVALID ------------------------------------
def test_crossed_tick_is_invalid() -> None:
    assert is_valid_quote(1.10003, 1.10006, "EURUSD") is True   # ask > bid: valid
    assert is_valid_quote(1.10006, 1.10003, "EURUSD") is False  # ask < bid: INVALID
    assert is_valid_quote(1.10000, 1.10000, "EURUSD") is True   # ask == bid: valid (not crossed)
    # JPY pair, same rule
    assert is_valid_quote(90.36, 90.35, "USDJPY") is False


def test_nonpositive_and_nonfinite_ticks_are_invalid() -> None:
    assert is_valid_quote(0.0, 1.10, "EURUSD") is False
    assert is_valid_quote(1.10, 0.0, "EURUSD") is False
    assert is_valid_quote(-1.0, 1.10, "EURUSD") is False
    assert is_valid_quote(float("inf"), 1.10, "EURUSD") is False
    assert is_valid_quote(1.10, float("nan"), "EURUSD") is False


def test_scaling_implausible_tick_is_invalid() -> None:
    # a non-JPY pair whose mid is far outside the 0.3-3.0 envelope (wrong scale) is INVALID
    assert is_valid_quote(0.00110, 0.00111, "EURUSD") is False
    # a JPY pair whose mid is far outside the 50-200 envelope is INVALID
    assert is_valid_quote(0.9035, 0.9036, "USDJPY") is False


# --- (2) an invalid tick never contributes to OHLC -------------------------------------
def test_invalid_tick_never_contributes_to_ohlc() -> None:
    # minute with a valid tick then a crossed tick: OHLC must come from the valid tick only.
    ticks = [_tick(_M0, 1.10000, 1.10010), _tick(_M0 + 1000, 1.90000, 1.10000)]
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    assert len(rows) == 1
    r = rows[0]
    # the crossed tick (bid 1.90) must NOT appear in any OHLC field
    for f in ("bid_open", "bid_high", "bid_low", "bid_close",
              "ask_open", "ask_high", "ask_low", "ask_close"):
        assert r[f] < 1.5, f"{f} was contaminated by the invalid tick"
    assert r["ask_close"] >= r["bid_close"]
    assert stats.invalid_crossed_tick_count == 1


# --- (3) an invalid tick never counts as observed/executable ---------------------------
def test_invalid_only_minute_is_unobserved() -> None:
    # a minute whose ONLY ticks are crossed has zero valid ticks -> no M1 row -> unobserved.
    ticks = [_tick(_M0, 1.90000, 1.10000), _tick(_M0 + 2000, 1.80000, 1.20000)]
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    assert rows == []                       # no observed minute
    assert stats.valid_tick_count == 0
    assert stats.minutes_with_no_valid_tick == 1
    # canonicalize: the minute is not observed / not executable
    d = date(2011, 3, 15)
    canon = cm.canonicalize_tick_day(rows, d)
    assert canon == []                       # no rows at all -> nothing executable


# --- (4) a minute with valid + invalid ticks uses the valid ticks only ------------------
def test_mixed_minute_uses_valid_ticks_only() -> None:
    # two valid ticks bracketing one crossed tick in the same minute.
    ticks = [
        _tick(_M0, 1.10000, 1.10010),     # valid
        _tick(_M0 + 1000, 1.90000, 1.10000),  # crossed (invalid)
        _tick(_M0 + 2000, 1.10020, 1.10030),  # valid
    ]
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    assert len(rows) == 1
    r = rows[0]
    assert r["bid_open"] == 1.10000 and r["bid_close"] == 1.10020
    assert r["ask_open"] == 1.10010 and r["ask_close"] == 1.10030
    assert r["bid_high"] == 1.10020 and r["ask_high"] == 1.10030  # no 1.90 contamination
    assert stats.valid_tick_count == 2 and stats.invalid_crossed_tick_count == 1


# --- (5) a minute with only invalid ticks becomes unobserved/non-executable -------------
def test_invalid_only_minute_non_executable_in_canonical() -> None:
    # minute A has valid ticks; minute B has only crossed ticks. B must be unobserved.
    ticks = [
        _tick(_M0, 1.10000, 1.10010),                 # minute A: valid
        _tick(_M0 + 61_000, 1.90000, 1.10000),        # minute B: crossed only
        _tick(_M0 + 62_000, 1.80000, 1.20000),        # minute B: crossed only
    ]
    rows, _ = ap.aggregate_m1_valid(ticks, "EURUSD")
    ts = {r["timestamp"] for r in rows}
    assert _M0 in ts                # minute A observed
    assert (_M0 + 60_000) not in ts  # minute B (only invalid ticks) NOT observed


# --- (6) a day with isolated invalid ticks can still certify ---------------------------
def test_day_with_isolated_invalid_ticks_certifies() -> None:
    # every minute has a valid tick; a few minutes also have an isolated crossed tick.
    ticks: list[ap.Tick] = []
    for m in range(5):
        base = _M0 + m * 60_000
        ticks.append(_tick(base, 1.10000 + m * 0.0001, 1.10010 + m * 0.0001))  # valid
        if m in (1, 3):
            ticks.append(_tick(base + 1000, 1.90000, 1.10000))  # isolated crossed tick
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    assert len(rows) == 5
    assert stats.invalid_crossed_tick_count == 2
    d = date(2011, 3, 15)
    canon = cm.canonicalize_tick_day(rows, d)
    cert = ap.certify_partition(instrument="EURUSD", year=2011, month=3, day=15, side="bid",
                                m1_rows=canon, source_bytes=0, source_sha256="x",
                                request_urls=[])
    # the isolated invalid ticks are filtered out -> zero ordering violations -> certifies
    assert cert["integrity_audit"]["bid_ask_ordering_violations"] == 0
    assert cert["acquisition_status"] == "CERTIFIED"


# --- (7) no price repair / clamp / swap occurs -----------------------------------------
def test_no_repair_clamp_or_swap() -> None:
    # a crossed tick must be DROPPED, not repaired (ask:=bid), clamped, or swapped.
    ticks = [_tick(_M0, 1.10000, 1.10010), _tick(_M0 + 1000, 1.10050, 1.10020)]
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    r = rows[0]
    # if the crossed tick were "repaired" (ask:=bid) it would add ask=1.10050; it must not.
    assert r["ask_high"] == 1.10010          # only the valid tick's ask
    assert r["bid_close"] == 1.10000         # only the valid tick's bid (not the 1.10050)
    assert stats.invalid_crossed_tick_count == 1
    # the raw invalid tick is preserved in provenance, not mutated
    assert stats.raw_tick_count == 2 and stats.valid_tick_count == 1


# --- (8) a zero-valid-observation day cannot certify -----------------------------------
def test_zero_valid_observation_day_cannot_certify() -> None:
    # a day whose ticks are ALL crossed -> zero valid ticks -> no rows -> cannot certify.
    ticks = [_tick(_M0 + m * 60_000, 1.90000, 1.10000) for m in range(5)]
    rows, stats = ap.aggregate_m1_valid(ticks, "EURUSD")
    assert rows == []
    assert stats.valid_tick_count == 0
    d = date(2011, 3, 15)
    canon = cm.canonicalize_tick_day(rows, d)
    cert = ap.certify_partition(instrument="EURUSD", year=2011, month=3, day=15, side="bid",
                                m1_rows=canon, source_bytes=0, source_sha256="x",
                                request_urls=[])
    assert cert["acquisition_status"] == "REJECTED_INTEGRITY"


# --- (9) terminal absence requires complete transport accounting -----------------------
def test_absence_requires_complete_transport_accounting() -> None:
    # A zero-observation day is terminal-absent ONLY when the complete session is accounted
    # for with zero VALID observations and no unresolved transient. A single unresolved
    # transient hour keeps it RETRYABLE (never absence from provider silence).
    from fx_smc_bot.research.v3.remediation import (
        CAT_ZERO_OBS,
        TICK_TRANSIENT,
        TICK_ZERO_OBS,
        decide_remediation_outcome,
    )
    assert decide_remediation_outcome(category=CAT_ZERO_OBS, tick_state=TICK_ZERO_OBS,
                                      tick_audit=None) == "TERMINAL_DATA_ABSENT"
    # an unresolved transient hour -> RETRYABLE, never absence
    assert decide_remediation_outcome(category=CAT_ZERO_OBS, tick_state=TICK_TRANSIENT,
                                      tick_audit=None) == "RETRYABLE"


# --- (10) transient HTTP failures never imply absence ----------------------------------
def test_transient_http_never_implies_absence() -> None:
    from fx_smc_bot.research.v3.remediation import (
        CAT_BIDASK_ORDER,
        TICK_TRANSIENT,
        decide_remediation_outcome,
    )
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_TRANSIENT,
                                      tick_audit=None) == "RETRYABLE"


# --- (11) 2018+ tick URLs are impossible ------------------------------------------------
def test_2018_plus_tick_url_is_blocked() -> None:
    fw = V3HoldoutFirewall()
    with pytest.raises(NetworkHoldoutFirewallError):
        fw.guard_url(_tick_url("EURUSD", date(2018, 1, 2), 0))
    assert fw.network.blocked_2018_plus_count() == 1


def test_pre_2018_tick_url_is_permitted() -> None:
    fw = V3HoldoutFirewall()
    fw.guard_url(_tick_url("EURUSD", date(2017, 12, 31), 0))  # must not raise
    assert fw.network.blocked_2018_plus_count() == 0
