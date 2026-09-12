"""Lightweight tests for the V4 pilot design artifact.
No market data. No model fit. No backtest.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

REPO = Path(r"D:\ComputaCenter\FX-smc-bot")
DESIGN_PATH = REPO / "results" / "gate_v4" / "v4_minimal_microstructure_pilot_design.json"
CONTRACT_PATH = REPO / "results" / "gate_v4" / "v4_new_data_capability_contract_v2.json"

SEED = "V4_P1_SAMPLE_V1"
INSTRUMENTS = ["6E", "6J", "6B"]
DEV_START = date(2016, 1, 1)
DEV_END = date(2016, 9, 30)
IVAL_START = date(2016, 10, 1)
IVAL_END = date(2017, 3, 31)
EXTVAL_START = date(2017, 4, 1)
EXTVAL_END = date(2017, 8, 31)
HOLDOUT_START = date(2017, 9, 1)
HOLDOUT_END = date(2017, 12, 31)
SEALED_START = date(2018, 1, 1)


def _load_design() -> dict:
    return json.loads(DESIGN_PATH.read_text())


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def _sample_hash(instrument: str, d: date) -> str:
    s = f"{SEED}|{instrument}|{d.isoformat()}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _iter_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class TestSampling:
    def test_hash_deterministic(self):
        h1 = _sample_hash("6E", date(2016, 1, 15))
        h2 = _sample_hash("6E", date(2016, 1, 15))
        assert h1 == h2

    def test_hash_differs_by_instrument(self):
        h1 = _sample_hash("6E", date(2016, 1, 15))
        h2 = _sample_hash("6J", date(2016, 1, 15))
        assert h1 != h2

    def test_hash_differs_by_date(self):
        h1 = _sample_hash("6E", date(2016, 1, 15))
        h2 = _sample_hash("6E", date(2016, 1, 16))
        assert h1 != h2

    def test_seed_string_frozen(self):
        d = _load_design()
        assert d["sampling"]["seed_string"] == SEED

    def test_days_per_month_frozen(self):
        d = _load_design()
        assert d["sampling"]["days_per_instrument_month"] == 4


class TestNo2018Dates:
    def test_no_chronology_period_touches_2018(self):
        d = _load_design()
        for role, period in d["staged_access"]["stage_P1_accessible"].items():
            assert date.fromisoformat(period["end"]) < SEALED_START, (
                f"{role} touches 2018+"
            )
        for role, period in d["staged_access"]["stage_P1_UNOPENED"].items():
            assert date.fromisoformat(period["end"]) < SEALED_START, (
                f"{role} touches 2018+"
            )
        for role, period in d["staged_access"]["SEALED"].items():
            if role == "2018_plus":
                assert date.fromisoformat(period["start"]) >= SEALED_START
            else:
                assert date.fromisoformat(period["end"]) < SEALED_START

    def test_firewall_rejects_2018(self):
        d = _load_design()
        assert "all 2018+ dates" in d["firewall"]["reject"]


class TestRoleFirewall:
    def test_extval_not_accessible_in_p1(self):
        d = _load_design()
        assert "external_validation" in d["staged_access"]["stage_P1_UNOPENED"]

    def test_holdout_sealed(self):
        d = _load_design()
        assert "final_holdout" in d["staged_access"]["SEALED"]

    def test_firewall_counters_zero(self):
        d = _load_design()
        counters = d["firewall"]["counters"]
        assert counters["external_validation_requests"] == 0
        assert counters["external_validation_reads"] == 0
        assert counters["v4_final_holdout_requests"] == 0
        assert counters["v4_final_holdout_reads"] == 0
        assert counters["2018_plus_requests"] == 0
        assert counters["2018_plus_reads"] == 0


class TestHashReproducibility:
    def test_pilot_design_hash_reproducible(self):
        d = _load_design()
        comp_hashes = d["component_hashes"]
        agg_blob = json.dumps(comp_hashes, sort_keys=True, separators=(",", ":"))
        recomputed = hashlib.sha256(agg_blob.encode("utf-8")).hexdigest()
        assert recomputed == d["pilot_design_hash"]

    def test_capability_contract_hash_matches(self):
        d = _load_design()
        c = _load_contract()
        assert d["capability_contract_hash"] == c["capability_contract_hash"]


class TestTargetFeatureNonOverlap:
    def test_targets_start_after_feature_cutoff(self):
        d = _load_design()
        assert "strictly after feature cutoff" in d["targets"]["definition"]
        assert "No use of the target event" in d["windows"]["constraint"]

    def test_confirmatory_targets_frozen(self):
        d = _load_design()
        conf = d["targets"]["confirmatory"]
        assert conf["T1"]["horizon"] == "5 seconds"
        assert conf["T2"]["horizon"] == "30 seconds"
        assert conf["T3"]["horizon"] == "100 events"


class TestDayLevelInference:
    def test_inference_unit_is_day(self):
        d = _load_design()
        assert "instrument-session-day" in d["metrics"]["inference_unit"]

    def test_bootstrap_replications(self):
        d = _load_design()
        assert d["inference"]["replications"] == 2000

    def test_holm_for_predictive(self):
        d = _load_design()
        assert "Holm" in d["inference"]["multiplicity"]


class TestPassFail:
    def test_all_criteria_present(self):
        d = _load_design()
        criteria = d["pass_fail"]["criteria"]
        assert len(criteria) == 4
        assert "Holm" in criteria[0]
        assert "50%" in criteria[2]
        assert "2 of 3" in criteria[3]


class TestModel:
    def test_ridge_alpha_grid(self):
        d = _load_design()
        assert d["model"]["alpha_grid"] == [0.01, 0.1, 1.0, 10.0, 100.0]

    def test_no_forbidden_models(self):
        d = _load_design()
        forbidden = d["model"]["forbidden"]
        assert "trees" in forbidden
        assert "neural nets" in forbidden
        assert "boosting" in forbidden


class TestGoNoGo:
    def test_proceed_verdict(self):
        d = _load_design()
        assert (
            d["go_no_go"]["proceed_verdict"]
            == "V4_MINIMAL_PILOT_INCREMENTAL_INFORMATION_FOUND"
        )

    def test_stop_verdict(self):
        d = _load_design()
        assert (
            d["go_no_go"]["stop_verdict"]
            == "V4_MINIMAL_PILOT_NO_INCREMENTAL_MICROSTRUCTURE_INFORMATION"
        )

    def test_terminal_verdict(self):
        d = _load_design()
        assert (
            d["terminal_verdict"]
            == "V4_MINIMAL_MICROSTRUCTURE_PILOT_DESIGN_FROZEN"
        )
