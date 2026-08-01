from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsrlpaeursr"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8-sig"))


def test_predecessor_block_and_protocol_are_preserved() -> None:
    predecessor = _load("predecessor_inheritance.json")
    protocol = _load("protocol_inheritance_lock.json")

    assert predecessor["predecessor_decision"] == "BLOCKED_BY_RATE_SOURCE_ACCESS"
    assert predecessor["blocking_adapter"] == "ECB_EONIA_ESTR_V2"
    assert predecessor["blocking_source_series"] == "EONIA"
    assert predecessor["http_status"] == "OFFICIAL_ENDPOINT_HTTP_STATUS_404"
    assert predecessor["ecb_snapshots_persisted"] == 0
    assert predecessor["ecb_numerical_rows_parsed"] == 0
    assert predecessor["market_requests"] == 0

    assert protocol["lock_id"] == "F0RPE2ERUSDSRLPAEURSR_PROTOCOL_INHERITANCE_V1"
    assert protocol["scientific_parameters_changed"] is False


def test_ecb_identities_and_corrected_series_are_frozen_before_parse() -> None:
    dataflow = _load("ecb_dataflow_identity.json")
    dsd = _load("ecb_dsd_identity.json")
    series = _load("eur_series_identity_freeze.json")
    endpoint = _load("ecb_endpoint_reconciliation.json")

    assert dataflow["EON"] == dataflow["EST"] == "PASS"
    assert dsd["EON_DSD"] == dsd["EST_DSD"] == "PASS"
    assert series["eonia_source_identity"] == "EON.D.EONIA_TO.RATE"
    assert series["estr_source_identity"] == "EST.B.EU000A2X2A25.WT"
    assert "EON.B.EU000A2X2A25.WT" in series["explicit_rejections"]

    assert endpoint["reconciliation_id"] == "ECB_EONIA_ESTR_SOURCE_RECONCILIATION_V1"
    assert endpoint["eonia_endpoint"]["base_endpoint"].endswith("/EON/D.EONIA_TO.RATE")
    assert endpoint["estr_endpoint"]["base_endpoint"].endswith("/EST/B.EU000A2X2A25.WT")
    assert endpoint["invalid_eon_key_rejected"] == "EON.B.EU000A2X2A25.WT"


def test_sdmx_schema_descriptors_are_value_blind_and_distinct() -> None:
    eonia = _load("eonia_schema_descriptor.json")
    estr = _load("estr_schema_descriptor.json")
    difference = _load("eur_schema_difference.json")
    reconciliation = _load("eur_schema_reconciliation.json")

    assert eonia["unique_KEY_values"] == ["EON.D.EONIA_TO.RATE"]
    assert estr["unique_KEY_values"] == ["EST.B.EU000A2X2A25.WT"]
    assert eonia["unique_FREQ_values"] == ["D"]
    assert estr["unique_FREQ_values"] == ["B"]
    assert eonia["schema_fingerprint"] != estr["schema_fingerprint"]
    assert difference["status"] == "PASS_DISTINCT_EXPLICIT_SCHEMAS"
    assert reconciliation["status"] == "PASS"
    assert reconciliation["eonia_mapping"]["OBS_VALUE / 100"] == "annualized_decimal_rate"
    assert reconciliation["estr_mapping"]["OBS_VALUE / 100"] == "annualized_decimal_rate"

    serialized = json.dumps([eonia, estr, difference, reconciliation], sort_keys=True)
    assert '"OBS_VALUE"' in serialized
    for forbidden in ("-0.", "2016-01-04,", "2019-10-01,"):
        assert forbidden not in serialized
    assert eonia["obs_value_values_committed"] == 0
    assert estr["row_level_data_committed"] == 0
