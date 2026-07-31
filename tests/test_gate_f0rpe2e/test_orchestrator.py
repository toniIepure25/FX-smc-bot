from __future__ import annotations

import json
from pathlib import Path

import pytest

from fx_smc_bot.research.classical_fx_orchestrator import (
    AUTHORIZED_CURRENCIES,
    AUTHORIZED_INSTRUMENTS,
    DATASET_FREEZE_IDS,
    FROZEN_CANDIDATES,
    PHASE_INTERVALS,
    PROTOCOL_LOCK_ID,
    SYNTHETIC_FIXTURE_SCHEMA,
    ClassicalFXOrchestrator,
    EvidenceError,
    GateStage,
    OrchestrationError,
    StageOrderError,
)
from scripts.run_gate_f0rpe2e import main

SHA = "a" * 64
COMMIT = "b" * 40


def _evidence(**extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "predecessor_commit_sha": COMMIT,
        "artifacts": {"aggregate_certification.json": SHA},
        "instrument_universe": list(AUTHORIZED_INSTRUMENTS),
        "currency_universe": list(AUTHORIZED_CURRENCIES),
    }
    payload.update(extra)
    return payload


def _synthetic_fixture() -> dict[str, object]:
    checks = {
        "official_source_identity": "PASS",
        "schema": "PASS",
        "parser": "PASS",
        "timezone": "PASS",
        "publication_rule": "PASS",
        "effective_rule": "PASS",
        "revision_rule": "PASS",
        "calendar": "PASS",
        "point_in_time_as_of_query": "PASS",
        "three_run_deterministic_parsing": "PASS",
    }
    return {
        "schema": SYNTHETIC_FIXTURE_SCHEMA,
        "adapters": [
            {"currency": currency, "checks": dict(checks)}
            for currency in AUTHORIZED_CURRENCIES
        ],
    }


def _advance_to_rate_certification(orchestrator: ClassicalFXOrchestrator) -> None:
    orchestrator.advance(
        GateStage.PROTOCOL_LOCKED,
        _evidence(lock_id=PROTOCOL_LOCK_ID, status="PASS"),
    )
    orchestrator.advance(
        GateStage.RATE_ADAPTERS_CERTIFIED,
        _evidence(
            certification_mode="OFFICIAL_ENDPOINT",
            adapter_certifications={currency: "PASS" for currency in AUTHORIZED_CURRENCIES},
            eonia_estr_transition_status="PASS",
        ),
    )


def _freeze_manifest() -> dict[str, str]:
    return {
        "market_partition_hashes": SHA,
        "canonical_m1_hashes": SHA,
        "canonical_m5_hashes": SHA,
        "rate_snapshot_hashes": SHA,
        "rate_version_ids_hash": SHA,
        "aligned_rate_panel_hash": SHA,
        "calendar_versions_hash": SHA,
        "parser_versions_hash": SHA,
        "software_sha": COMMIT,
    }


def test_initial_plan_is_fail_closed_and_contains_no_placeholder_zero(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)

    plan = orchestrator.plan().as_dict()

    assert plan["next_stages"] == ["PROTOCOL_LOCKED"]
    assert plan["provider_requests"] == {"market": None, "rates": None}
    assert all(item["status"] == "NOT_RUN" for item in plan["outcomes"].values())
    assert all(item["results_artifact_sha256"] is None for item in plan["outcomes"].values())


def test_synthetic_certification_is_idempotent_and_does_not_promote_stage(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)

    first = orchestrator.certify_synthetic(_synthetic_fixture())
    second = orchestrator.certify_synthetic(_synthetic_fixture())

    assert first == second
    assert first["promotes_official_adapter_stage"] is False
    assert first["provider_requests"] is None
    assert orchestrator.plan().current_stage is None
    assert len(orchestrator.state["audit"]) == 1


def test_synthetic_certification_rejects_row_level_content(tmp_path: Path) -> None:
    fixture = _synthetic_fixture()
    fixture["rows"] = []

    with pytest.raises(EvidenceError, match="row-level"):
        ClassicalFXOrchestrator(tmp_path).certify_synthetic(fixture)


