"""Tests for V4 pilot metadata cost preflight gate.
No market data. No API calls. No model fit.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

REPO = Path(r"D:\ComputaCenter\FX-smc-bot")
MANIFEST_PATH = REPO / "results" / "gate_v4" / "v4_p1_sample_manifest.json"
PREFLIGHT_PATH = REPO / "results" / "gate_v4" / "v4_pilot_metadata_cost_preflight.json"
DESIGN_PATH = REPO / "results" / "gate_v4" / "v4_minimal_microstructure_pilot_design.json"
CONTRACT_PATH = REPO / "results" / "gate_v4" / "v4_new_data_capability_contract_v2.json"
PREFLIGHT_SCRIPT = REPO / "scripts" / "v4" / "pilot_metadata_preflight.py"

SEED = "V4_P1_SAMPLE_V1"
SEALED_START = date(2018, 1, 1)
EXTVAL_START = date(2017, 4, 1)
HOLDOUT_START = date(2017, 9, 1)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


class TestSamplingDeterminism:
    def test_manifest_hash_deterministic(self):
        m = _load(MANIFEST_PATH)
        entries = m["entries"]
        blob = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        recomputed = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        assert recomputed == m["manifest_hash"]

    def test_selection_hash_format(self):
        m = _load(MANIFEST_PATH)
        for e in m["entries"][:10]:
            h = e["selection_hash"]
            assert len(h) == 64
            int(h, 16)  # valid hex

    def test_seed_frozen(self):
        m = _load(MANIFEST_PATH)
        assert m["seed"] == SEED


class TestManifestFirewall:
    def test_no_2018_dates(self):
        m = _load(MANIFEST_PATH)
        for e in m["entries"]:
            d = date.fromisoformat(e["date"])
            assert d < SEALED_START, f"2018+ date in manifest: {e['date']}"

    def test_no_extval_dates(self):
        m = _load(MANIFEST_PATH)
        for e in m["entries"]:
            d = date.fromisoformat(e["date"])
            assert d < EXTVAL_START, f"Ext-val date in manifest: {e['date']}"

    def test_no_holdout_dates(self):
        m = _load(MANIFEST_PATH)
        for e in m["entries"]:
            d = date.fromisoformat(e["date"])
            assert d < HOLDOUT_START, f"Holdout date in manifest: {e['date']}"

    def test_roles_valid(self):
        m = _load(MANIFEST_PATH)
        valid_roles = {"development", "internal_validation"}
        for e in m["entries"]:
            assert e["role"] in valid_roles

    def test_instruments_valid(self):
        m = _load(MANIFEST_PATH)
        valid_inst = {"6E", "6J", "6B"}
        for e in m["entries"]:
            assert e["instrument"] in valid_inst


class TestPreflightFirewall:
    def test_all_counters_zero(self):
        p = _load(PREFLIGHT_PATH)
        fw = p["firewall"]
        for key, val in fw.items():
            assert val == 0, f"Firewall counter {key} = {val}, expected 0"

    def test_no_market_outcomes(self):
        p = _load(PREFLIGHT_PATH)
        assert p["firewall"]["market_outcomes_opened"] == 0
        assert p["firewall"]["historical_mbp10_payload_requests"] == 0
        assert p["firewall"]["historical_trade_payload_requests"] == 0


class TestMetadataOnlyWhitelist:
    def test_preflight_script_exists(self):
        assert PREFLIGHT_SCRIPT.exists()

    def test_no_forbidden_endpoints_in_script(self):
        content = PREFLIGHT_SCRIPT.read_text()
        # Check that forbidden endpoints are not CALLED (only listed in guard)
        for forbidden in ["client.timeseries", "client.batch",
                          ".get_range(", ".get_subscription(",
                          ".to_df()", ".to_ndarray()"]:
            assert forbidden not in content, (
                f"Forbidden endpoint call '{forbidden}' found in preflight script"
            )

    def test_forbidden_methods_defined(self):
        content = PREFLIGHT_SCRIPT.read_text()
        assert "FORBIDDEN_METHODS" in content
        assert "get_range" in content
        assert "batch" in content


class TestHashReproducibility:
    def test_preflight_hash_reproducible(self):
        m = _load(MANIFEST_PATH)
        # Verify manifest hash matches
        entries = m["entries"]
        blob = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == m["manifest_hash"]

    def test_capability_hash_chain(self):
        p = _load(PREFLIGHT_PATH)
        d = _load(DESIGN_PATH)
        c = _load(CONTRACT_PATH)
        assert p["capability_contract_hash"] == c["capability_contract_hash"]
        assert p["pilot_design_hash"] == d["pilot_design_hash"]
        assert p["manifest_hash"] == m_hash()


def m_hash() -> str:
    m = _load(MANIFEST_PATH)
    return m["manifest_hash"]


class TestBudgetScenarios:
    def test_full_p1_is_total(self):
        p = _load(PREFLIGHT_PATH)
        m = _load(MANIFEST_PATH)
        assert p["budget_scenarios"]["FULL_P1"]["instrument_days"] == m["total_instrument_days"]

    def test_scenarios_are_fractions(self):
        p = _load(PREFLIGHT_PATH)
        bs = p["budget_scenarios"]
        assert bs["SCENARIO_50"]["instrument_days"] == bs["FULL_P1"]["instrument_days"] // 2
        assert bs["SCENARIO_25"]["instrument_days"] == bs["FULL_P1"]["instrument_days"] // 4

    def test_scenarios_not_scientific(self):
        p = _load(PREFLIGHT_PATH)
        for key in ["SCENARIO_50", "SCENARIO_25"]:
            assert "NOT the scientific sample" in p["budget_scenarios"][key]["note"]


class TestTerminalVerdict:
    def test_blocked_verdict(self):
        p = _load(PREFLIGHT_PATH)
        assert p["terminal_verdict"] == "V4_PILOT_METADATA_PREFLIGHT_BLOCKED_BY_API_CREDENTIAL"

    def test_api_key_missing(self):
        p = _load(PREFLIGHT_PATH)
        assert p["api_key_status"] == "MISSING"

    def test_next_gate_defined(self):
        p = _load(PREFLIGHT_PATH)
        assert p["next_gate_if_ready"] == "V4_PILOT_ACQUISITION_AUTHORIZATION"
