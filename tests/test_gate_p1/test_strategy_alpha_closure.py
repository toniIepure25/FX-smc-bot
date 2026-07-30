from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fx_smc_bot.research.strategy_alpha_closure import (
    EXPECTED_CLAIM_STATUSES,
    EXPECTED_RESULTS,
    QUARANTINE_ID,
    QUARANTINE_STATUS,
    REQUIRED_FUTURE_CONDITIONS,
    REQUIRED_SEAL_PROHIBITIONS,
    SEAL_ID,
    SEAL_STATUS,
    build_claim_matrix,
    detect_prohibited_changed_paths,
    payload_hash_without,
    reproduce_aggregate_results,
    validate_claim_matrix,
    validate_no_forward_handoff,
    validate_posthoc_quarantine,
    validate_strategy_alpha_lineage_seal,
)

REPO = Path(__file__).resolve().parents[2]
A1A = REPO / "results" / "gate_p0rdcra1a"
P1 = REPO / "results" / "gate_p1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_aggregate_reproduction_matches_frozen_results() -> None:
    reproduced = reproduce_aggregate_results(
        load_json(A1A / "candidate_results.json"),
        load_json(A1A / "benchmark_alpha_results.json"),
        load_json(A1A / "candidate_eligibility_adjudication.json"),
        load_json(A1A / "execution_sample_manifest.json"),
    )

    assert reproduced["status"] == "PASS"
    assert reproduced["trade_count"] == 3991
    assert all(check["match"] for check in reproduced["checks"])
    assert reproduced["primary_candidate"] is None
    assert reproduced["secondary_candidate"] is None


def test_exact_candidate_metrics_and_tiers_are_locked() -> None:
    reproduction = load_json(P1 / "final_result_reproduction.json")
    observed = {row["candidate_id"]: row for row in reproduction["candidate_results"]}

    for candidate_id, expected in EXPECTED_RESULTS.items():
        assert observed[candidate_id]["trade_count"] == expected["trade_count"]
        assert observed[candidate_id]["mean_net_r"] == expected["mean_net_r"]
        assert observed[candidate_id]["day_cluster_ci"] == expected["day_cluster_ci"]
        assert observed[candidate_id]["profit_factor"] == expected["profit_factor"]
        assert observed[candidate_id]["sharpe"] == expected["sharpe"]
        assert observed[candidate_id]["tier"] == expected["tier"]


def test_claim_matrix_identities_and_statuses_are_exact() -> None:
    claims = build_claim_matrix()
    validation = validate_claim_matrix(claims)

    assert validation["status"] == "PASS"
    assert validation["observed_statuses"] == EXPECTED_CLAIM_STATUSES


def test_event_and_strategy_estimands_remain_distinct() -> None:
    audit = load_json(P1 / "event_to_strategy_translation_audit.json")

    assert audit["event_estimand"] == "post-event markout relative to matched controls"
    assert audit["strategy_estimand"] == (
        "net executable R from a fully specified trading policy"
    )
    assert "not contradictory" in audit["interpretation"]


def test_negative_controls_are_adjudicated_without_inversion() -> None:
    audit = load_json(P1 / "negative_control_adjudication.json")

    assert audit["direction_flip"]["adjudication"] == "HYPOTHESIS_GENERATING_ONLY"
    assert audit["direction_flip"]["inverted_strategy_created"] is False
    assert all(
        result["mean_net_r"] > 0
        for result in audit["direction_flip"]["results"].values()
    )
    assert all(
        result["mean_net_r"] < 0 for result in audit["one_bar_delay"]["results"].values()
    )
    assert all(
        result["mean_net_r"] < 0 for result in audit["two_bar_delay"]["results"].values()
    )
    assert not any(audit["leave_one_year_out"].values())
    assert audit["pbo"] == 0.86
    assert set(audit["holm_adjusted_p_values"].values()) == {1.0}


def test_posthoc_quarantine_is_complete_and_tamper_evident() -> None:
    quarantine = load_json(P1 / "posthoc_hypothesis_quarantine.json")
    tampered = {**quarantine, "hypotheses": quarantine["hypotheses"][:-1]}

    assert quarantine["quarantine_id"] == QUARANTINE_ID
    assert len(quarantine["hypotheses"]) == 10
    assert {item["status"] for item in quarantine["hypotheses"]} == {QUARANTINE_STATUS}
    assert validate_posthoc_quarantine(quarantine)["status"] == "PASS"
    assert validate_posthoc_quarantine(tampered)["status"] == "FAIL"


def test_lineage_seal_identity_hash_and_guards_are_immutable() -> None:
    seal = load_json(P1 / "strategy_alpha_lineage_seal.json")
    tampered = {**seal, "status": "REOPENED"}

    assert seal["seal_id"] == SEAL_ID
    assert seal["status"] == SEAL_STATUS
    assert all(item in seal["prohibitions"] for item in REQUIRED_SEAL_PROHIBITIONS)
    assert all(
        item in seal["permitted_future_work_requires"]
        for item in REQUIRED_FUTURE_CONDITIONS
    )
    assert validate_strategy_alpha_lineage_seal(seal)["status"] == "PASS"
    assert validate_strategy_alpha_lineage_seal(tampered)["status"] == "FAIL"


def test_prohibited_git_content_classifier_blocks_payload_paths() -> None:
    prohibited = [
        "data/raw/p0rdcra1a/provider.bin",
        "data/canonical/p0rdcra1a/EURUSD.parquet",
        "results/gate_p1/row_level_trades.json",
        "tmp/provider_payload.json",
        "config/client_secret.json",
    ]
    permitted = [
        "results/gate_p1/final_claim_matrix.json",
        "docs/research/strategy_alpha/STRATEGY_ALPHA_RESULTS.md",
        "src/fx_smc_bot/research/strategy_alpha_closure.py",
    ]

    assert detect_prohibited_changed_paths(prohibited) == prohibited
    assert detect_prohibited_changed_paths(permitted) == []


def test_forward_handoff_classifier_blocks_closed_lineage_artifacts() -> None:
    assert validate_no_forward_handoff(
        [
            "configs/research/strategy_alpha_forward_v1.yaml",
            "results/gate_p1/prospective_protocol_freeze.json",
        ]
    )["status"] == "FAIL"
    assert validate_no_forward_handoff(
        [
            "results/gate_p1/final_decision.json",
            "docs/research/strategy_alpha/STRATEGY_ALPHA_LINEAGE_SEAL.md",
        ]
    )["status"] == "PASS"


def test_reproducibility_manifest_hashes_all_declared_artifacts() -> None:
    manifest = load_json(P1 / "reproducibility_manifest.json")
    records = [
        record
        for entries in manifest["artifact_groups"].values()
        for record in entries
    ]

    assert manifest["status"] == "PASS"
    assert manifest["all_declared_artifacts_present"] is True
    assert manifest["raw_canonical_or_row_level_data_included"] is False
    assert manifest["sealed_holdout_data_included"] is False
    assert manifest["manifest_hash"] == payload_hash_without(manifest, "manifest_hash")
    for record in records:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["raw_sha256"]
