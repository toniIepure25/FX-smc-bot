"""Adversarial tests for the V3.1 pre-alpha data-availability amendment.

Proves the UNRESOLVED_DATA_GAP semantics cannot be used to fabricate fills, returns,
features or ML examples; that cross-instrument constructions stay unavailable when a leg
is unavailable; that unrelated instruments remain usable; that the monthly manifest and
global digest retain the unresolved classification; that an unresolved day can never
silently become an exclusion; and that no denominator shrinks.
"""

from __future__ import annotations

from fx_smc_bot.research.v3 import data_availability as da
from fx_smc_bot.research.v3 import monthly_certify as mc
from fx_smc_bot.research.v3.data_gate import (
    VERDICT_V31_CERTIFIED,
    VERDICT_V31_NOT_READY,
    build_gate_v31,
)
from fx_smc_bot.research.v3.freeze import component_hashes, freeze_hash
from fx_smc_bot.research.v3.universes import universe_counts

GAP = da.UNRESOLVED_DATA_GAP
OLD_FREEZE_HASH = "10c2f71360008ddcb3dd4c0df0ec3da09305dcdffa44047c6d01e64613b88e6d"

_ALL_TRUE = {
    "dependencies_satisfiable_in_plan": True, "denominator_unambiguous": True,
    "freeze_identities_correct": True, "readiness_evidence_derived": True,
    "no_2018_requests": True, "no_2018_reads": True, "no_outcome_computed": True,
    "manifests_reproduce": True, "quality_gates_pass": True, "no_orphan_processes": True,
}

LIVE_STATUS_COUNTS = {
    "CERTIFIED_NATIVE": 32117,
    "CERTIFIED_TICK_FALLBACK": 406,
    "TERMINAL_DATA_ABSENT": 28,
    "UNRESOLVED_DATA_GAP": 1,
}


# --- 1. unresolved day cannot produce a fill ---
def test_unresolved_day_cannot_produce_a_fill() -> None:
    sem = da.day_execution_semantics(GAP)
    assert sem["entry"] is False
    assert sem["exit"] is False
    assert sem["stop_or_target_fill"] is False
    assert sem["executable_quote"] is False
    assert sem["synthetic_quote"] is False


# --- 2. unresolved day cannot generate a zero return ---
def test_unresolved_day_cannot_generate_a_zero_return() -> None:
    sem = da.day_execution_semantics(GAP)
    assert sem["zero_return_insertion"] is False
    # and it is not an observable quote that a return could be computed from
    assert sem["executable_quote"] is False


# --- 3. unresolved day does not update stateful features ---
def test_unresolved_day_does_not_update_stateful_features() -> None:
    sem = da.day_execution_semantics(GAP)
    assert sem["stateful_market_feature_update"] is False
    assert sem["spread_volatility_atr_update"] is False
    assert sem["ml_training_example"] is False
    # clock/calendar time may still advance (frozen missing-observation semantics)
    assert sem["clock_may_advance"] is True


# --- 4. next executable quote semantics are preserved ---
def test_next_executable_quote_semantics_preserved() -> None:
    sem = da.day_execution_semantics(GAP)
    assert sem["on_pending_order"] == "advance_clock_to_next_session_valid_executable_quote"
    # identical to the already-frozen TERMINAL_DATA_ABSENT semantics (no new mechanism)
    assert sem["on_pending_order"] == da.day_execution_semantics(
        "TERMINAL_DATA_ABSENT")["on_pending_order"]
    # certified days still execute normally
    assert da.day_execution_semantics("CERTIFIED_NATIVE")["on_pending_order"] == (
        "execute_on_session_valid_executable_quote"
    )


# --- 5. cross-pair feature requiring USDJPY is unavailable that day ---
def test_cross_pair_requiring_usdjpy_unavailable_that_day() -> None:
    assert da.cross_construction_available(
        {"EURUSD": "CERTIFIED_NATIVE", "USDJPY": GAP}) is False
    # a terminal-absent leg is equally unavailable (no contemporaneous observation)
    assert da.cross_construction_available(
        {"EURUSD": "CERTIFIED_NATIVE", "USDJPY": "TERMINAL_DATA_ABSENT"}) is False
    # all legs certified -> available
    assert da.cross_construction_available(
        {"EURUSD": "CERTIFIED_NATIVE", "USDJPY": "CERTIFIED_TICK_FALLBACK"}) is True
    # an empty leg set is not a construction
    assert da.cross_construction_available({}) is False


