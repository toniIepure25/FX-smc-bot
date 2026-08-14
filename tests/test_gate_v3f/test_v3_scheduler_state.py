"""Tests for the adaptive provider scheduler, durable state machine and native plan."""

from __future__ import annotations

import random
import tempfile
from datetime import date
from pathlib import Path

import pytest

from fx_smc_bot.research.v3 import native_plan
from fx_smc_bot.research.v3 import provider_scheduler as ps
from fx_smc_bot.research.v3.acquisition_state import StateStore, Transport, UnitStatus


# --- scheduler ---
def test_classify() -> None:
    assert ps.classify(200) is ps.Outcome.OK
    assert ps.classify(503) is ps.Outcome.THROTTLE
    assert ps.classify(429) is ps.Outcome.THROTTLE
    assert ps.classify(404) is ps.Outcome.MISSING
    assert ps.classify(0, timed_out=True) is ps.Outcome.TIMEOUT


def test_token_bucket_paces() -> None:
    b = ps.TokenBucket(rate_per_sec=1.0, capacity=1.0)
    assert b.take(0.0) == 0.0            # first token free
    assert b.take(0.0) > 0.0            # must wait ~1s for next
    assert b.take(2.0) == 0.0            # refilled after time passes


def test_breaker_opens_and_recovers() -> None:
    br = ps.CircuitBreaker(trip_threshold=3, cooldown_s=30.0)
    for _ in range(3):
        br.record(ps.Outcome.THROTTLE, 0.0)
    assert br.state is ps.BreakerState.OPEN
    assert br.allow(0.0) is False
    assert br.allow(31.0) is True        # half-open recovery probe
    br.record(ps.Outcome.OK, 31.0)
    assert br.state is ps.BreakerState.CLOSED


def test_backoff_is_bounded_and_deterministic() -> None:
    r1 = [ps.backoff_delay(a, rng=random.Random(0)) for a in (1, 2, 3, 8)]
    r2 = [ps.backoff_delay(a, rng=random.Random(0)) for a in (1, 2, 3, 8)]
    assert r1 == r2
    assert all(d <= 120.0 for d in r1)


def test_scheduler_gives_up_after_max_attempts() -> None:
    sch = ps.AdaptiveScheduler(max_attempts=3, clock=lambda: 0.0, seed=1)
    assert sch.record(ps.Outcome.THROTTLE, 1.0, 1)[0] is True
    assert sch.record(ps.Outcome.THROTTLE, 1.0, 3)[0] is False  # bounded retries


# --- state machine ---
def test_weekend_is_deterministic_absent_not_from_silence() -> None:
    store = StateStore(Path(tempfile.mkdtemp()) / "s.json")
    store.plan("EURUSD", date(2014, 6, 7))   # Saturday
    store.plan("EURUSD", date(2014, 6, 10))  # Tuesday
    assert store.units["EURUSD:2014-06-07"].status == UnitStatus.TERMINAL_DATA_ABSENT.value
    assert store.units["EURUSD:2014-06-10"].status == UnitStatus.PLANNED.value


def test_illegal_transition_and_no_overwrite_certified() -> None:
    p = Path(tempfile.mkdtemp()) / "s.json"
    store = StateStore(p)
    store.plan("EURUSD", date(2014, 6, 10))
    with pytest.raises(ValueError):
        # illegal: cannot certify directly from PLANNED (must go through IN_PROGRESS)
        store.transition("EURUSD", date(2014, 6, 10), UnitStatus.CERTIFIED_NATIVE)
    store.transition("EURUSD", date(2014, 6, 10), UnitStatus.IN_PROGRESS)
    store.transition("EURUSD", date(2014, 6, 10), UnitStatus.CERTIFIED_NATIVE,
                     transport=Transport.NATIVE_M1.value)
    with pytest.raises(ValueError):
        store.transition("EURUSD", date(2014, 6, 10), UnitStatus.RETRYABLE)  # no overwrite


def test_resume_preserves_certified() -> None:
    p = Path(tempfile.mkdtemp()) / "s.json"
    store = StateStore(p)
    store.plan("EURUSD", date(2014, 6, 10))
    store.transition("EURUSD", date(2014, 6, 10), UnitStatus.IN_PROGRESS)
    store.transition("EURUSD", date(2014, 6, 10), UnitStatus.CERTIFIED_NATIVE,
                     transport=Transport.NATIVE_M1.value, canonical_rows=1440)
    reopened = StateStore(p)
    reopened.load()
    assert reopened.summary()["certified_units"] == 1
    assert "EURUSD:2014-06-10" not in reopened.pending_keys()


# --- native plan ---
def test_native_plan_reduces_requests() -> None:
    c = native_plan.plan_counts()
    assert c["instruments"] == 13
    assert c["native_requests_planned"] < c["tick_requests_equivalent"]
    assert c["tick_requests_equivalent"] / c["native_requests_planned"] >= 10
    assert c["monthly_canonical_partitions"] == 2496


def test_plan_units_are_pre_2018_fx_trading_dates() -> None:
    # Corrected FX weekly calendar: plan includes Sunday partial sessions (weekday 6) but
    # NEVER Saturday (weekday 5, fully closed), and is strictly pre-2018.
    seen_years = set()
    saturdays = 0
    sundays = 0
    for i, (_inst, d) in enumerate(native_plan.iter_units()):
        assert d.year < 2018
        if d.weekday() == 5:
            saturdays += 1
        if d.weekday() == 6:
            sundays += 1
        seen_years.add(d.year)
        if i > 5000:
            break
    assert saturdays == 0        # Saturday is the only fully-closed weekday-type
    assert sundays > 0           # Sunday partial sessions are legitimate trading dates
    assert seen_years <= {2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017}
