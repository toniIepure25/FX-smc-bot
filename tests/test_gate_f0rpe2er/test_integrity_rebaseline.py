from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2er"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_scientific_protocol_is_inherited_without_changes() -> None:
    lock = _load("protocol_inheritance_lock.json")

    assert lock["program_id"] == "FX_CLASSICAL_RISK_PREMIA_V2"
    assert lock["lineage_id"] == "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V2"
    assert lock["failed_tip_sha"] == "2a2a42fd9be080ca36cc7c5f9ae5e574c4b1a2a2"
    assert lock["scientific_values_changed"] is False
    assert lock["permitted_delta"] == "INFRASTRUCTURE_AND_INTEGRITY_HANDLING_ONLY"

    hashes = lock["locked_artifact_sha256"]
    assert isinstance(hashes, dict)
    for relative_path, expected in hashes.items():
        assert (
            manifest_file_sha256(
                ROOT / relative_path,
                SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            )
            == expected
        ), relative_path


def test_rebaseline_never_represents_2023_2025_as_untouched() -> None:
    rebaseline = _load("integrity_rebaseline.json")

    assert rebaseline["relationship"] == (
        "SCIENTIFIC_PROTOCOL_INHERITANCE_WITH_NEW_FUTURE_ONLY_INTEGRITY_BASELINE"
    )
    assert rebaseline["historical_2023_2025_status"] == (
        "QUARANTINED_FROM_ALL_SELECTION_REPLICATION_AND_CONFIRMATORY_USE"
    )
    assert rebaseline["historical_2023_2025_untouched_claim"] is False
    assert rebaseline["historical_quarantined_data_used"] is False
    assert rebaseline["historical_quarantined_data_persisted"] is False


def test_confirmatory_holdout_is_future_only_without_backfill() -> None:
    rebaseline = _load("integrity_rebaseline.json")

    assert rebaseline["future_confirmatory_start"] == (
        "FIRST_COMPLETE_FX_TRADING_DAY_AFTER_FINAL_PORTFOLIO_FREEZE"
    )
    assert rebaseline["future_confirmatory_status"] == "NOT_YET_GENERATED_OR_ACCESSED"
    assert rebaseline["future_confirmatory_minimum_eligible_trading_days"] == 252
    assert rebaseline["future_confirmatory_minimum_calendar_months"] == 12
    assert rebaseline["both_future_conditions_required"] is True
    assert rebaseline["backfill_permitted"] is False


def test_clean_room_artifact_does_not_commit_an_absolute_path() -> None:
    clean_room = _load("clean_room_root.json")
    configured_path = clean_room["configured_path_template"]

    assert configured_path == "<repository-parent>/FX-smc-bot-local-data/f0rpe2er_v2"
    assert clean_room["absolute_path_committed"] is False
    assert clean_room["outside_repository"] is True
    assert clean_room["old_roots_inspected"] is False
    assert not Path(configured_path).is_absolute()


def test_documentation_boundary_forbids_numerical_observations() -> None:
    boundary = _load("documentation_data_boundary.json")
    metadata = boundary["metadata_documentation_class"]
    numerical = boundary["numerical_data_class"]

    assert isinstance(metadata, dict)
    assert metadata["class"] == "A"
    assert metadata["numerical_observations_permitted"] is False
    assert metadata["search_result_snippets_with_numerical_rows_permitted"] is False
    assert metadata["live_dashboard_tables_permitted"] is False
    assert isinstance(numerical, dict)
    assert numerical["class"] == "B"
    assert numerical["server_side_date_bounds_required"] is True
    assert numerical["response_date_firewall_required"] is True
    assert boundary["network_numerical_access_started"] is False


def test_allowlist_is_bounded_to_amended_universe_and_pre_2023_data() -> None:
    allowlist = _load("official_source_allowlist.json")
    records = allowlist["records"]

    assert isinstance(records, list)
    assert allowlist["record_count"] == 8
    assert allowlist["adapter_count"] == 7
    assert allowlist["nzd_allowlisted"] is False
    assert allowlist["nzdusd_allowlisted"] is False
    assert {record["currency"] for record in records} == {
        "USD",
        "EUR",
        "GBP",
        "AUD",
        "JPY",
        "CAD",
        "CHF",
    }
    for record in records:
        assert date.fromisoformat(record["maximum_authorized_date"]) <= date(2022, 12, 31)
        assert record["server_side_date_parameters"]
        assert record["series_parameter"]
        assert record["response_date_enforcement"] == "ATOMIC_FIREWALL"
        assert record["eligibility_status"] == "PENDING_LIVE_CERTIFICATION"

