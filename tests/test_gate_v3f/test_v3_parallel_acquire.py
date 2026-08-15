"""Tests for the bounded-parallel acquisition core: cache reuse, unit transport classification,
adaptive concurrency up/down, retry amplification and firewall-before-scheduling."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from fx_smc_bot.research.v3 import parallel_acquire as pa
from fx_smc_bot.research.v3.firewall import NetworkHoldoutFirewallError, V3HoldoutFirewall
from fx_smc_bot.research.v3.native_transport import native_m1_url
from fx_smc_bot.research.v3.provider_scheduler import Outcome


# --- cache validity / reuse ---
def test_cache_valid(tmp_path: Path) -> None:
    good = tmp_path / "g.bi5"
    good.write_bytes(b"\x00" * 11000)
    assert pa.cache_valid(good)
    small = tmp_path / "s.bi5"
    small.write_bytes(b"404 not found")          # tiny error body
    assert not pa.cache_valid(small)
    html = tmp_path / "h.bi5"
    html.write_bytes(b"<html>" + b" " * 400)     # 503 HTML page
    assert not pa.cache_valid(html)
    assert not pa.cache_valid(tmp_path / "missing.bi5")


# --- per-unit transport classification (frozen fallback policy) ---
def test_classify_unit_transport() -> None:
    assert pa.classify_unit_transport(Outcome.OK, Outcome.OK) == pa.NATIVE
    assert pa.classify_unit_transport(Outcome.MISSING, Outcome.OK) == pa.FALLBACK
    assert pa.classify_unit_transport(Outcome.OK, Outcome.MISSING) == pa.FALLBACK
    assert pa.classify_unit_transport(Outcome.THROTTLE, Outcome.OK) == pa.RETRY
    assert pa.classify_unit_transport(Outcome.OK, Outcome.TIMEOUT) == pa.RETRY
    assert pa.classify_unit_transport(Outcome.ERROR, Outcome.OK) == pa.RETRY


# --- retry amplification accounting ---
def test_retry_amplification() -> None:
    r = pa.RetryAccounting()
    r.record_attempts(6)
    r.record_certified_files(4)
    assert r.amplification() == 1.5
    assert pa.RetryAccounting().amplification() == 0.0


# --- adaptive concurrency ---
def test_controller_downgrades_on_throttle() -> None:
    t = [0.0]
    c = pa.ConcurrencyController(initial=3, max_level=4, window=10, clock=lambda: t[0])
    for _ in range(10):
        c.observe(True)                          # 100% throttle
    assert c.update(breaker_open=False) == 2


def test_controller_downgrades_on_breaker() -> None:
    c = pa.ConcurrencyController(initial=3, max_level=4)
    assert c.update(breaker_open=True) == 2


def test_controller_upgrades_after_clean_window() -> None:
    t = [100.0]
    c = pa.ConcurrencyController(initial=2, max_level=4, window=10, clock=lambda: t[0])
    for _ in range(10):
        c.observe(False)                         # 0% throttle over a full window
    assert c.update(breaker_open=False) == 3


def test_controller_cooldown_blocks_immediate_upgrade() -> None:
    t = [0.0]
    c = pa.ConcurrencyController(initial=2, max_level=4, window=4, cooldown_s=100.0,
                                clock=lambda: t[0])
    for _ in range(4):
        c.observe(True)
    assert c.update(breaker_open=False) == 1     # downgrade + start cooldown
    for _ in range(4):
        c.observe(False)
    t[0] = 50.0
    assert c.update(breaker_open=False) == 1     # still cooling down -> no upgrade
    t[0] = 200.0
    for _ in range(4):
        c.observe(False)
    assert c.update(breaker_open=False) == 2     # cooldown elapsed -> upgrade


def test_controller_is_bounded() -> None:
    hi = pa.ConcurrencyController(initial=1, max_level=1, window=2)
    for _ in range(4):
        hi.observe(False)
    assert hi.update(breaker_open=False) == 1    # never exceeds max_level
    lo = pa.ConcurrencyController(initial=1, max_level=4)
    assert lo.update(breaker_open=True) == 1     # never below 1


# --- target planning: cache reuse + firewall-before-scheduling ---
def test_plan_targets_reuses_cached_side_and_firewalls(tmp_path: Path) -> None:
    fw = V3HoldoutFirewall()

    def guard(url: str, d: date) -> None:
        fw.guard_url(url)
        fw.guard_date(d, context="test")

    # cache a valid BID side -> only ASK should be scheduled (bid reused, not redownloaded)
    (tmp_path / "EURUSD_2014-06-10_bid.bi5").write_bytes(b"\x00" * 11000)
    targets = pa.plan_targets([("EURUSD", date(2014, 6, 10))], tmp_path, native_m1_url, guard)
    assert {t.side for t in targets} == {"ask"}
    assert all(t.url.startswith("https://datafeed.dukascopy.com/") for t in targets)

    # firewall runs BEFORE scheduling: a 2018 unit must raise (never scheduled)
    with pytest.raises(NetworkHoldoutFirewallError):
        pa.plan_targets([("EURUSD", date(2018, 1, 2))], tmp_path, native_m1_url, guard)
