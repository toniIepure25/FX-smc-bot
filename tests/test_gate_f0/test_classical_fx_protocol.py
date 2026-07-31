from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPOSITORY_ROOT / "results" / "gate_f0"
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "research" / "classical_fx_factors_v1.yaml"

PROGRAM_ID = "FX_CLASSICAL_RISK_PREMIA_V1"
LINEAGE_ID = "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1"
INSTRUMENTS = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
CURRENCIES = ("USD", "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF")
CANDIDATES = (
    "F0_TSMOM_COMPOSITE_V1",
    "F0_SHORT_TERM_REVERSAL_V1",
    "F0_DUAL_HORIZON_TREND_V1",
    "F0_DONCHIAN_BREAKOUT_V1",
    "F0_RATE_DIFFERENTIAL_CARRY_V1",
    "F0_FIXED_MULTI_FACTOR_V1",
)
RATE_SERIES = {
    "USD": "EFFR",
    "EUR": "EONIA_TO_ESTR",
    "GBP": "IUDSOIA",
    "JPY": "FM01'STRDCLUCON",
    "AUD": "RBA_CASH_RATE",
    "NZD": "B2_OVERNIGHT_INTERBANK_CASH_RATE",
    "CAD": "V39079",
    "CHF": "SRFXON3",
}


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((RESULTS_ROOT / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_yaml_freezes_exact_identity_universe_and_family() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["program_id"] == PROGRAM_ID
    assert config["lineage_id"] == LINEAGE_ID
    assert tuple(config["instruments"]) == INSTRUMENTS
    assert tuple(config["currencies"]) == CURRENCIES
    assert tuple(candidate["candidate_id"] for candidate in config["candidates"]) == CANDIDATES
    assert len(config["benchmarks"]["benchmark_ids"]) == 5
    assert config["benchmarks"]["matched_turnover_random_sign"]["seed"] == 1729


def test_factor_family_and_donchian_definition_are_exact() -> None:
    specification = _load_json("factor_family_freeze.json")["frozen_specification"]
    assert specification["candidate_count"] == 6
    assert tuple(row["candidate_id"] for row in specification["candidates"]) == CANDIDATES
    donchian = specification["candidates"][3]
    assert donchian["comparison_price"] == "PREVIOUS_DAILY_RESEARCH_CLOSE"
    assert donchian["upper_channel_price"] == "CERTIFIED_DAILY_RESEARCH_HIGH"
    assert donchian["lower_channel_price"] == "CERTIFIED_DAILY_RESEARCH_LOW"
    assert donchian["channel_window_ends_trading_days_before_comparison_close"] == 1
    weights = specification["candidates"][5]["factor_risk_contribution_targets"]
    assert list(weights.values()) == [0.25, 0.15, 0.2, 0.15, 0.25]
    assert sum(weights.values()) == 1.0


def test_rate_registry_is_complete_and_point_in_time() -> None:
    registry = _load_json("rate_series_registry.json")
    rows = registry["frozen_specification"]["series"]
    assert {row["currency"]: row["series_identifier"] for row in rows} == RATE_SERIES
    assert all(row["publication_timestamp"] for row in rows)
    assert all(row["effective_timestamp"] for row in rows)
    rules = registry["frozen_specification"]["global_point_in_time_rules"]
    assert rules["revised_value_backfill_before_original_publication_allowed"] is False
    assert rules["unproven_timestamp_action"] == "TREAT_AS_MISSING"


def test_temporal_partition_and_market_contract_are_exact() -> None:
    partitions = _load_json("time_partition_freeze.json")["frozen_specification"]["partitions"]
    assert partitions["warmup_only"] == {
        "start": "2010-01-01",
        "end": "2010-12-31",
        "outcome_adjudication_allowed": False,
    }
    assert partitions["development"]["end"] == "2016-12-31"
    assert partitions["internal_validation"]["end"] == "2019-12-31"
    assert partitions["independent_replication"]["end"] == "2022-12-31"
    assert partitions["quarantined_interval"]["access_allowed"] is False
    assert partitions["quarantined_interval"]["enumeration_allowed"] is False

    market = _load_json("market_data_contract.json")["frozen_specification"]
    assert market["provider"] == "DUKASCOPY_BI5_BID_AND_ASK"
    assert market["same_bar_ambiguity"] == "ADVERSE_FIRST"
    assert market["price_forward_fill_allowed"] is False
    assert market["weekend_rule"]["friday_deadline_local_time"] == "16:55"
    assert market["weekend_rule"]["timezone"] == "America/New_York"


def test_previous_lineage_digests_match_tracked_closure_artifacts() -> None:
    inheritance = _load_json("previous_lineage_inheritance.json")
    for row in inheritance["inherited_artifact_digests"]:
        path = REPOSITORY_ROOT / row["repository_relative_path"]
        assert _sha256(path) == row["sha256"]
    assert inheritance["inheritance_rules"]["prior_results_used_as_predictive_inputs"] is False
    assert inheritance["inheritance_rules"]["prior_candidates_reopened"] is False


def test_clean_room_artifact_contains_no_absolute_path() -> None:
    artifact_path = RESULTS_ROOT / "clean_room_root.json"
    artifact = _load_json(artifact_path.name)
    text = artifact_path.read_text(encoding="utf-8")
    assert artifact["status"] == "PASS"
    assert artifact["frozen_specification"]["absolute_path_recorded"] is False
    assert "D:\\" not in text
    assert "C:\\" not in text


def test_all_preregistration_artifacts_have_exact_identity() -> None:
    for path in RESULTS_ROOT.glob("*.json"):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert artifact["program_id"] == PROGRAM_ID
        assert artifact["lineage_id"] == LINEAGE_ID
