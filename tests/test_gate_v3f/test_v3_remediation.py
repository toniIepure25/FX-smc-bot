"""Adversarial tests for the V3_DATA_INTEGRITY_REMEDIATION_V1 pre-outcome contract.

Proves the frozen remediation rules cannot be gamed:
  * generic integrity failures are NOT silently excluded / remediated;
  * native ask<bid cannot certify native;
  * ask<bid triggers tick fallback ONLY under the frozen eligible category;
  * a successful synchronized tick fallback must have zero ordering violations;
  * zero-native-observation does NOT imply terminal absence before full tick confirmation;
  * transient tick failures never imply absence;
  * full-session zero native + zero tick observations may become TERMINAL_DATA_ABSENT;
  * certified native units remain unchanged;
  * 2018+ tick URLs are impossible.
"""

from __future__ import annotations

from datetime import date

import pytest

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3.acquisition_state import StateStore, UnitStatus
from fx_smc_bot.research.v3.firewall import NetworkHoldoutFirewallError, V3HoldoutFirewall
from fx_smc_bot.research.v3.remediation import (
    ABSENT_REASON_CONFIRMED,
    CAT_BIDASK_ORDER,
    CAT_ZERO_OBS,
    ELIGIBLE_CATEGORIES,
    TICK_HAS_OBS,
    TICK_TRANSIENT,
    TICK_ZERO_OBS,
    decide_remediation_outcome,
    remediation_contract_hash,
)

PASS_AUDIT = {"bid_ask_ordering_violations": 0, "scaling_plausibility_ok": True,
              "duplicate_timestamps": 0}
FAIL_AUDIT = {"bid_ask_ordering_violations": 3, "scaling_plausibility_ok": True,
              "duplicate_timestamps": 0}


def _tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


# --- contract is pre-outcome and deterministic -----------------------------------------
def test_contract_hash_is_deterministic_and_preoutcome() -> None:
    h1 = remediation_contract_hash()
    h2 = remediation_contract_hash()
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)


def test_only_two_categories_are_eligible() -> None:
    assert set(ELIGIBLE_CATEGORIES) == {CAT_ZERO_OBS, CAT_BIDASK_ORDER}


# --- generic integrity failures are NOT silently excluded -------------------------------
def test_non_eligible_category_is_never_remediated() -> None:
    # Even a "passing" tick audit cannot rescue a non-eligible integrity failure.
    assert decide_remediation_outcome(category="OTHER_INTEGRITY_FAILURE",
                                      tick_state=TICK_HAS_OBS, tick_audit=PASS_AUDIT) \
        == "INTEGRITY_FAILURE"
    assert decide_remediation_outcome(category="NATIVE_SCALING_FAILURE",
                                      tick_state=TICK_ZERO_OBS, tick_audit=None) \
        == "INTEGRITY_FAILURE"


def test_begin_remediation_refuses_non_eligible_category(tmp_path) -> None:
    store = StateStore(tmp_path / "s.json")
    d = date(2014, 6, 10)
    store.plan("EURUSD", d)
    store.transition("EURUSD", d, UnitStatus.IN_PROGRESS)
    store.transition("EURUSD", d, UnitStatus.INTEGRITY_FAILURE)
    with pytest.raises(ValueError):
        store.begin_remediation("EURUSD", d, "OTHER_INTEGRITY_FAILURE")
    # status unchanged: still INTEGRITY_FAILURE, not silently moved
    assert store.units["EURUSD:2014-06-10"].status == UnitStatus.INTEGRITY_FAILURE.value


def test_begin_remediation_refuses_non_failure_status(tmp_path) -> None:
    store = StateStore(tmp_path / "s.json")
    d = date(2014, 6, 10)
    store.plan("EURUSD", d)
    with pytest.raises(ValueError):
        store.begin_remediation("EURUSD", d, CAT_BIDASK_ORDER)  # PLANNED, not a failure


# --- native ask<bid cannot certify native -----------------------------------------------
def test_native_ask_lt_bid_cannot_certify() -> None:
    rows = [{"timestamp": 1_402_394_400_000,
             "bid_open": 1.10, "bid_high": 1.10, "bid_low": 1.10, "bid_close": 1.10006,
             "ask_open": 1.10, "ask_high": 1.10, "ask_low": 1.10, "ask_close": 1.10003,
             "bid_volume": 5.0, "ask_volume": 5.0}]
    cert = ap.certify_partition(instrument="EURUSD", year=2014, month=6, day=10, side="bid",
                                m1_rows=rows, source_bytes=0, source_sha256="x",
                                request_urls=[])
    assert cert["integrity_audit"]["bid_ask_ordering_violations"] == 1
    assert cert["integrity_audit"]["bid_ask_valid"] is False
    assert cert["acquisition_status"] == "REJECTED_INTEGRITY"