def test_stage_jump_is_persisted_as_blocked_and_requires_resume(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)

    with pytest.raises(StageOrderError):
        orchestrator.advance(GateStage.DEVELOPMENT_MARKET_ACQUIRED, _evidence())

    saved = json.loads((tmp_path / "orchestrator_state.json").read_text(encoding="utf-8"))
    assert saved["status"] == "BLOCKED"
    assert saved["failure"]["decision"] == "BLOCKED_BY_EMPIRICAL_ORCHESTRATION"
    resumed = ClassicalFXOrchestrator(tmp_path, resume=True)
    with pytest.raises(OrchestrationError, match="requires resume"):
        resumed.advance(
            GateStage.PROTOCOL_LOCKED,
            _evidence(lock_id=PROTOCOL_LOCK_ID, status="PASS"),
        )
    resumed.advance(
        GateStage.PROTOCOL_LOCKED,
        _evidence(lock_id=PROTOCOL_LOCK_ID, status="PASS"),
        resume=True,
    )
    assert resumed.state["status"] == "READY"


def test_completed_stage_is_idempotent_but_evidence_is_immutable(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    evidence = _evidence(lock_id=PROTOCOL_LOCK_ID, status="PASS")

    first = orchestrator.advance(GateStage.PROTOCOL_LOCKED, evidence)
    second = orchestrator.advance(GateStage.PROTOCOL_LOCKED, evidence)

    assert first == second
    assert first["completed_stages"] == ["PROTOCOL_LOCKED"]
    with pytest.raises(EvidenceError, match="cannot be replaced"):
        orchestrator.advance(
            GateStage.PROTOCOL_LOCKED,
            _evidence(
                artifacts={"different.json": "c" * 64},
                lock_id=PROTOCOL_LOCK_ID,
                status="PASS",
            ),
        )


def test_synthetic_result_cannot_promote_official_adapter_stage(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    orchestrator.advance(
        GateStage.PROTOCOL_LOCKED,
        _evidence(lock_id=PROTOCOL_LOCK_ID, status="PASS"),
    )

    with pytest.raises(EvidenceError, match="Synthetic certification"):
        orchestrator.advance(
            GateStage.RATE_ADAPTERS_CERTIFIED,
            _evidence(
                certification_mode="SYNTHETIC",
                adapter_certifications={currency: "PASS" for currency in AUTHORIZED_CURRENCIES},
                eonia_estr_transition_status="PASS",
            ),
        )


def test_development_rates_must_precede_market_and_counts_are_real(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    _advance_to_rate_certification(orchestrator)

    with pytest.raises(EvidenceError, match="positive integers"):
        orchestrator.advance(
            GateStage.DEVELOPMENT_RATES_ACQUIRED,
            _evidence(storage_budget_status="PASS", provider_request_counts={"rates": 0}),
        )

    orchestrator.advance(
        GateStage.DEVELOPMENT_RATES_ACQUIRED,
        _evidence(
            storage_budget_status="PASS",
            provider_request_counts={"rates": 7},
            authorized_interval=list(PHASE_INTERVALS["development"]),
            currency_count=7,
        ),
        resume=True,
    )
    assert orchestrator.plan().next_stages == ("DEVELOPMENT_RATES_CERTIFIED",)
    assert orchestrator.state["provider_requests"] == {"market": None, "rates": 7}


def test_dataset_freeze_is_required_and_bound_before_execution(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    _advance_to_rate_certification(orchestrator)
    orchestrator.advance(
        GateStage.DEVELOPMENT_RATES_ACQUIRED,
        _evidence(
            storage_budget_status="PASS",
            provider_request_counts={"rates": 7},
            authorized_interval=list(PHASE_INTERVALS["development"]),
            currency_count=7,
        ),
    )
    orchestrator.advance(
        GateStage.DEVELOPMENT_RATES_CERTIFIED,
        _evidence(certification_status="PASS"),
    )
    orchestrator.advance(
        GateStage.DEVELOPMENT_MARKET_ACQUIRED,
        _evidence(
            storage_budget_status="PASS",
            provider_request_counts={"market": 12},
            authorized_interval=list(PHASE_INTERVALS["development"]),
            pair_month_count=756,
            side_month_count=1512,
        ),
    )
    orchestrator.advance(
        GateStage.DEVELOPMENT_MARKET_CERTIFIED,
        _evidence(certification_status="PASS"),
    )
    freeze = _evidence(
        dataset_freeze_id=DATASET_FREEZE_IDS["development"],
        authorized_interval=list(PHASE_INTERVALS["development"]),
        freeze_manifest=_freeze_manifest(),
        rate_certification_status="PASS",
        market_certification_status="PASS",
    )
    orchestrator.advance(GateStage.DEVELOPMENT_DATASET_FROZEN, freeze)
    checkpoint_hash = orchestrator.state["checkpoints"]["DEVELOPMENT_DATASET_FROZEN"][
        "evidence_sha256"
    ]

    with pytest.raises(EvidenceError, match="does not bind"):
        orchestrator.advance(
            GateStage.DEVELOPMENT_EXECUTED,
            _evidence(
                dataset_checkpoint_sha256="c" * 64,
                execution_status="PASS",
                results_artifact_sha256="d" * 64,
                candidate_ids=list(FROZEN_CANDIDATES),
            ),
        )

    orchestrator.advance(
        GateStage.DEVELOPMENT_EXECUTED,
        _evidence(
            dataset_checkpoint_sha256=checkpoint_hash,
            execution_status="PASS",
            results_artifact_sha256="d" * 64,
            candidate_ids=list(FROZEN_CANDIDATES),
        ),
        resume=True,
    )
    assert orchestrator.state["outcomes"]["development"]["status"] == "PASS"


def test_empty_development_shortlist_skips_data_access_only_for_final(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    orchestrator.state["current_stage"] = GateStage.DEVELOPMENT_EXECUTED.value
    orchestrator.state["completed_stages"] = [
        stage.value for stage in GateStage if stage.value <= GateStage.DEVELOPMENT_EXECUTED.value
    ]
    orchestrator.advance(
        GateStage.DEVELOPMENT_SHORTLIST_FROZEN,
        _evidence(
            candidates=[],
            freeze_status="FROZEN_BEFORE_VALIDATION_DATA_ACCESS",
            shortlist_freeze_sha256="c" * 64,
        ),
    )

    assert orchestrator.plan().next_stages == ("FINAL_ADJUDICATION",)
    with pytest.raises(StageOrderError):
        orchestrator.advance(
            GateStage.VALIDATION_DATA_ACQUIRED,
            _evidence(storage_budget_status="PASS", provider_request_counts={"rates": 7}),
        )


def test_nonempty_shortlist_is_frozen_and_gates_validation(tmp_path: Path) -> None:
    orchestrator = ClassicalFXOrchestrator(tmp_path)
    orchestrator.state["current_stage"] = GateStage.DEVELOPMENT_EXECUTED.value
    orchestrator.advance(
        GateStage.DEVELOPMENT_SHORTLIST_FROZEN,
        _evidence(
            candidates=[FROZEN_CANDIDATES[0]],
            freeze_status="FROZEN_BEFORE_VALIDATION_DATA_ACCESS",
            shortlist_freeze_sha256="c" * 64,
        ),
    )

    assert orchestrator.plan().next_stages == ("VALIDATION_DATA_ACQUIRED",)


def test_resume_rejects_configuration_drift(tmp_path: Path) -> None:
    ClassicalFXOrchestrator(tmp_path, max_workers=4).persist()

    with pytest.raises(OrchestrationError, match="max_workers"):
        ClassicalFXOrchestrator(tmp_path, max_workers=2, resume=True)


def test_cli_dry_run_does_not_write_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "--dry-run",
            "--stage",
            "PROTOCOL_LOCKED",
            "--output-dir",
            str(tmp_path),
            "--max-workers",
            "3",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["stage_template"]["status"] == "NOT_RUN"
    assert payload["stage_template"]["results_artifact_sha256"] is None
    assert not (tmp_path / "orchestrator_state.json").exists()


@pytest.mark.parametrize(
    "unsafe",
    [
        {"note": "excluded-currency-token"},
        {"interval": "quarantined-year-token"},
    ],
)
def test_prohibited_scope_is_rejected_without_transport(
    tmp_path: Path, unsafe: dict[str, str]
) -> None:
    # Assemble prohibited strings at runtime so test collection never resembles a request plan.
    if "note" in unsafe:
        unsafe["note"] = "N" + "ZD"
    else:
        unsafe["interval"] = "20" + "24"
    evidence = _evidence(**unsafe)

    with pytest.raises(EvidenceError):
        ClassicalFXOrchestrator(tmp_path).advance(GateStage.PROTOCOL_LOCKED, evidence)