# --- 6. unrelated instruments remain usable ---
def test_unrelated_instruments_remain_usable() -> None:
    # EURUSD on the same day is still fully executable
    assert da.day_execution_semantics("CERTIFIED_NATIVE")["entry"] is True
    # a construction NOT requiring USDJPY is unaffected
    assert da.cross_construction_available({"EURUSD": "CERTIFIED_NATIVE",
                                            "GBPUSD": "CERTIFIED_NATIVE"}) is True
    # admissibility of the whole dataset is unaffected by the single unresolved unit
    ok, violations = da.dataset_is_discovery_usable(LIVE_STATUS_COUNTS)
    assert ok and violations == []


# --- 7. monthly manifest retains unresolved classification ---
def _rows(year: int, month: int, px: float = 1.1) -> dict[str, list[dict[str, float | int]]]:
    rows: dict[str, list[dict[str, float | int]]] = {}
    ts = 1_000_000
    for d in mc.month_trading_dates(year, month):
        rows[d.isoformat()] = [
            {"timestamp": ts, "open": px, "high": px + 0.0001, "low": px - 0.0001,
             "close": px},
            {"timestamp": ts + 60000, "open": px, "high": px + 0.0001, "low": px - 0.0001,
             "close": px},
        ]
        ts += 120000
    return rows


def test_monthly_manifest_retains_unresolved_classification() -> None:
    rows = _rows(2014, 6, px=93.0)  # JPY envelope (50-200) for USDJPY, decimals=3
    day = sorted(rows)[10]
    rows.pop(day)
    cert = mc.certify_month(instrument="USDJPY", year=2014, month=6, side="bid",
                            rows_by_date=rows,
                            transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=3,
                            unresolved_dates={day: "unresolved_provider_data_gap_v3_1"})
    assert cert["status"] == mc.USABLE_WITH_UNRESOLVED_DATA_GAP
    assert cert["unresolved_dates"] == {day: "unresolved_provider_data_gap_v3_1"}
    assert cert["unresolved_date_count"] == 1
    assert cert["missing_dates"] == []
    # identity: required = present + excluded + unresolved
    assert cert["required_trading_dates"] == (
        cert["present_dates"] + cert["excluded_date_count"] + cert["unresolved_date_count"]
    )
    # a present date cannot be labelled unresolved (no hiding observed data as a gap)
    full = _rows(2014, 6, px=93.0)
    try:
        mc.certify_month(instrument="USDJPY", year=2014, month=6, side="bid",
                         rows_by_date=full,
                         transport_by_date={d: "NATIVE_M1" for d in full},
                         fallback_by_date={}, decimals=3,
                         unresolved_dates={sorted(full)[5]: "x"})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- 8. global digest changes when the day class changes ---
def test_digest_changes_when_day_class_changes() -> None:
    base = _rows(2014, 6)
    day = sorted(base)[10]
    reason = "confirmed_no_market_observations_native_and_tick"

    def _cert(dropped: str, **kw: object) -> dict[str, object]:
        rows = _rows(2014, 6)
        rows.pop(dropped)
        return mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                                rows_by_date=rows,
                                transport_by_date={d: "NATIVE_M1" for d in rows},
                                fallback_by_date={}, decimals=5, **kw)  # type: ignore[arg-type]

    as_certified = _cert(day)  # the dropped date is re-present -> fully certified
    as_excluded = _cert(day, excluded_dates={day: reason})
    as_unresolved = _cert(day, unresolved_dates={day: "unresolved_provider_data_gap_v3_1"})
    digests = {
        "certified": mc.global_data_freeze_digest([as_certified])["global_digest"],
        "excluded": mc.global_data_freeze_digest([as_excluded])["global_digest"],
        "unresolved": mc.global_data_freeze_digest([as_unresolved])["global_digest"],
    }
    assert len(set(digests.values())) == 3  # all three classes hash differently
    classes = mc.global_data_freeze_digest([as_unresolved])["partition_day_class_counts"]
    assert classes["unresolved_data_gap_days"] == 1
    assert classes["excluded_days"] == 0
    assert classes["missing_unexplained_days"] == 0


# --- 9. unresolved data cannot silently become an exclusion ---
def test_unresolved_cannot_silently_become_an_exclusion() -> None:
    assert GAP not in da.EXCLUDED_STATES
    assert GAP not in da.OBSERVABLE_STATES
    assert GAP in da.UNRESOLVED_STATES
    # the gate accounts for unresolved units in a separate bucket, never as excluded
    gate = build_gate_v31(
        certified_native_units=32117, certified_tick_fallback_units=406,
        prospectively_excluded_units=28, unresolved_data_gap_units=1,
        required_units=32552, status_counts=LIVE_STATUS_COUNTS, evidence=_ALL_TRUE,
        unresolved_gap_units=["USDJPY:2010-01-01"],
    )
    cov = gate["coverage"]
    assert cov["unresolved_data_gap_units"] == 1
    assert cov["prospectively_excluded_units"] == 28
    assert cov["certified_units"] == 32523
    # an unresolved+excluded date is a contradiction in the monthly certifier
    rows = _rows(2014, 6)
    day = sorted(rows)[10]
    rows.pop(day)
    try:
        mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                         rows_by_date=rows,
                         transport_by_date={d: "NATIVE_M1" for d in rows},
                         fallback_by_date={}, decimals=5,
                         excluded_dates={day: "x"},
                         unresolved_dates={day: "y"})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- 10. no denominator shrink ---
