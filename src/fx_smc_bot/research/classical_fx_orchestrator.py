"""Fail-closed orchestration for Gate F0-RP-E2E.

This module coordinates evidence produced by acquisition and research workers.
It deliberately contains no transport client and never reads empirical data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

PROGRAM_ID: Final = "FX_CLASSICAL_RISK_PREMIA_V1"
LINEAGE_ID: Final = "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1"
AMENDMENT_ID: Final = "F0_RATE_PROVENANCE_AMENDMENT_V1"
GATE_ID: Final = "F0_RP_E2E_OFFICIAL_RATE_AND_EMPIRICAL_ORCHESTRATION_V1"
STATE_SCHEMA_VERSION: Final = "F0RPE2E_ORCHESTRATOR_STATE_V1"
SYNTHETIC_FIXTURE_SCHEMA: Final = "F0RPE2E_SYNTHETIC_METADATA_SCHEMA_V1"
PROTOCOL_LOCK_ID: Final = "F0RPE2E_SCIENTIFIC_PROTOCOL_INHERITANCE_V1"

AUTHORIZED_INSTRUMENTS: Final = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
AUTHORIZED_CURRENCIES: Final = ("USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF")
FROZEN_CANDIDATES: Final = (
    "F0_TSMOM_COMPOSITE_V1",
    "F0_SHORT_TERM_REVERSAL_V1",
    "F0_DUAL_HORIZON_TREND_V1",
    "F0_DONCHIAN_BREAKOUT_V1",
    "F0_RATE_DIFFERENTIAL_CARRY_V1",
    "F0_FIXED_MULTI_FACTOR_V1",
)

PHASE_INTERVALS: Final[dict[str, tuple[str, str]]] = {
    "development": ("2010-01-01", "2016-12-31"),
    "validation": ("2017-01-01", "2019-12-31"),
    "replication": ("2020-01-01", "2022-12-31"),
}
DATASET_FREEZE_IDS: Final = {
    "development": "FX_CLASSICAL_FACTORS_DEVELOPMENT_2010_2016_V1",
    "validation": "FX_CLASSICAL_FACTORS_VALIDATION_2017_2019_V1",
    "replication": "FX_CLASSICAL_FACTORS_REPLICATION_2020_2022_V1",
}
FINAL_DECISIONS: Final = frozenset(
    {
        "F0RPE2E_FACTOR_PORTFOLIO_FROZEN_FOR_FUTURE_CONFIRMATION",
        "F0RPE2E_NO_FACTOR_PORTFOLIO_PASSED_DEVELOPMENT",
        "F0RPE2E_NO_FACTOR_PORTFOLIO_PASSED_INTERNAL_VALIDATION",
        "F0RPE2E_NO_FACTOR_PORTFOLIO_SURVIVED_INDEPENDENT_REPLICATION",
        "F0RPE2E_EMPIRICAL_INFRASTRUCTURE_CERTIFIED_EXECUTION_NOT_COMPLETED",
        "BLOCKED_BY_F0RP_PROVENANCE",
        "BLOCKED_BY_PROTOCOL_INHERITANCE",
        "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
        "BLOCKED_BY_RATE_SOURCE_ACCESS",
        "BLOCKED_BY_RATE_PARSE_INTEGRITY",
        "BLOCKED_BY_RATE_VINTAGE_INTEGRITY",
        "BLOCKED_BY_RATE_AVAILABILITY_ALIGNMENT",
        "BLOCKED_BY_EONIA_ESTR_TRANSITION",
        "BLOCKED_BY_MARKET_DATA_PROVENANCE",
        "BLOCKED_BY_STORAGE_BUDGET",
        "BLOCKED_BY_PROVIDER_ACCESS",
        "BLOCKED_BY_DATA_CERTIFICATION",
        "BLOCKED_BY_EMPIRICAL_ORCHESTRATION",
        "BLOCKED_BY_EXECUTION_INTEGRITY",
        "BLOCKED_BY_FINANCING_COST_MODEL",
        "BLOCKED_BY_LOOKAHEAD_OR_LEAKAGE",
        "BLOCKED_BY_PORTFOLIO_ACCOUNTING",
        "BLOCKED_BY_NONDETERMINISM",
        "BLOCKED_BY_MULTIPLE_TESTING_INTEGRITY",
        "BLOCKED_BY_RESULT_INTEGRITY",
        "BLOCKED_BY_STATIC_ANALYSIS",
        "BLOCKED_BY_PROSPECTIVE_INTEGRITY",
    }
)

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_PROHIBITED_YEAR_RE: Final = re.compile(r"(?<!\d)20(?:23|24|25)(?!\d)")
_ROW_LEVEL_KEYS: Final = frozenset(
    {"observation", "observations", "row", "rows", "rate_value", "values", "payload"}
)


class OrchestrationError(RuntimeError):
    """Base class for deterministic fail-closed orchestration errors."""


class StageOrderError(OrchestrationError):
    """Raised when a caller attempts a stage jump."""


class EvidenceError(OrchestrationError):
    """Raised when checkpoint evidence is incomplete or unsafe."""


class GateStage(str, Enum):
    PROTOCOL_LOCKED = "PROTOCOL_LOCKED"
    RATE_ADAPTERS_CERTIFIED = "RATE_ADAPTERS_CERTIFIED"
    DEVELOPMENT_RATES_ACQUIRED = "DEVELOPMENT_RATES_ACQUIRED"
    DEVELOPMENT_RATES_CERTIFIED = "DEVELOPMENT_RATES_CERTIFIED"
    DEVELOPMENT_MARKET_ACQUIRED = "DEVELOPMENT_MARKET_ACQUIRED"
    DEVELOPMENT_MARKET_CERTIFIED = "DEVELOPMENT_MARKET_CERTIFIED"
    DEVELOPMENT_DATASET_FROZEN = "DEVELOPMENT_DATASET_FROZEN"
    DEVELOPMENT_EXECUTED = "DEVELOPMENT_EXECUTED"
    DEVELOPMENT_SHORTLIST_FROZEN = "DEVELOPMENT_SHORTLIST_FROZEN"
    VALIDATION_DATA_ACQUIRED = "VALIDATION_DATA_ACQUIRED"
    VALIDATION_DATASET_FROZEN = "VALIDATION_DATASET_FROZEN"
    VALIDATION_EXECUTED = "VALIDATION_EXECUTED"
    REPLICATION_SHORTLIST_FROZEN = "REPLICATION_SHORTLIST_FROZEN"
    REPLICATION_DATA_ACQUIRED = "REPLICATION_DATA_ACQUIRED"
    REPLICATION_DATASET_FROZEN = "REPLICATION_DATASET_FROZEN"
    REPLICATION_EXECUTED = "REPLICATION_EXECUTED"
    FINAL_ADJUDICATION = "FINAL_ADJUDICATION"


STAGE_ORDER: Final = tuple(GateStage)
ACQUISITION_STAGES: Final = frozenset(
    {
        GateStage.DEVELOPMENT_RATES_ACQUIRED,
        GateStage.DEVELOPMENT_MARKET_ACQUIRED,
        GateStage.VALIDATION_DATA_ACQUIRED,
        GateStage.REPLICATION_DATA_ACQUIRED,
    }
)
DATASET_STAGES: Final = {
    GateStage.DEVELOPMENT_DATASET_FROZEN: "development",
    GateStage.VALIDATION_DATASET_FROZEN: "validation",
    GateStage.REPLICATION_DATASET_FROZEN: "replication",
}
EXECUTION_STAGES: Final = {
    GateStage.DEVELOPMENT_EXECUTED: "development",
    GateStage.VALIDATION_EXECUTED: "validation",
    GateStage.REPLICATION_EXECUTED: "replication",
}
PAIR_MONTH_COUNTS: Final = {"development": 756, "validation": 324, "replication": 324}
SIDE_MONTH_COUNTS: Final = {phase: count * 2 for phase, count in PAIR_MONTH_COUNTS.items()}


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _validate_sha(value: object, *, commit: bool = False, label: str = "hash") -> str:
    pattern = _COMMIT_RE if commit else _SHA256_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise EvidenceError(f"{label} must be a lowercase {'commit' if commit else 'SHA-256'}")
    return value


def _scan_prohibited(value: object, path: str = "evidence") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _ROW_LEVEL_KEYS:
                raise EvidenceError(f"{path}.{key_text} contains prohibited row-level content")
            _scan_prohibited(key_text, f"{path}.key")
            _scan_prohibited(item, f"{path}.{key_text}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_prohibited(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        upper = value.upper()
        if "NZD" in upper:
            raise EvidenceError(f"{path} references an excluded asset")
        if _PROHIBITED_YEAR_RE.search(value):
            raise EvidenceError(f"{path} references a quarantined year")


def _new_state(max_workers: int, clean_room_identity: str | None) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "amendment_id": AMENDMENT_ID,
        "gate_id": GATE_ID,
        "authorized_instruments": list(AUTHORIZED_INSTRUMENTS),
        "authorized_currencies": list(AUTHORIZED_CURRENCIES),
        "phase_intervals": {key: list(value) for key, value in PHASE_INTERVALS.items()},
        "max_workers": max_workers,
        "clean_room_identity_sha256": clean_room_identity,
        "status": "READY",
        "current_stage": None,
        "completed_stages": [],
        "checkpoints": {},
        "failure": None,
        "provider_requests": {"market": None, "rates": None},
        "outcomes": {
            phase: {"status": "NOT_RUN", "results_artifact_sha256": None}
            for phase in PHASE_INTERVALS
        },
        "shortlists": {
            "validation": {"status": "NOT_RUN", "candidates": None, "freeze_sha256": None},
            "replication": {"status": "NOT_RUN", "candidates": None, "freeze_sha256": None},
        },
        "final_decision": None,
        "synthetic_certification": None,
        "audit": [],
    }


@dataclass(frozen=True)
class GatePlan:
    current_stage: str | None
    next_stages: tuple[str, ...]
    status: str
    provider_requests: Mapping[str, int | None]
    outcomes: Mapping[str, Mapping[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {
            "gate_id": GATE_ID,
            "current_stage": self.current_stage,
            "next_stages": list(self.next_stages),
            "status": self.status,
            "provider_requests": dict(self.provider_requests),
            "outcomes": {key: dict(value) for key, value in self.outcomes.items()},
        }


class ClassicalFXOrchestrator:
    """Checkpointed state machine that promotes only aggregate evidence."""

    def __init__(
        self,
        output_dir: Path,
        *,
        max_workers: int = 1,
        clean_room_root: Path | None = None,
        resume: bool = False,
    ) -> None:
        if not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        self.output_dir = Path(output_dir)
        _scan_prohibited(os.path.abspath(os.fspath(self.output_dir)), "output_dir")
        self.state_path = self.output_dir / "orchestrator_state.json"
        clean_room_identity = self._clean_room_identity(clean_room_root)
        if self.state_path.exists():
            if not resume:
                raise OrchestrationError("Existing state requires resume=True")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._validate_loaded_state(max_workers, clean_room_identity)
        else:
            self.state = _new_state(max_workers, clean_room_identity)

    @staticmethod
    def _clean_room_identity(root: Path | None) -> str | None:
        if root is None:
            return None
        lexical = os.path.abspath(os.fspath(root))
        _scan_prohibited(lexical, "clean_room_root")
        return hashlib.sha256(os.path.normcase(lexical).encode("utf-8")).hexdigest()

    def _validate_loaded_state(self, max_workers: int, clean_room_identity: str | None) -> None:
        if self.state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise OrchestrationError("Unsupported orchestrator state schema")
        if self.state.get("gate_id") != GATE_ID:
            raise OrchestrationError("State belongs to another gate")
        if self.state.get("max_workers") != max_workers:
            raise OrchestrationError("Resumed max_workers must match the checkpoint")
        if self.state.get("clean_room_identity_sha256") != clean_room_identity:
            raise OrchestrationError("Resumed clean-room identity must match the checkpoint")
        if self.state.get("authorized_instruments") != list(AUTHORIZED_INSTRUMENTS):
            raise OrchestrationError("Authorized instrument universe changed")
        if self.state.get("authorized_currencies") != list(AUTHORIZED_CURRENCIES):
            raise OrchestrationError("Authorized currency universe changed")

    def plan(self) -> GatePlan:
        return GatePlan(
            current_stage=self.state["current_stage"],
            next_stages=tuple(stage.value for stage in self._allowed_next_stages()),
            status=self.state["status"],
            provider_requests=self.state["provider_requests"],
            outcomes=self.state["outcomes"],
        )

    def persist(self) -> None:
        _atomic_write_json(self.state_path, self.state)

    def certify_synthetic(
        self, fixture: Mapping[str, Any], *, persist: bool = True
    ) -> dict[str, Any]:
        """Certify metadata/schema fixtures without promoting an empirical stage."""
        _scan_prohibited(fixture, "fixture")
        if fixture.get("schema") != SYNTHETIC_FIXTURE_SCHEMA:
            raise EvidenceError("Synthetic fixture schema is not frozen")
        adapters = fixture.get("adapters")
        if not isinstance(adapters, list) or len(adapters) != len(AUTHORIZED_CURRENCIES):
            raise EvidenceError("Synthetic fixture must contain exactly seven adapters")
        required_checks = (
            "official_source_identity",
            "schema",
            "parser",
            "timezone",
            "publication_rule",
            "effective_rule",
            "revision_rule",
            "calendar",
            "point_in_time_as_of_query",
            "three_run_deterministic_parsing",
        )
        currencies: list[str] = []
        for adapter in adapters:
            if not isinstance(adapter, Mapping):
                raise EvidenceError("Each synthetic adapter fixture must be an object")
            currency = adapter.get("currency")
            if not isinstance(currency, str):
                raise EvidenceError("Synthetic adapter currency is missing")
            currencies.append(currency)
            checks = adapter.get("checks")
            if not isinstance(checks, Mapping) or any(
                checks.get(check) != "PASS" for check in required_checks
            ):
                raise EvidenceError(f"Synthetic adapter checks failed for {currency}")
        if len(set(currencies)) != len(currencies) or set(currencies) != set(
            AUTHORIZED_CURRENCIES
        ):
            raise EvidenceError("Synthetic adapters must use the exact frozen currencies")
        fixture_sha256 = canonical_sha256(fixture)
        certification: dict[str, Any] = {
            "schema": SYNTHETIC_FIXTURE_SCHEMA,
            "status": "PASS",
            "fixture_sha256": fixture_sha256,
            "currency_count": len(currencies),
            "observation_access": "NOT_RUN",
            "provider_requests": None,
            "promotes_official_adapter_stage": False,
        }
        existing = self.state.get("synthetic_certification")
        if existing is not None:
            if existing != certification:
                raise EvidenceError("Synthetic certification is already pinned to another fixture")
            return certification
        self.state["synthetic_certification"] = certification
        self._audit("SYNTHETIC_CERTIFICATION", fixture_sha256)
        if persist:
            _atomic_write_json(self.output_dir / "synthetic_certification.json", certification)
            self.persist()
        return certification

    def advance(
        self,
        stage: GateStage | str,
        evidence: Mapping[str, Any],
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        target = GateStage(stage)
        _scan_prohibited(evidence)
        evidence_hash = canonical_sha256(evidence)
        existing = self.state["checkpoints"].get(target.value)
        if existing is not None:
            if existing["evidence_sha256"] != evidence_hash:
                raise EvidenceError("Completed stage cannot be replaced with different evidence")
            return self.state
        if self.state["status"] == "BLOCKED" and not resume:
            raise OrchestrationError("Blocked state requires resume=True")
        if target not in self._allowed_next_stages():
            allowed = ", ".join(stage.value for stage in self._allowed_next_stages()) or "none"
            self._persist_failure("BLOCKED_BY_EMPIRICAL_ORCHESTRATION", target, allowed)
            raise StageOrderError(f"Stage {target.value} is not allowed; expected {allowed}")
        try:
            normalized = self._validate_evidence(target, evidence)
        except OrchestrationError as exc:
            self._persist_failure("BLOCKED_BY_EXECUTION_INTEGRITY", target, str(exc))
            raise

        checkpoint = {
            "stage": target.value,
            "evidence_sha256": evidence_hash,
            "predecessor_commit_sha": normalized["predecessor_commit_sha"],
            "artifact_hashes": normalized["artifacts"],
            "task_identity": canonical_sha256(
                {"gate_id": GATE_ID, "stage": target.value, "evidence_sha256": evidence_hash}
            ),
        }
        self._apply_stage_state(target, normalized)
        self.state["status"] = "COMPLETE" if target is GateStage.FINAL_ADJUDICATION else "READY"
        self.state["failure"] = None
        self.state["current_stage"] = target.value
        self.state["completed_stages"].append(target.value)
        self.state["checkpoints"][target.value] = checkpoint
        self._audit(target.value, evidence_hash)
        stage_number = STAGE_ORDER.index(target) + 1
        checkpoint_path = (
            self.output_dir / "checkpoints" / f"{stage_number:02d}-{target.value}.json"
        )
        _atomic_write_json(checkpoint_path, checkpoint)
        self.persist()
        return self.state

    def _allowed_next_stages(self) -> tuple[GateStage, ...]:
        current = self.state["current_stage"]
        if current is None:
            return (GateStage.PROTOCOL_LOCKED,)
        stage = GateStage(current)
        if stage is GateStage.FINAL_ADJUDICATION:
            return ()
        if stage is GateStage.DEVELOPMENT_SHORTLIST_FROZEN:
            candidates = self.state["shortlists"]["validation"]["candidates"]
            return (
                (GateStage.VALIDATION_DATA_ACQUIRED,)
                if candidates
                else (GateStage.FINAL_ADJUDICATION,)
            )
        if stage is GateStage.REPLICATION_SHORTLIST_FROZEN:
            candidates = self.state["shortlists"]["replication"]["candidates"]
            return (
                (GateStage.REPLICATION_DATA_ACQUIRED,)
                if candidates
                else (GateStage.FINAL_ADJUDICATION,)
            )
        return (STAGE_ORDER[STAGE_ORDER.index(stage) + 1],)

    def _validate_evidence(
        self, stage: GateStage, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(evidence)
        normalized["predecessor_commit_sha"] = _validate_sha(
            evidence.get("predecessor_commit_sha"), commit=True, label="predecessor_commit_sha"
        )
        artifacts = evidence.get("artifacts")
        if not isinstance(artifacts, Mapping) or not artifacts:
            raise EvidenceError("Every stage requires at least one predecessor artifact")
        normalized["artifacts"] = {
            str(name): _validate_sha(value, label=f"artifacts.{name}")
            for name, value in sorted(artifacts.items())
        }
        if evidence.get("instrument_universe") != list(AUTHORIZED_INSTRUMENTS):
            raise EvidenceError("Stage evidence must bind the exact instrument universe")
        if evidence.get("currency_universe") != list(AUTHORIZED_CURRENCIES):
            raise EvidenceError("Stage evidence must bind the exact currency universe")

        if stage is GateStage.PROTOCOL_LOCKED:
            if evidence.get("lock_id") != PROTOCOL_LOCK_ID or evidence.get("status") != "PASS":
                raise EvidenceError("Protocol stage requires the frozen passing inheritance lock")
        if stage is GateStage.RATE_ADAPTERS_CERTIFIED:
            self._validate_official_adapter_evidence(evidence)
        if stage in ACQUISITION_STAGES:
            if evidence.get("storage_budget_status") != "PASS":
                raise EvidenceError("Acquisition requires a current passing storage budget")
            request_counts = evidence.get("provider_request_counts")
            if not isinstance(request_counts, Mapping):
                raise EvidenceError("Acquisition must persist provider request counts")
            for kind, count in request_counts.items():
                if kind not in {"market", "rates"} or not isinstance(count, int) or count <= 0:
                    raise EvidenceError(
                        "Executed provider request counts must be positive integers"
                    )
            phase = self._acquisition_phase(stage)
            if evidence.get("authorized_interval") != list(PHASE_INTERVALS[phase]):
                raise EvidenceError(f"Unexpected {phase} acquisition interval")
            if stage is GateStage.DEVELOPMENT_RATES_ACQUIRED:
                if set(request_counts) != {"rates"}:
                    raise EvidenceError("Development rate acquisition may request only rates")
                if evidence.get("currency_count") != len(AUTHORIZED_CURRENCIES):
                    raise EvidenceError("Development rate acquisition must cover seven currencies")
            if stage is GateStage.DEVELOPMENT_MARKET_ACQUIRED:
                if set(request_counts) != {"market"}:
                    raise EvidenceError(
                        "Development market acquisition may request only market data"
                    )
                self._validate_market_partition_counts(phase, evidence)
            if stage in {
                GateStage.VALIDATION_DATA_ACQUIRED,
                GateStage.REPLICATION_DATA_ACQUIRED,
            }:
                if set(request_counts) != {"market", "rates"}:
                    raise EvidenceError(
                        "Conditional data acquisition requires rate and market counts"
                    )
                if evidence.get("rates_certified_before_market") is not True:
                    raise EvidenceError("Conditional rates must be certified before market access")
                self._validate_market_partition_counts(phase, evidence)
        if stage in {
            GateStage.DEVELOPMENT_RATES_CERTIFIED,
            GateStage.DEVELOPMENT_MARKET_CERTIFIED,
        } and evidence.get("certification_status") != "PASS":
            raise EvidenceError("Development certification stage requires PASS")
        if stage in DATASET_STAGES:
            self._validate_dataset_freeze(DATASET_STAGES[stage], evidence)
        if stage in EXECUTION_STAGES:
            self._validate_execution(EXECUTION_STAGES[stage], evidence)
        if stage is GateStage.DEVELOPMENT_SHORTLIST_FROZEN:
            self._validate_shortlist(
                evidence,
                maximum=4,
                expected_status="FROZEN_BEFORE_VALIDATION_DATA_ACCESS",
            )
        if stage is GateStage.REPLICATION_SHORTLIST_FROZEN:
            self._validate_shortlist(
                evidence,
                maximum=2,
                expected_status="FROZEN_BEFORE_REPLICATION_DATA_ACCESS",
            )
        if stage is GateStage.FINAL_ADJUDICATION:
            self._validate_final(evidence)
        return normalized

    @staticmethod
    def _validate_official_adapter_evidence(evidence: Mapping[str, Any]) -> None:
        if evidence.get("certification_mode") != "OFFICIAL_ENDPOINT":
            raise EvidenceError("Synthetic certification cannot promote official adapters")
        matrix = evidence.get("adapter_certifications")
        if not isinstance(matrix, Mapping) or set(matrix) != set(AUTHORIZED_CURRENCIES):
            raise EvidenceError("Official certification must cover exactly seven currencies")
        if any(status != "PASS" for status in matrix.values()):
            raise EvidenceError("Every official adapter must pass")
        if evidence.get("eonia_estr_transition_status") != "PASS":
            raise EvidenceError("The EONIA/ESTR transition must pass")

    @staticmethod
    def _validate_dataset_freeze(phase: str, evidence: Mapping[str, Any]) -> None:
        if evidence.get("dataset_freeze_id") != DATASET_FREEZE_IDS[phase]:
            raise EvidenceError(f"Unexpected {phase} dataset freeze ID")
        if evidence.get("authorized_interval") != list(PHASE_INTERVALS[phase]):
            raise EvidenceError(f"Unexpected {phase} interval")
        if evidence.get("rate_certification_status") != "PASS":
            raise EvidenceError("Dataset freeze requires passing rate certification")
        if evidence.get("market_certification_status") != "PASS":
            raise EvidenceError("Dataset freeze requires passing market certification")
        required = {
            "market_partition_hashes",
            "canonical_m1_hashes",
            "canonical_m5_hashes",
            "rate_snapshot_hashes",
            "rate_version_ids_hash",
            "aligned_rate_panel_hash",
            "calendar_versions_hash",
            "parser_versions_hash",
            "software_sha",
        }
        manifest = evidence.get("freeze_manifest")
        if not isinstance(manifest, Mapping) or set(manifest) != required:
            raise EvidenceError("Dataset freeze manifest fields are incomplete or unexpected")
        for name, value in manifest.items():
            _validate_sha(value, commit=name == "software_sha", label=f"freeze_manifest.{name}")

    def _validate_execution(self, phase: str, evidence: Mapping[str, Any]) -> None:
        freeze_stage = {
            "development": GateStage.DEVELOPMENT_DATASET_FROZEN,
            "validation": GateStage.VALIDATION_DATASET_FROZEN,
            "replication": GateStage.REPLICATION_DATASET_FROZEN,
        }[phase]
        freeze_checkpoint = self.state["checkpoints"].get(freeze_stage.value)
        if freeze_checkpoint is None:
            raise EvidenceError("Outcomes require a completed dataset freeze")
        if evidence.get("dataset_checkpoint_sha256") != freeze_checkpoint["evidence_sha256"]:
            raise EvidenceError("Outcome evidence does not bind the frozen dataset")
        result_hash = _validate_sha(evidence.get("results_artifact_sha256"), label="results hash")
        if evidence.get("execution_status") != "PASS":
            raise EvidenceError("Executed outcomes must have PASS status")
        if result_hash in {"0" * 64, "f" * 64}:
            raise EvidenceError("Placeholder result hashes are prohibited")
        candidates = evidence.get("candidate_ids")
        expected_candidates: Sequence[str] | None
        if phase == "development":
            expected_candidates = FROZEN_CANDIDATES
        elif phase == "validation":
            expected_candidates = self.state["shortlists"]["validation"]["candidates"]
        else:
            expected_candidates = self.state["shortlists"]["replication"]["candidates"]
        if not isinstance(candidates, list) or candidates != list(expected_candidates or ()):
            raise EvidenceError(f"{phase.title()} execution candidate set changed")

    @staticmethod
    def _acquisition_phase(stage: GateStage) -> str:
        if stage in {
            GateStage.DEVELOPMENT_RATES_ACQUIRED,
            GateStage.DEVELOPMENT_MARKET_ACQUIRED,
        }:
            return "development"
        if stage is GateStage.VALIDATION_DATA_ACQUIRED:
            return "validation"
        if stage is GateStage.REPLICATION_DATA_ACQUIRED:
            return "replication"
        raise EvidenceError("Stage is not an acquisition stage")

    @staticmethod
    def _validate_market_partition_counts(phase: str, evidence: Mapping[str, Any]) -> None:
        if evidence.get("pair_month_count") != PAIR_MONTH_COUNTS[phase]:
            raise EvidenceError(f"Unexpected {phase} pair-month count")
        if evidence.get("side_month_count") != SIDE_MONTH_COUNTS[phase]:
            raise EvidenceError(f"Unexpected {phase} side-month count")

    @staticmethod
    def _validate_shortlist(
        evidence: Mapping[str, Any], *, maximum: int, expected_status: str
    ) -> None:
        candidates = evidence.get("candidates")
        if not isinstance(candidates, list) or len(candidates) > maximum:
            raise EvidenceError(f"Shortlist must contain at most {maximum} candidates")
        if len(set(candidates)) != len(candidates) or any(
            candidate not in FROZEN_CANDIDATES for candidate in candidates
        ):
            raise EvidenceError("Shortlist contains duplicate or unfrozen candidates")
        if evidence.get("freeze_status") != expected_status:
            raise EvidenceError("Shortlist freeze status is not preregistered")
        _validate_sha(evidence.get("shortlist_freeze_sha256"), label="shortlist freeze hash")

    def _validate_final(self, evidence: Mapping[str, Any]) -> None:
        decision = evidence.get("decision")
        if decision not in FINAL_DECISIONS:
            raise EvidenceError("Final decision is outside the frozen decision set")
        validation_candidates = self.state["shortlists"]["validation"]["candidates"]
        replication_candidates = self.state["shortlists"]["replication"]["candidates"]
        if decision == "F0RPE2E_NO_FACTOR_PORTFOLIO_PASSED_DEVELOPMENT" and validation_candidates:
            raise EvidenceError("Development failure decision conflicts with a non-empty shortlist")
        if (
            decision == "F0RPE2E_NO_FACTOR_PORTFOLIO_PASSED_INTERNAL_VALIDATION"
            and replication_candidates
        ):
            raise EvidenceError("Validation failure decision conflicts with a non-empty shortlist")
        if decision == "F0RPE2E_FACTOR_PORTFOLIO_FROZEN_FOR_FUTURE_CONFIRMATION":
            selected = evidence.get("selected_candidates")
            if not isinstance(selected, list) or len(selected) != 1:
                raise EvidenceError("Exactly one future portfolio must be selected")
            if selected[0] not in (replication_candidates or []):
                raise EvidenceError("Future portfolio must come from the replication shortlist")
            if evidence.get("future_freeze_status") != "FROZEN_BEFORE_FUTURE_DATA_GENERATION":
                raise EvidenceError("Future portfolio must be frozen before future data")

    def _apply_stage_state(self, stage: GateStage, evidence: Mapping[str, Any]) -> None:
        if stage in ACQUISITION_STAGES:
            for kind, count in evidence["provider_request_counts"].items():
                previous = self.state["provider_requests"][kind]
                self.state["provider_requests"][kind] = (previous or 0) + count
        if stage in EXECUTION_STAGES:
            phase = EXECUTION_STAGES[stage]
            self.state["outcomes"][phase] = {
                "status": "PASS",
                "results_artifact_sha256": evidence["results_artifact_sha256"],
            }
        if stage is GateStage.DEVELOPMENT_SHORTLIST_FROZEN:
            self.state["shortlists"]["validation"] = {
                "status": evidence["freeze_status"],
                "candidates": list(evidence["candidates"]),
                "freeze_sha256": evidence["shortlist_freeze_sha256"],
            }
        if stage is GateStage.REPLICATION_SHORTLIST_FROZEN:
            self.state["shortlists"]["replication"] = {
                "status": evidence["freeze_status"],
                "candidates": list(evidence["candidates"]),
                "freeze_sha256": evidence["shortlist_freeze_sha256"],
            }
        if stage is GateStage.FINAL_ADJUDICATION:
            self.state["final_decision"] = evidence["decision"]

    def _audit(self, action: str, payload_hash: str) -> None:
        event = {
            "sequence": len(self.state["audit"]) + 1,
            "action": action,
            "payload_sha256": payload_hash,
        }
        event["event_id"] = canonical_sha256(event)
        if not self.state["audit"] or self.state["audit"][-1] != event:
            self.state["audit"].append(event)

    def _persist_failure(self, decision: str, target: GateStage, detail: str) -> None:
        failure = {
            "decision": decision,
            "attempted_stage": target.value,
            "detail": detail,
        }
        failure["failure_id"] = canonical_sha256(failure)
        self.state["status"] = "BLOCKED"
        if self.state.get("failure") == failure:
            self.persist()
            return
        self.state["failure"] = failure
        self._audit("STAGE_BLOCKED", failure["failure_id"])
        self.persist()


def build_stage_evidence_template(stage: GateStage | str) -> dict[str, Any]:
    """Return a dry-run template containing no observations or fake outcomes."""
    target = GateStage(stage)
    template: dict[str, Any] = {
        "stage": target.value,
        "predecessor_commit_sha": None,
        "artifacts": None,
        "instrument_universe": list(AUTHORIZED_INSTRUMENTS),
        "currency_universe": list(AUTHORIZED_CURRENCIES),
        "provider_request_counts": None,
        "results_artifact_sha256": None,
        "status": "NOT_RUN",
    }
    phase = DATASET_STAGES.get(target)
    if phase is not None:
        template.update(
            {
                "dataset_freeze_id": DATASET_FREEZE_IDS[phase],
                "authorized_interval": list(PHASE_INTERVALS[phase]),
                "freeze_manifest": None,
            }
        )
    return template
