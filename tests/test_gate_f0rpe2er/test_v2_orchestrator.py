from __future__ import annotations

import json
from pathlib import Path

import pytest

from fx_smc_bot.research.classical_fx_orchestrator import (
    AUTHORIZED_CURRENCIES,
    AUTHORIZED_INSTRUMENTS,
    FROZEN_CANDIDATES,
    V2_BOUNDARY_ID,
    V2_FAILED_GATE_TIP_SHA,
    V2_INFRASTRUCTURE_FREEZE_ID,
    V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA,
    V2_PROGRAM_ID,
    V2_QUARANTINE_STATUS,
    V2_REBASELINE_ID,
    ClassicalFXV2Orchestrator,
    EvidenceError,
    OrchestrationError,
    StageOrderError,
    V2GateStage,
    build_v2_stage_evidence_template,
)
from scripts.run_gate_f0rpe2er import main

SHA = "a" * 64
SECOND_SHA = "b" * 64
COMMITS = [f"{index:x}" * 40 for index in range(1, 16)]


def _common(commit: str, previous: str | None = None, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "stage_commit_sha": commit,
        "artifacts": {"aggregate_certification.json": SHA},
        "instrument_universe": list(AUTHORIZED_INSTRUMENTS),
        "currency_universe": list(AUTHORIZED_CURRENCIES),
    }
    if previous is not None:
        payload["predecessor_stage_commit_sha"] = previous
    payload.update(extra)
    return payload


def _failed_gate() -> dict[str, object]:
    return _common(
        V2_FAILED_GATE_TIP_SHA,
        inheritance_status="FAILED_GATE_PRESERVED_NOT_REVERSED",
        failed_gate_tip_sha=V2_FAILED_GATE_TIP_SHA,
        predecessor_decision="BLOCKED_BY_PROSPECTIVE_INTEGRITY",
        failed_integrity_audit_preserved=True,
        exposed_documentation_record_preserved=True,
    )


def _advance_to_infrastructure(
    orchestrator: ClassicalFXV2Orchestrator,
) -> dict[V2GateStage, str]:
    commits: dict[V2GateStage, str] = {V2GateStage.FAILED_GATE_INHERITED: V2_FAILED_GATE_TIP_SHA}
    orchestrator.advance(V2GateStage.FAILED_GATE_INHERITED, _failed_gate())
    commits[V2GateStage.INTEGRITY_REBASELINED] = COMMITS[0]
    orchestrator.advance(
        V2GateStage.INTEGRITY_REBASELINED,
        _common(
            COMMITS[0],
            V2_FAILED_GATE_TIP_SHA,
            rebaseline_id=V2_REBASELINE_ID,
            quarantine_status=V2_QUARANTINE_STATUS,
            untouched_claim=False,
            future_confirmatory_start_rule=(
                "FIRST_COMPLETE_FX_TRADING_DAY_AFTER_FINAL_PORTFOLIO_FREEZE"
            ),
            future_observations_status="NOT_YET_GENERATED_OR_ACCESSED",
            clean_room_identity_sha256=orchestrator.clean_room_identity,
            clean_room_certification_status="PASS",
        ),
    )
    commits[V2GateStage.SOURCE_BOUNDARY_FROZEN] = V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA
    orchestrator.advance(
        V2GateStage.SOURCE_BOUNDARY_FROZEN,
        _common(
            V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA,
            COMMITS[0],
            boundary_id=V2_BOUNDARY_ID,
            boundary_status="PASS",
            metadata_class_supplies_numerical_observations=False,
            numerical_class_requires_server_side_bounds=True,
            official_source_count=7,
            maximum_authorized_date="2022-12-31",
            source_allowlist_sha256=SHA,
        ),
    )
    source_checkpoint = orchestrator.state["checkpoints"]["SOURCE_BOUNDARY_FROZEN"]
    commits[V2GateStage.LIVE_ADAPTERS_CERTIFIED] = COMMITS[2]
    orchestrator.advance(
        V2GateStage.LIVE_ADAPTERS_CERTIFIED,
        _common(
            COMMITS[2],
            V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA,
            access_predecessor_commit_sha=V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA,
            certification_mode="LIVE_OFFICIAL_BOUNDED",
            adapter_certifications={currency: "PASS" for currency in AUTHORIZED_CURRENCIES},
            source_boundary_checkpoint_sha256=source_checkpoint["evidence_sha256"],
            integrity_boundary_pre_network_sha=V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA,
            response_firewall_status="PASS",
            server_side_date_bounds_status="PASS",
            eonia_estr_transition_status="PASS",
        ),
    )
    commits[V2GateStage.INFRASTRUCTURE_FROZEN] = COMMITS[3]
    orchestrator.advance(
        V2GateStage.INFRASTRUCTURE_FROZEN,
        _common(
            COMMITS[3],
            COMMITS[2],
            freeze_id=V2_INFRASTRUCTURE_FREEZE_ID,
            certification_status="PASS",
            observation_access_before_freeze=False,
            infrastructure_manifest_sha256=SECOND_SHA,
        ),
    )
    return commits


