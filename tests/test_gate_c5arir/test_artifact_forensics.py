from __future__ import annotations

import json

from fx_smc_bot.research.gate_c5arir import (
    C5AR_DECISION,
    RECONCILIATION_ID,
    CompactSources,
    c5b_handoff_ready,
    canonical_json_bytes,
    canonical_json_sha256,
    classify_hash_match,
    overlay_preserves_lock,
    raw_sha256,
    regenerate_adjudication,
    scientific_changes,
    scientific_projection,
    semantic_diff,
    validate_holdout_closed,
)


def _compact_sources() -> CompactSources:
    hashes = {
        "results/gate_c5ar/post_validation_lock.json": "lock-hash",
        "results/gate_c5adqr/validation_data_quality.json": "dqr-hash",
        "results/gate_c5ar/control_matching_audit.json": "matching-hash",
        "results/gate_c5ar/validation_primary_estimand.json": "primary-hash",
        "results/gate_c5ar/validation_inference.json": "inference-hash",
        "results/gate_c5ar/validation_placebo.json": "placebo-hash",
        "results/gate_c5ar/holdout_integrity.json": "holdout-hash",
    }
    return CompactSources(
        primary={
            "mean_event_executable_markout_points": 11.33724832214778,
            "mean_event_minus_control_points": 27.453020134228165,
        },
        inference={
            "ci95_day_cluster_bootstrap": [14.784214406740844, 40.27386831699497],
            "raw_permutation_p_value": 0.004497751124437781,
        },
        placebo={"placebo_reproduces_relative_resilience": False},
        matching={
            "balance_pass": True,
            "exact_key_relaxations": 0,
            "post_match_smd": {"atr": 0.03, "spread": 0.02},
            "successfully_matched_events": 1192,
        },
        holdout={"status": "PASS"},
        hashes=hashes,
    )


def test_raw_and_canonical_json_hashing_are_distinct_when_serialization_differs() -> None:
    payload = {"b": 2, "a": 1}
    pretty = b'{\n  "b": 2,\n  "a": 1\n}\n'

    assert raw_sha256(pretty) != canonical_json_sha256(payload)
    assert canonical_json_bytes(payload) == b'{"a":1,"b":2}'


def test_canonicalization_preserves_complete_fields() -> None:
    payload = {"z": {"keep": True}, "a": [3, 2, 1], "hash": "abc"}
    canonical = json.loads(canonical_json_bytes(payload).decode("utf-8"))

    assert canonical == payload


def test_semantic_diff_classifies_source_reference_only_change() -> None:
    old = {"criteria": [{"source_hash": "old", "observed_value": 1}]}
    new = {"criteria": [{"source_hash": "new", "observed_value": 1}]}

    changes = semantic_diff(old, new)

    assert changes == [
        {
            "json_path": "$.criteria[0].source_hash",
            "old_value": "old",
            "new_value": "new",
            "classification": "SOURCE_REFERENCE_ONLY",
            "scientific_relevance": False,
        }
    ]


def test_scientific_field_change_detection_marks_observed_value() -> None:
    changes = semantic_diff(
        {"criteria": [{"observed_value": 1}]},
        {"criteria": [{"observed_value": 2}]},
    )

    assert scientific_changes(changes)[0]["classification"] == "SCIENTIFIC_VALUE_CHANGE"


def test_criterion_regeneration_from_compact_sources() -> None:
    adjudication = regenerate_adjudication(_compact_sources())

    assert len(adjudication["criteria"]) == 11
    assert adjudication["final_decision"] == C5AR_DECISION
    assert adjudication["criteria"][8]["criterion"] == "mean_absolute_event_executable_markout"
    assert adjudication["criteria"][8]["passed"] is False


def test_stale_lock_detection_by_semantic_projection() -> None:
    current = regenerate_adjudication(_compact_sources())
    stale = json.loads(json.dumps(current))
    stale["criteria"][0]["source_hash"] = "previous-lock-hash"

    assert scientific_projection(stale) == scientific_projection(current)
    assert semantic_diff(stale, current)[0]["classification"] == "SOURCE_REFERENCE_ONLY"


def test_wrong_hash_mode_detection_for_crlf_lock() -> None:
    payload = {"status": "PASS"}
    data = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
    expected = raw_sha256(data.replace(b"\n", b"\r\n"))

    assert classify_hash_match(expected, data, payload) == "crlf_normalized_sha256"


def test_lock_overlay_immutability() -> None:
    original_lock = {
        "final_decision": C5AR_DECISION,
        "statement": "No validation-informed modification is permitted.",
        "status": "LOCKED",
    }
    overlay = {
        "overlay_id": RECONCILIATION_ID,
        "preserved_original_lock_fields": original_lock.copy(),
    }

    assert overlay_preserves_lock(original_lock, overlay)


def test_historical_lock_preservation_rejects_missing_fields() -> None:
    original_lock = {"final_decision": C5AR_DECISION, "statement": "x", "status": "LOCKED"}
    overlay = {"overlay_id": RECONCILIATION_ID, "preserved_original_lock_fields": {}}

    assert not overlay_preserves_lock(original_lock, overlay)


def test_authoritative_artifact_precedence_prefers_regenerated_science_over_lock_hash() -> None:
    current = regenerate_adjudication(_compact_sources())
    stale = json.loads(json.dumps(current))
    stale["criteria"][0]["source_hash"] = "older"

    precedence = [
        "frozen protocol and decision matrix",
        "immutable compact primary source artifacts",
        "deterministic adjudication regeneration",
        "committed historical artifact",
        "post-validation lock reference",
    ]

    assert precedence[-1] == "post-validation lock reference"
    assert scientific_projection(stale) == scientific_projection(current)


def test_c5b_handoff_requires_reconciliation_overlay() -> None:
    overlay = {"reconciliation_overlay_hash": "overlay-hash"}
    handoff = {
        "status": "READY_TO_RESUME_C5B_PHASE_0",
        "reconciliation_overlay_hash": "overlay-hash",
        "require_c5b_to_validate_original_lock_and_overlay": True,
    }

    assert c5b_handoff_ready(handoff, overlay)


def test_holdout_access_rejection() -> None:
    closed = validate_holdout_closed({"status": "PASS"})
    opened = validate_holdout_closed({"status": "PASS", "holdout_events_detected": True})

    assert closed["status"] == "PASS"
    assert opened["status"] == "FAIL"
    assert opened["violations"] == ["holdout_events_detected"]