# --- ask<bid triggers tick fallback ONLY under the frozen eligible category -------------
def test_bidask_category_with_clean_tick_certifies() -> None:
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=PASS_AUDIT) == "CERTIFIED_TICK_FALLBACK"


def test_bidask_category_with_violating_tick_stays_failure() -> None:
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=FAIL_AUDIT) == "INTEGRITY_FAILURE"


# --- a successful synchronized tick fallback must have zero ordering violations --------
def test_tick_fallback_requires_zero_violations() -> None:
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=PASS_AUDIT) == "CERTIFIED_TICK_FALLBACK"
    # a single violation is enough to keep it an integrity failure (zero tolerance)
    one_viol = {"bid_ask_ordering_violations": 1, "scaling_plausibility_ok": True,
                "duplicate_timestamps": 0}
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=one_viol) == "INTEGRITY_FAILURE"
    # duplicates also block certification
    dups = {"bid_ask_ordering_violations": 0, "scaling_plausibility_ok": True,
            "duplicate_timestamps": 2}
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=dups) == "INTEGRITY_FAILURE"
    # scaling failure also blocks certification
    badscale = {"bid_ask_ordering_violations": 0, "scaling_plausibility_ok": False,
                "duplicate_timestamps": 0}
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_HAS_OBS,
                                      tick_audit=badscale) == "INTEGRITY_FAILURE"


# --- zero-native-observation does NOT imply absence before full tick confirmation ------
def test_zero_obs_day_with_tick_data_is_not_absent() -> None:
    # a zero-native-observation day that HAS tick observations is certified, not absent
    assert decide_remediation_outcome(category=CAT_ZERO_OBS, tick_state=TICK_HAS_OBS,
                                      tick_audit=PASS_AUDIT) == "CERTIFIED_TICK_FALLBACK"


# --- transient tick failures never imply absence ---------------------------------------
def test_transient_tick_never_implies_absence() -> None:
    assert decide_remediation_outcome(category=CAT_ZERO_OBS, tick_state=TICK_TRANSIENT,
                                      tick_audit=None) == "RETRYABLE"
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_TRANSIENT,
                                      tick_audit=None) == "RETRYABLE"


# --- full-session zero native + zero tick => TERMINAL_DATA_ABSENT ----------------------
def test_zero_native_and_zero_tick_is_terminal_absent() -> None:
    assert decide_remediation_outcome(category=CAT_ZERO_OBS, tick_state=TICK_ZERO_OBS,
                                      tick_audit=None) == "TERMINAL_DATA_ABSENT"


def test_bidask_day_with_zero_tick_is_not_absent() -> None:
    # a bid/ask day had native observations; zero tick observations is NOT a confirmed
    # closure for this category -- it conservatively remains an integrity failure.
    assert decide_remediation_outcome(category=CAT_BIDASK_ORDER, tick_state=TICK_ZERO_OBS,
                                      tick_audit=None) == "INTEGRITY_FAILURE"


def test_absent_reason_is_the_frozen_confirmed_string() -> None:
    assert ABSENT_REASON_CONFIRMED == "confirmed_no_market_observations_native_and_tick"


# --- certified native units remain unchanged -------------------------------------------
def test_certified_native_unit_cannot_regress(tmp_path) -> None:
    store = StateStore(tmp_path / "s.json")
    d = date(2014, 6, 10)
    store.plan("EURUSD", d)
    store.transition("EURUSD", d, UnitStatus.IN_PROGRESS)
    store.transition("EURUSD", d, UnitStatus.CERTIFIED_NATIVE, transport="NATIVE_M1",
                     source_checksum="s", canonical_checksum="c", canonical_rows=1440)
    # a certified unit can never be re-entered into the remediation pass or any other state
    with pytest.raises(ValueError):
        store.begin_remediation("EURUSD", d, CAT_BIDASK_ORDER)
    with pytest.raises(ValueError):
        store.transition("EURUSD", d, UnitStatus.IN_PROGRESS)
    assert store.units["EURUSD:2014-06-10"].status == UnitStatus.CERTIFIED_NATIVE.value


# --- 2018+ tick URLs are impossible -----------------------------------------------------
def test_2018_plus_tick_url_is_blocked() -> None:
    fw = V3HoldoutFirewall()
    with pytest.raises(NetworkHoldoutFirewallError):
        fw.guard_url(_tick_url("EURUSD", date(2018, 1, 2), 0))
    assert fw.network.blocked_2018_plus_count() == 1


def test_pre_2018_tick_url_is_permitted() -> None:
    fw = V3HoldoutFirewall()
    fw.guard_url(_tick_url("EURUSD", date(2017, 12, 31), 0))  # must not raise
    assert fw.network.blocked_2018_plus_count() == 0