def _storage(stage: V2GateStage) -> dict[str, object]:
    return {
        "status": "PASS",
        "checked_for_stage": stage.value,
        "free_bytes": 2_000,
        "required_bytes": 1_000,
        "evidence_sha256": SHA,
    }


def _freeze_manifest() -> dict[str, str]:
    return {
        "market_hashes": SHA,
        "m1_hashes": SHA,
        "m5_hashes": SHA,
        "source_snapshot_hashes": SHA,
        "rate_version_ids_hash": SHA,
        "aligned_panel_hash": SHA,
        "calendar_versions_hash": SHA,
        "parser_versions_hash": SHA,
        "software_sha": COMMITS[5],
    }


def test_v2_identity_and_exact_stage_order(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")

    assert orchestrator.state["program_id"] == V2_PROGRAM_ID
    assert orchestrator.state["quarantine_status"] == V2_QUARANTINE_STATUS
    assert orchestrator.state["quarantined_interval_untouched_claim"] is False
    assert [stage.value for stage in V2GateStage] == [
        "FAILED_GATE_INHERITED",
        "INTEGRITY_REBASELINED",
        "SOURCE_BOUNDARY_FROZEN",
        "LIVE_ADAPTERS_CERTIFIED",
        "INFRASTRUCTURE_FROZEN",
        "DEVELOPMENT_RATES_ACQUIRED",
        "DEVELOPMENT_RATES_CERTIFIED",
        "DEVELOPMENT_MARKET_ACQUIRED",
        "DEVELOPMENT_MARKET_CERTIFIED",
        "DEVELOPMENT_DATASET_FROZEN",
        "DEVELOPMENT_EXECUTED",
        "VALIDATION_SHORTLIST_FROZEN",
        "VALIDATION_DATASET_FROZEN",
        "VALIDATION_EXECUTED",
        "REPLICATION_SHORTLIST_FROZEN",
        "REPLICATION_DATASET_FROZEN",
        "REPLICATION_EXECUTED",
        "FINAL_ADJUDICATION",
    ]
    assert orchestrator.plan().next_stages == ("FAILED_GATE_INHERITED",)


def test_failed_gate_lineage_is_exact_and_immutable(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")

    with pytest.raises(EvidenceError, match="sealed V1 tip"):
        orchestrator.advance(
            V2GateStage.FAILED_GATE_INHERITED,
            {**_failed_gate(), "stage_commit_sha": COMMITS[0]},
        )

    orchestrator.advance(V2GateStage.FAILED_GATE_INHERITED, _failed_gate(), resume=True)
    assert orchestrator.state["completed_stages"] == ["FAILED_GATE_INHERITED"]
    assert not orchestrator.pending_path.exists()
    with pytest.raises(EvidenceError, match="cannot be replaced"):
        orchestrator.advance(
            V2GateStage.FAILED_GATE_INHERITED,
            {**_failed_gate(), "artifacts": {"changed.json": SECOND_SHA}},
        )


def test_stage_jump_is_fail_closed_and_resume_is_explicit(tmp_path: Path) -> None:
    output = tmp_path / "out"
    clean = tmp_path / "clean"
    orchestrator = ClassicalFXV2Orchestrator(output, clean_room_root=clean)

    with pytest.raises(StageOrderError):
        orchestrator.advance(V2GateStage.SOURCE_BOUNDARY_FROZEN, _common(COMMITS[0]))

    assert json.loads(orchestrator.state_path.read_text(encoding="utf-8"))["status"] == "BLOCKED"
    resumed = ClassicalFXV2Orchestrator(output, clean_room_root=clean, resume=True)
    with pytest.raises(OrchestrationError, match="requires resume"):
        resumed.advance(V2GateStage.FAILED_GATE_INHERITED, _failed_gate())
    resumed.advance(V2GateStage.FAILED_GATE_INHERITED, _failed_gate(), resume=True)


def test_clean_room_identity_and_worker_count_are_pinned_on_resume(tmp_path: Path) -> None:
    output = tmp_path / "out"
    ClassicalFXV2Orchestrator(
        output, clean_room_root=tmp_path / "clean", max_workers=4
    ).persist()

    with pytest.raises(OrchestrationError, match="max_workers"):
        ClassicalFXV2Orchestrator(
            output, clean_room_root=tmp_path / "clean", max_workers=2, resume=True
        )
    with pytest.raises(OrchestrationError, match="clean_room_identity"):
        ClassicalFXV2Orchestrator(
            output, clean_room_root=tmp_path / "different", max_workers=4, resume=True
        )


def test_source_boundary_and_pre_access_commit_are_required(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    _advance_to_infrastructure(orchestrator)

    assert orchestrator.plan().current_stage == "INFRASTRUCTURE_FROZEN"
    assert orchestrator.state["checkpoints"]["LIVE_ADAPTERS_CERTIFIED"][
        "stage_commit_sha"
    ] == COMMITS[2]
    assert (
        orchestrator.state["integrity_boundary_pre_network_sha"]
        == V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA
    )


def test_acquisition_requires_current_storage_and_infrastructure_commit(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    _advance_to_infrastructure(orchestrator)
    evidence = _common(
        COMMITS[4],
        COMMITS[3],
        access_predecessor_commit_sha=COMMITS[3],
        infrastructure_pre_observation_sha=COMMITS[3],
        live_adapter_certification_sha256=orchestrator.state["checkpoints"][
            "LIVE_ADAPTERS_CERTIFIED"
        ]["evidence_sha256"],
        provider_request_counts={"rates": 7},
        response_scope_status="PASS",
    )

    with pytest.raises(EvidenceError, match="storage recheck"):
        orchestrator.advance(V2GateStage.DEVELOPMENT_RATES_ACQUIRED, evidence)

    evidence["storage_recheck"] = _storage(V2GateStage.DEVELOPMENT_RATES_ACQUIRED)
    orchestrator.advance(V2GateStage.DEVELOPMENT_RATES_ACQUIRED, evidence, resume=True)
    assert orchestrator.state["provider_requests"] == {"market": None, "rates": 7}


def test_market_acquisition_requires_every_live_adapter_to_remain_certified(
    tmp_path: Path,
) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    _advance_to_infrastructure(orchestrator)
    orchestrator.state["current_stage"] = V2GateStage.DEVELOPMENT_RATES_CERTIFIED.value
    orchestrator.state["checkpoints"][V2GateStage.DEVELOPMENT_RATES_CERTIFIED.value] = {
        "stage_commit_sha": COMMITS[4]
    }
    orchestrator.state["live_adapter_certifications"][AUTHORIZED_CURRENCIES[0]] = "FAIL"
    live_checkpoint = orchestrator.state["checkpoints"][V2GateStage.LIVE_ADAPTERS_CERTIFIED.value]

    with pytest.raises(EvidenceError, match="all seven live official adapters"):
        orchestrator.advance(
            V2GateStage.DEVELOPMENT_MARKET_ACQUIRED,
            _common(
                COMMITS[5],
                COMMITS[4],
                access_predecessor_commit_sha=COMMITS[4],
                infrastructure_pre_observation_sha=COMMITS[3],
                live_adapter_certification_sha256=live_checkpoint["evidence_sha256"],
                storage_recheck=_storage(V2GateStage.DEVELOPMENT_MARKET_ACQUIRED),
                provider_request_counts={"market": 1},
                response_scope_status="PASS",
            ),
        )


def test_atomic_checkpoint_and_state_bind_the_same_transition(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    orchestrator.advance(V2GateStage.FAILED_GATE_INHERITED, _failed_gate())

    state = json.loads(orchestrator.state_path.read_text(encoding="utf-8"))
    checkpoint_path = next((orchestrator.output_dir / "checkpoints_v2").iterdir())
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert state["checkpoints"]["FAILED_GATE_INHERITED"] == checkpoint
    assert checkpoint["task_identity"] == orchestrator.state["checkpoints"][
        "FAILED_GATE_INHERITED"
    ]["task_identity"]
    assert not orchestrator.pending_path.exists()


def test_execution_rejects_placeholder_or_embedded_metrics(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    orchestrator.state["current_stage"] = V2GateStage.DEVELOPMENT_DATASET_FROZEN.value
    orchestrator.state["checkpoints"][V2GateStage.DEVELOPMENT_DATASET_FROZEN.value] = {
        "evidence_sha256": SHA,
        "stage_commit_sha": COMMITS[5],
    }
    evidence = _common(
        COMMITS[6],
        COMMITS[5],
        access_predecessor_commit_sha=COMMITS[5],
        dataset_checkpoint_sha256=SHA,
        execution_status="PASS",
        metrics_status="COMPLETE",
        results_artifact_sha256="0" * 64,
        metrics_manifest_sha256=SECOND_SHA,
        candidate_ids=list(FROZEN_CANDIDATES),
    )

    with pytest.raises(EvidenceError, match="Placeholder"):
        orchestrator.advance(V2GateStage.DEVELOPMENT_EXECUTED, evidence)
    with pytest.raises(EvidenceError, match="numerical content"):
        orchestrator.advance(
            V2GateStage.DEVELOPMENT_EXECUTED,
            {**evidence, "metrics": {"candidate": 0.0}},
            resume=True,
        )


def test_empty_validation_shortlist_allows_only_final_adjudication(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")
    orchestrator.state["current_stage"] = V2GateStage.DEVELOPMENT_EXECUTED.value
    orchestrator.state["checkpoints"][V2GateStage.DEVELOPMENT_EXECUTED.value] = {
        "stage_commit_sha": COMMITS[6]
    }
    orchestrator.advance(
        V2GateStage.VALIDATION_SHORTLIST_FROZEN,
        _common(
            COMMITS[7],
            COMMITS[6],
            candidates=[],
            freeze_status="FROZEN_BEFORE_VALIDATION_DATA_ACCESS",
            shortlist_freeze_sha256=SHA,
        ),
    )

    assert orchestrator.plan().next_stages == ("FINAL_ADJUDICATION",)
    with pytest.raises(StageOrderError):
        orchestrator.advance(V2GateStage.VALIDATION_DATASET_FROZEN, _common(COMMITS[8]))


def test_certify_only_cannot_promote_acquisition(tmp_path: Path) -> None:
    orchestrator = ClassicalFXV2Orchestrator(tmp_path / "out", clean_room_root=tmp_path / "clean")

    with pytest.raises(StageOrderError, match="certify-only"):
        orchestrator.advance(
            V2GateStage.DEVELOPMENT_RATES_ACQUIRED,
            _common(COMMITS[0]),
            certify_only=True,
        )


def test_v2_template_has_no_fake_metrics_or_request_counts() -> None:
    template = build_v2_stage_evidence_template(V2GateStage.DEVELOPMENT_EXECUTED)

    assert template["provider_request_counts"] is None
    assert template["results_artifact_sha256"] is None
    assert template["metrics_manifest_sha256"] is None
    assert template["status"] == "NOT_RUN"


def test_cli_supports_required_flags_without_writing_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    result = main(
        [
            "--stage",
            "FAILED_GATE_INHERITED",
            "--dry-run",
            "--certify-only",
            "--max-workers",
            "3",
            "--clean-room-root",
            str(tmp_path / "clean"),
            "--output-dir",
            str(output),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["mode"] == "CERTIFY_ONLY"
    assert payload["stage_template"]["status"] == "NOT_RUN"
    assert not (output / "orchestrator_state_v2.json").exists()


def test_excluded_asset_evidence_is_rejected_before_any_stage(tmp_path: Path) -> None:
    evidence = _failed_gate()
    evidence["note"] = "N" + "ZD"

    with pytest.raises(EvidenceError, match="excluded asset"):
        ClassicalFXV2Orchestrator(
            tmp_path / "out", clean_room_root=tmp_path / "clean"
        ).advance(V2GateStage.FAILED_GATE_INHERITED, evidence)


def test_v1_api_remains_available(tmp_path: Path) -> None:
    from fx_smc_bot.research.classical_fx_orchestrator import ClassicalFXOrchestrator, GateStage

    assert ClassicalFXOrchestrator(tmp_path).plan().next_stages == (
        GateStage.PROTOCOL_LOCKED.value,
    )