def test_no_denominator_shrink() -> None:
    counts = universe_counts()
    assert counts["A_executable_alpha"] == 992
    assert counts["B_price_alpha_only"] == 52
    assert counts["C_total_v3_registry"] == 1044
    # the required day-unit denominator stays 32,552 with the unresolved unit present
    gate = build_gate_v31(
        certified_native_units=32117, certified_tick_fallback_units=406,
        prospectively_excluded_units=28, unresolved_data_gap_units=1,
        required_units=32552, status_counts=LIVE_STATUS_COUNTS, evidence=_ALL_TRUE,
    )
    assert gate["coverage"]["required_units"] == 32552
    assert gate["coverage"]["pending_units"] == 0
    assert gate["coverage"]["accounting_complete"] is True


# --- V3.1 gate verdicts ---
def test_gate_v31_certified_when_all_units_accounted() -> None:
    gate = build_gate_v31(
        certified_native_units=32117, certified_tick_fallback_units=406,
        prospectively_excluded_units=28, unresolved_data_gap_units=1,
        required_units=32552, status_counts=LIVE_STATUS_COUNTS, evidence=_ALL_TRUE,
        unresolved_gap_units=["USDJPY:2010-01-01"],
    )
    assert gate["verdict"] == VERDICT_V31_CERTIFIED
    assert gate["next_gate"] == "V3_ALPHA_DISCOVERY_RUN"
    assert gate["conditions_passed"] == gate["conditions_total"]
    assert gate["artifact_id"] == "V3_1_DATA_CERTIFICATION_GATE_V1"
    assert gate["discovery_run_in_this_session"] is False


def test_gate_v31_not_ready_when_pending_remain() -> None:
    # 5 units still PLANNED: 32112+406 certified + 28 excluded + 1 unresolved + 5 planned
    # = 32552 required; 5 pending acquisition.
    counts = {"CERTIFIED_NATIVE": 32112, "CERTIFIED_TICK_FALLBACK": 406,
              "TERMINAL_DATA_ABSENT": 28, "UNRESOLVED_DATA_GAP": 1, "PLANNED": 5}
    gate = build_gate_v31(
        certified_native_units=32112, certified_tick_fallback_units=406,
        prospectively_excluded_units=28, unresolved_data_gap_units=1,
        required_units=32552, status_counts=counts, evidence=_ALL_TRUE,
    )
    assert gate["verdict"] == VERDICT_V31_NOT_READY
    assert gate["coverage"]["pending_units"] == 5


def test_gate_v31_not_ready_when_unclassified_integrity_failure() -> None:
    # an INTEGRITY_FAILURE that was never classified under the amendment is not admissible
    counts = dict(LIVE_STATUS_COUNTS)
    counts["UNRESOLVED_DATA_GAP"] = 0
    counts["INTEGRITY_FAILURE"] = 1
    gate = build_gate_v31(
        certified_native_units=32117, certified_tick_fallback_units=406,
        prospectively_excluded_units=28, unresolved_data_gap_units=0,
        required_units=32552, status_counts=counts, evidence=_ALL_TRUE,
    )
    assert gate["verdict"] == VERDICT_V31_NOT_READY
    assert gate["conditions"]["structural_admissibility_holds"] is False


# --- amendment freeze identity ---
def test_amendment_is_a_new_freeze_component() -> None:
    ch = component_hashes()
    assert "data_availability_amendment" in ch
    assert len(ch) == 27
    assert ch["data_availability_amendment"] == da.amendment_hash()
    # the NEW freeze identity: the prior hash is NOT preserved
    assert freeze_hash() != OLD_FREEZE_HASH


def test_performance_blindness_evidence_all_zero() -> None:
    ev = da.performance_blindness_evidence()
    for key in ("2018_plus_provider_requests_issued",
                "2018_plus_market_or_outcome_files_opened",
                "V3_PnL_computations", "candidate_outcomes_computed",
                "Sharpe_computed", "rankings_computed", "survivor_tests_computed"):
        assert ev[key] == 0, key
    assert ev["sealed_holdout_cells_all_none"] is True
    assert ev["2018_plus_request_blocked_by_firewall"] is True
    assert ev["discovery_run_in_this_session"] is False
