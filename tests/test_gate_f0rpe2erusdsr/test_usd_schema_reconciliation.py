from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsr"


def _load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_discovery_freezes_two_exact_schema_fingerprints() -> None:
    legacy = _load("usd_legacy_schema_descriptor.json")
    modern = _load("usd_modern_schema_descriptor.json")
    difference = _load("usd_schema_difference.json")

    assert legacy["descriptor"]["schema_fingerprint"] == (
        "da2935b38af012e67bf97d5900d44c64a9495b454262c698ae8827464cf7d00e"
    )
    assert modern["descriptor"]["schema_fingerprint"] == (
        "a002a5c557f22d51e9ac2171b981472589800ffe8a03d481629bd8844c165dff"
    )
    assert difference["classification"] == "TWO_EXPLICITLY_VERSIONED_SCHEMAS"
    assert difference["permissive_arbitrary_key_guessing_allowed"] is False
    assert difference["total_official_requests"] == 2
    assert difference["total_local_snapshots"] == 2
    assert difference["numerical_rows_exposed_to_parser"] == 0


def test_discovery_descriptors_are_bounded_and_value_free() -> None:
    for name, start, end, count in (
        ("usd_legacy_schema_descriptor.json", "2016-01-04", "2016-01-08", 5),
        ("usd_modern_schema_descriptor.json", "2016-03-01", "2016-03-04", 8),
    ):
        artifact = _load(name)
        descriptor = artifact["descriptor"]

        assert descriptor["minimum_response_date"] == start
        assert descriptor["maximum_response_date"] == end
        assert descriptor["row_count"] == count
        assert artifact["all_discovered_dates_authorized"] is True
        assert artifact["numerical_rows_exposed_to_parser"] == 0
        assert artifact["snapshot_location"] == "EXTERNAL_CLEAN_ROOM_NOT_GIT"


def test_reconciliation_maps_only_exact_effr_rows_and_rejects_unknown_shapes() -> None:
    reconciliation = _load("usd_schema_reconciliation.json")

    assert reconciliation["reconciliation_id"] == (
        "NY_FED_EFFR_SCHEMA_RECONCILIATION_V1"
    )
    assert reconciliation["status"] == "FROZEN_BEFORE_USD_RATE_PERSISTENCE"
    assert reconciliation["adapter_authorization"]["required_row_series_identity"] == (
        "EFFR"
    )
    assert reconciliation["unknown_schema_fingerprint_policy"] == "REJECT_ATOMICALLY"
    assert reconciliation["arbitrary_key_guessing_allowed"] is False
    assert reconciliation["internal_normalized_fields_claimed_as_official_fields"] == []
    assert reconciliation["rate_versions_persisted"] == 0


def test_legacy_publication_instant_is_not_fabricated() -> None:
    reconciliation = _load("usd_schema_reconciliation.json")
    legacy = reconciliation["supported_schemas"][0]
    mapping = legacy["normalized_rate_version_mapping"]

    assert legacy["schema_role"] == "LEGACY_PRE_FIELD_CHANGE_SCHEMA"
    assert legacy["rate_version_emission_allowed"] is False
    assert mapping["publication_timestamp"].startswith("NOT_CONSTRUCTIBLE")
    assert mapping["effective_timestamp"].startswith("NOT_CONSTRUCTIBLE")
    assert mapping["strategy_availability_timestamp"].startswith("NOT_CONSTRUCTIBLE")
    assert reconciliation["publication_timestamp_inferred_from_fetch_time"] is False
    assert reconciliation["publication_timestamp_inferred_from_file_metadata"] is False
    assert reconciliation["publication_timestamp_inferred_from_observation_date_alone"] is False
