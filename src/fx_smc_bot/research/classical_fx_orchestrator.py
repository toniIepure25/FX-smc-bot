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


# Gate F0-RP-E2E-R is a new lineage.  The V1 names above intentionally remain
# unchanged so sealed V1 callers and tests continue to replay byte-for-byte.
V2_PROGRAM_ID: Final = "FX_CLASSICAL_RISK_PREMIA_V2"
V2_LINEAGE_ID: Final = "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V2"
V2_GATE_ID: Final = "F0_RP_E2E_REBASELINE_V1"
V2_STATE_SCHEMA_VERSION: Final = "F0RPE2ER_ORCHESTRATOR_STATE_V2"
V2_REBASELINE_ID: Final = "F0RPE2ER_FUTURE_ONLY_CONFIRMATORY_BASELINE_V1"
V2_BOUNDARY_ID: Final = "F0RPE2ER_DOCUMENTATION_DATA_BOUNDARY_V1"
V2_INFRASTRUCTURE_FREEZE_ID: Final = "F0RPE2ER_EMPIRICAL_INFRASTRUCTURE_V1"
V2_FAILED_GATE_TIP_SHA: Final = "2a2a42fd9be080ca36cc7c5f9ae5e574c4b1a2a2"
V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA: Final = (
    "313349aecc6694c1e852f1d0b2b2f6170ed81514"
)
V2_PREDECESSOR_DECISION: Final = "BLOCKED_BY_PROSPECTIVE_INTEGRITY"
V2_RELATIONSHIP: Final = (
    "SCIENTIFIC_PROTOCOL_INHERITANCE_WITH_NEW_FUTURE_ONLY_INTEGRITY_BASELINE"
)
V2_QUARANTINE_STATUS: Final = (
    "QUARANTINED_FROM_ALL_SELECTION_REPLICATION_AND_CONFIRMATORY_USE"
)
V2_FUTURE_START_RULE: Final = (
    "FIRST_COMPLETE_FX_TRADING_DAY_AFTER_FINAL_PORTFOLIO_FREEZE"
)

V2_DATASET_FREEZE_IDS: Final = {
    "development": "FX_CLASSICAL_FACTORS_DEVELOPMENT_2010_2016_V2",
    "validation": "FX_CLASSICAL_FACTORS_VALIDATION_2017_2019_V2",
    "replication": "FX_CLASSICAL_FACTORS_REPLICATION_2020_2022_V2",
}
V2_FINAL_DECISIONS: Final = frozenset(
    {
        "F0RPE2ER_PORTFOLIO_FROZEN_FOR_FUTURE_CONFIRMATION",
        "F0RPE2ER_NO_PORTFOLIO_PASSED_DEVELOPMENT",
        "F0RPE2ER_NO_PORTFOLIO_PASSED_INTERNAL_VALIDATION",
        "F0RPE2ER_NO_PORTFOLIO_SURVIVED_INDEPENDENT_REPLICATION",
        "F0RPE2ER_INFRASTRUCTURE_CERTIFIED_EMPIRICAL_EXECUTION_BLOCKED",
        "BLOCKED_BY_FAILED_GATE_PROVENANCE",
        "BLOCKED_BY_PROTOCOL_INHERITANCE",
        "BLOCKED_BY_INTEGRITY_REBASELINE",
        "BLOCKED_BY_CLEAN_ROOM_ISOLATION",
        "BLOCKED_BY_SOURCE_ALLOWLIST",
        "BLOCKED_BY_DOCUMENTATION_DATA_BOUNDARY",
        "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
        "BLOCKED_BY_RATE_SOURCE_ACCESS",
        "BLOCKED_BY_RATE_PARSE_INTEGRITY",
        "BLOCKED_BY_RATE_VINTAGE_INTEGRITY",
        "BLOCKED_BY_RATE_ALIGNMENT",
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
        "BLOCKED_BY_FUTURE_PROSPECTIVE_INTEGRITY",
    }
)


class V2GateStage(str, Enum):
    FAILED_GATE_INHERITED = "FAILED_GATE_INHERITED"
    INTEGRITY_REBASELINED = "INTEGRITY_REBASELINED"
    SOURCE_BOUNDARY_FROZEN = "SOURCE_BOUNDARY_FROZEN"
    LIVE_ADAPTERS_CERTIFIED = "LIVE_ADAPTERS_CERTIFIED"
    INFRASTRUCTURE_FROZEN = "INFRASTRUCTURE_FROZEN"
    DEVELOPMENT_RATES_ACQUIRED = "DEVELOPMENT_RATES_ACQUIRED"
    DEVELOPMENT_RATES_CERTIFIED = "DEVELOPMENT_RATES_CERTIFIED"
    DEVELOPMENT_MARKET_ACQUIRED = "DEVELOPMENT_MARKET_ACQUIRED"
    DEVELOPMENT_MARKET_CERTIFIED = "DEVELOPMENT_MARKET_CERTIFIED"
    DEVELOPMENT_DATASET_FROZEN = "DEVELOPMENT_DATASET_FROZEN"
    DEVELOPMENT_EXECUTED = "DEVELOPMENT_EXECUTED"
    VALIDATION_SHORTLIST_FROZEN = "VALIDATION_SHORTLIST_FROZEN"
    VALIDATION_DATASET_FROZEN = "VALIDATION_DATASET_FROZEN"
    VALIDATION_EXECUTED = "VALIDATION_EXECUTED"
    REPLICATION_SHORTLIST_FROZEN = "REPLICATION_SHORTLIST_FROZEN"
    REPLICATION_DATASET_FROZEN = "REPLICATION_DATASET_FROZEN"
    REPLICATION_EXECUTED = "REPLICATION_EXECUTED"
    FINAL_ADJUDICATION = "FINAL_ADJUDICATION"


V2_STAGE_ORDER: Final = tuple(V2GateStage)
V2_EXECUTION_STAGES: Final = {
    V2GateStage.DEVELOPMENT_EXECUTED: "development",
    V2GateStage.VALIDATION_EXECUTED: "validation",
    V2GateStage.REPLICATION_EXECUTED: "replication",
}
V2_DATASET_STAGES: Final = {
    V2GateStage.DEVELOPMENT_DATASET_FROZEN: "development",
    V2GateStage.VALIDATION_DATASET_FROZEN: "validation",
    V2GateStage.REPLICATION_DATASET_FROZEN: "replication",
}
V2_CERTIFY_ONLY_STAGES: Final = frozenset(
    {
        V2GateStage.FAILED_GATE_INHERITED,
        V2GateStage.INTEGRITY_REBASELINED,
        V2GateStage.SOURCE_BOUNDARY_FROZEN,
        V2GateStage.LIVE_ADAPTERS_CERTIFIED,
        V2GateStage.INFRASTRUCTURE_FROZEN,
        V2GateStage.DEVELOPMENT_RATES_CERTIFIED,
        V2GateStage.DEVELOPMENT_MARKET_CERTIFIED,
    }
)
_V2_ACQUISITION_STAGES: Final = frozenset(
    {
        V2GateStage.DEVELOPMENT_RATES_ACQUIRED,
        V2GateStage.DEVELOPMENT_MARKET_ACQUIRED,
        V2GateStage.VALIDATION_DATASET_FROZEN,
        V2GateStage.REPLICATION_DATASET_FROZEN,
    }
)
_V2_COMMIT_BOUNDARIES: Final = {
    V2GateStage.LIVE_ADAPTERS_CERTIFIED: V2GateStage.SOURCE_BOUNDARY_FROZEN,
    V2GateStage.DEVELOPMENT_RATES_ACQUIRED: V2GateStage.INFRASTRUCTURE_FROZEN,
    V2GateStage.DEVELOPMENT_MARKET_ACQUIRED: V2GateStage.DEVELOPMENT_RATES_CERTIFIED,
    V2GateStage.DEVELOPMENT_EXECUTED: V2GateStage.DEVELOPMENT_DATASET_FROZEN,
    V2GateStage.VALIDATION_DATASET_FROZEN: V2GateStage.VALIDATION_SHORTLIST_FROZEN,
    V2GateStage.VALIDATION_EXECUTED: V2GateStage.VALIDATION_DATASET_FROZEN,
    V2GateStage.REPLICATION_DATASET_FROZEN: V2GateStage.REPLICATION_SHORTLIST_FROZEN,
    V2GateStage.REPLICATION_EXECUTED: V2GateStage.REPLICATION_DATASET_FROZEN,
}


def _v2_scan_evidence(value: object, path: str = "evidence") -> None:
    """Reject numerical payloads and excluded assets while allowing policy metadata."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _ROW_LEVEL_KEYS or key_text.lower() == "metrics":
                raise EvidenceError(f"{path}.{key_text} contains prohibited numerical content")
            _v2_scan_evidence(key_text, f"{path}.key")
            _v2_scan_evidence(item, f"{path}.{key_text}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _v2_scan_evidence(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and "N" + "ZD" in value.upper():
        raise EvidenceError(f"{path} references an excluded asset")


def _v2_state(max_workers: int, clean_room_identity: str) -> dict[str, Any]:
    return {
        "schema_version": V2_STATE_SCHEMA_VERSION,
        "program_id": V2_PROGRAM_ID,
        "lineage_id": V2_LINEAGE_ID,
        "gate_id": V2_GATE_ID,
        "predecessor_program": PROGRAM_ID,
        "predecessor_gate": GATE_ID,
        "predecessor_decision": V2_PREDECESSOR_DECISION,
        "relationship": V2_RELATIONSHIP,
        "amendment_id": AMENDMENT_ID,
        "authorized_instruments": list(AUTHORIZED_INSTRUMENTS),
        "authorized_currencies": list(AUTHORIZED_CURRENCIES),
        "phase_intervals": {key: list(value) for key, value in PHASE_INTERVALS.items()},
        "quarantined_interval": ["2023-01-01", "2025-12-31"],
        "quarantine_status": V2_QUARANTINE_STATUS,
        "quarantined_interval_untouched_claim": False,
        "future_confirmatory_start_rule": V2_FUTURE_START_RULE,
        "future_observations_status": "NOT_YET_GENERATED_OR_ACCESSED",
        "max_workers": max_workers,
        "clean_room_identity_sha256": clean_room_identity,
        "status": "READY",
        "current_stage": None,
        "completed_stages": [],
        "checkpoints": {},
        "failure": None,
        "provider_requests": {"market": None, "rates": None},
        "source_snapshots": None,
        "integrity_boundary_pre_network_sha": None,
        "infrastructure_pre_observation_sha": None,
        "live_adapter_certifications": None,
        "outcomes": {
            phase: {
                "status": "NOT_RUN",
                "results_artifact_sha256": None,
                "metrics_manifest_sha256": None,
            }
            for phase in PHASE_INTERVALS
        },
        "shortlists": {
            "validation": {"status": "NOT_RUN", "candidates": None, "freeze_sha256": None},
            "replication": {"status": "NOT_RUN", "candidates": None, "freeze_sha256": None},
        },
        "final_decision": None,
        "audit": [],
    }


@dataclass(frozen=True)
class V2GatePlan:
    current_stage: str | None
    next_stages: tuple[str, ...]
    status: str
    provider_requests: Mapping[str, int | None]
    outcomes: Mapping[str, Mapping[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {
            "program_id": V2_PROGRAM_ID,
            "lineage_id": V2_LINEAGE_ID,
            "gate_id": V2_GATE_ID,
            "current_stage": self.current_stage,
            "next_stages": list(self.next_stages),
            "status": self.status,
            "provider_requests": dict(self.provider_requests),
            "outcomes": {key: dict(value) for key, value in self.outcomes.items()},
        }


class ClassicalFXV2Orchestrator:
    """Fail-closed V2 lineage orchestrator with recoverable atomic checkpoints."""

    def __init__(
        self,
        output_dir: Path,
        *,
        clean_room_root: Path,
        max_workers: int = 1,
        resume: bool = False,
    ) -> None:
        if not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        self.output_dir = Path(output_dir)
        _v2_scan_evidence(os.path.abspath(os.fspath(self.output_dir)), "output_dir")
        self.state_path = self.output_dir / "orchestrator_state_v2.json"
        self.pending_path = self.output_dir / ".orchestrator_state_v2.pending.json"
        self.clean_room_identity = self._clean_room_identity(clean_room_root)
        self._recover_pending_transition()
        if self.state_path.exists():
            if not resume:
                raise OrchestrationError("Existing V2 state requires resume=True")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._validate_loaded_state(max_workers)
        else:
            self.state = _v2_state(max_workers, self.clean_room_identity)

    @staticmethod
    def _clean_room_identity(root: Path) -> str:
        lexical = os.path.abspath(os.fspath(root))
        _v2_scan_evidence(lexical, "clean_room_root")
        return hashlib.sha256(os.path.normcase(lexical).encode("utf-8")).hexdigest()

    def _validate_loaded_state(self, max_workers: int) -> None:
        expected = {
            "schema_version": V2_STATE_SCHEMA_VERSION,
            "program_id": V2_PROGRAM_ID,
            "lineage_id": V2_LINEAGE_ID,
            "gate_id": V2_GATE_ID,
            "relationship": V2_RELATIONSHIP,
            "amendment_id": AMENDMENT_ID,
            "authorized_instruments": list(AUTHORIZED_INSTRUMENTS),
            "authorized_currencies": list(AUTHORIZED_CURRENCIES),
            "max_workers": max_workers,
            "clean_room_identity_sha256": self.clean_room_identity,
        }
        for key, value in expected.items():
            if self.state.get(key) != value:
                raise OrchestrationError(f"Resumed V2 {key} does not match the checkpoint")

    def _recover_pending_transition(self) -> None:
        if not self.pending_path.exists():
            return
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        state = pending.get("state")
        checkpoint = pending.get("checkpoint")
        checkpoint_name = pending.get("checkpoint_name")
        if (
            not isinstance(state, Mapping)
            or not isinstance(checkpoint, Mapping)
            or not isinstance(checkpoint_name, str)
            or pending.get("transaction_sha256")
            != canonical_sha256(
                {"state": state, "checkpoint": checkpoint, "checkpoint_name": checkpoint_name}
            )
        ):
            raise OrchestrationError("Invalid pending V2 checkpoint transaction")
        _atomic_write_json(self.output_dir / "checkpoints_v2" / checkpoint_name, checkpoint)
        _atomic_write_json(self.state_path, state)
        self.pending_path.unlink()

    def plan(self) -> V2GatePlan:
        return V2GatePlan(
            current_stage=self.state["current_stage"],
            next_stages=tuple(stage.value for stage in self._allowed_next_stages()),
            status=self.state["status"],
            provider_requests=self.state["provider_requests"],
            outcomes=self.state["outcomes"],
        )

    def persist(self) -> None:
        _atomic_write_json(self.state_path, self.state)

    def advance(
        self,
        stage: V2GateStage | str,
        evidence: Mapping[str, Any],
        *,
        resume: bool = False,
        certify_only: bool = False,
    ) -> dict[str, Any]:
        target = V2GateStage(stage)
        _v2_scan_evidence(evidence)
        if certify_only and target not in V2_CERTIFY_ONLY_STAGES:
            raise StageOrderError("certify-only mode cannot access data or outcomes")
        evidence_hash = canonical_sha256(evidence)
        existing = self.state["checkpoints"].get(target.value)
        if existing is not None:
            if existing["evidence_sha256"] != evidence_hash:
                raise EvidenceError("Completed V2 stage cannot be replaced")
            return self.state
        if self.state["status"] == "BLOCKED" and not resume:
            raise OrchestrationError("Blocked V2 state requires resume=True")
        if target not in self._allowed_next_stages():
            allowed = ", ".join(item.value for item in self._allowed_next_stages()) or "none"
            self._persist_failure(target, f"expected {allowed}")
            raise StageOrderError(f"Stage {target.value} is not allowed; expected {allowed}")
        try:
            normalized = self._validate_evidence(target, evidence)
        except OrchestrationError as exc:
            self._persist_failure(target, str(exc))
            raise
        checkpoint = self._checkpoint(target, evidence_hash, normalized)
        next_state = json.loads(json.dumps(self.state, allow_nan=False))
        self._apply_stage(next_state, target, normalized)
        next_state["status"] = "COMPLETE" if target is V2GateStage.FINAL_ADJUDICATION else "READY"
        next_state["failure"] = None
        next_state["current_stage"] = target.value
        next_state["completed_stages"].append(target.value)
        next_state["checkpoints"][target.value] = checkpoint
        self._append_audit(next_state, target.value, evidence_hash)
        self._persist_transition(next_state, checkpoint)
        self.state = next_state
        return self.state

    def _allowed_next_stages(self) -> tuple[V2GateStage, ...]:
        current = self.state["current_stage"]
        if current is None:
            return (V2GateStage.FAILED_GATE_INHERITED,)
        stage = V2GateStage(current)
        if stage is V2GateStage.FINAL_ADJUDICATION:
            return ()
        if stage is V2GateStage.VALIDATION_SHORTLIST_FROZEN:
            candidates = self.state["shortlists"]["validation"]["candidates"]
            return (
                (V2GateStage.VALIDATION_DATASET_FROZEN,)
                if candidates
                else (V2GateStage.FINAL_ADJUDICATION,)
            )
        if stage is V2GateStage.REPLICATION_SHORTLIST_FROZEN:
            candidates = self.state["shortlists"]["replication"]["candidates"]
            return (
                (V2GateStage.REPLICATION_DATASET_FROZEN,)
                if candidates
                else (V2GateStage.FINAL_ADJUDICATION,)
            )
        return (V2_STAGE_ORDER[V2_STAGE_ORDER.index(stage) + 1],)

    def _validate_evidence(
        self, stage: V2GateStage, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(evidence)
        normalized["stage_commit_sha"] = _validate_sha(
            evidence.get("stage_commit_sha"), commit=True, label="stage_commit_sha"
        )
        artifacts = evidence.get("artifacts")
        if not isinstance(artifacts, Mapping) or not artifacts:
            raise EvidenceError("Every V2 stage requires aggregate artifacts")
        normalized["artifacts"] = {
            str(name): _validate_sha(value, label=f"artifacts.{name}")
            for name, value in sorted(artifacts.items())
        }
        if evidence.get("instrument_universe") != list(AUTHORIZED_INSTRUMENTS):
            raise EvidenceError("V2 stage changed the instrument universe")
        if evidence.get("currency_universe") != list(AUTHORIZED_CURRENCIES):
            raise EvidenceError("V2 stage changed the currency universe")
        self._validate_commit_order(stage, evidence, normalized["stage_commit_sha"])

        if stage is V2GateStage.FAILED_GATE_INHERITED:
            self._validate_failed_gate(evidence, normalized["stage_commit_sha"])
        elif stage is V2GateStage.INTEGRITY_REBASELINED:
            self._validate_rebaseline(evidence)
        elif stage is V2GateStage.SOURCE_BOUNDARY_FROZEN:
            self._validate_source_boundary(evidence)
        elif stage is V2GateStage.LIVE_ADAPTERS_CERTIFIED:
            self._validate_live_adapters(evidence)
        elif stage is V2GateStage.INFRASTRUCTURE_FROZEN:
            if (
                evidence.get("freeze_id") != V2_INFRASTRUCTURE_FREEZE_ID
                or evidence.get("certification_status") != "PASS"
                or evidence.get("observation_access_before_freeze") is not False
            ):
                raise EvidenceError("Infrastructure must pass before observation access")
            _validate_sha(evidence.get("infrastructure_manifest_sha256"), label="manifest hash")
        elif stage in _V2_ACQUISITION_STAGES:
            self._validate_acquisition(stage, evidence)
        elif stage in {
            V2GateStage.DEVELOPMENT_RATES_CERTIFIED,
            V2GateStage.DEVELOPMENT_MARKET_CERTIFIED,
        }:
            if evidence.get("certification_status") != "PASS":
                raise EvidenceError("Certification stage requires PASS")
        if stage in V2_DATASET_STAGES:
            self._validate_dataset_freeze(V2_DATASET_STAGES[stage], evidence)
        if stage in V2_EXECUTION_STAGES:
            self._validate_execution(V2_EXECUTION_STAGES[stage], evidence)
        if stage is V2GateStage.VALIDATION_SHORTLIST_FROZEN:
            self._validate_shortlist(
                evidence,
                maximum=4,
                status="FROZEN_BEFORE_VALIDATION_DATA_ACCESS",
            )
        if stage is V2GateStage.REPLICATION_SHORTLIST_FROZEN:
            self._validate_shortlist(
                evidence, maximum=2, status="FROZEN_BEFORE_REPLICATION_DATA_ACCESS"
            )
        if stage is V2GateStage.FINAL_ADJUDICATION:
            self._validate_final(evidence)
        return normalized

    def _validate_commit_order(
        self, stage: V2GateStage, evidence: Mapping[str, Any], stage_commit: str
    ) -> None:
        if stage is V2GateStage.FAILED_GATE_INHERITED:
            if stage_commit != V2_FAILED_GATE_TIP_SHA:
                raise EvidenceError("Failed-gate inheritance must start at the sealed V1 tip")
            return
        current = V2GateStage(self.state["current_stage"])
        previous_commit = self.state["checkpoints"][current.value]["stage_commit_sha"]
        if evidence.get("predecessor_stage_commit_sha") != previous_commit:
            raise EvidenceError("Stage does not bind the immediately preceding commit")
        boundary = _V2_COMMIT_BOUNDARIES.get(stage)
        if boundary is not None:
            boundary_commit = self.state["checkpoints"][boundary.value]["stage_commit_sha"]
            if evidence.get("access_predecessor_commit_sha") != boundary_commit:
                raise EvidenceError("Stage does not bind the required pre-access commit")
            if stage_commit == boundary_commit:
                raise EvidenceError("Access or outcomes must occur after the boundary commit")

    def _validate_failed_gate(self, evidence: Mapping[str, Any], stage_commit: str) -> None:
        if (
            evidence.get("inheritance_status") != "FAILED_GATE_PRESERVED_NOT_REVERSED"
            or evidence.get("failed_gate_tip_sha") != stage_commit
            or evidence.get("predecessor_decision") != V2_PREDECESSOR_DECISION
            or evidence.get("failed_integrity_audit_preserved") is not True
            or evidence.get("exposed_documentation_record_preserved") is not True
        ):
            raise EvidenceError("Failed V1 gate provenance was not preserved exactly")

    def _validate_rebaseline(self, evidence: Mapping[str, Any]) -> None:
        if (
            evidence.get("rebaseline_id") != V2_REBASELINE_ID
            or evidence.get("quarantine_status") != V2_QUARANTINE_STATUS
            or evidence.get("untouched_claim") is not False
            or evidence.get("future_confirmatory_start_rule") != V2_FUTURE_START_RULE
            or evidence.get("future_observations_status")
            != "NOT_YET_GENERATED_OR_ACCESSED"
            or evidence.get("clean_room_identity_sha256") != self.clean_room_identity
            or evidence.get("clean_room_certification_status") != "PASS"
        ):
            raise EvidenceError("Future-only integrity rebaseline is incomplete")

    @staticmethod
    def _validate_source_boundary(evidence: Mapping[str, Any]) -> None:
        if (
            evidence.get("stage_commit_sha") != V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA
            or evidence.get("boundary_id") != V2_BOUNDARY_ID
            or evidence.get("boundary_status") != "PASS"
            or evidence.get("metadata_class_supplies_numerical_observations") is not False
            or evidence.get("numerical_class_requires_server_side_bounds") is not True
            or evidence.get("official_source_count") != len(AUTHORIZED_CURRENCIES)
            or evidence.get("maximum_authorized_date") != "2022-12-31"
        ):
            raise EvidenceError("Documentation/data source boundary is incomplete")
        _validate_sha(evidence.get("source_allowlist_sha256"), label="source allowlist hash")

    def _validate_live_adapters(self, evidence: Mapping[str, Any]) -> None:
        matrix = evidence.get("adapter_certifications")
        source_checkpoint = self.state["checkpoints"][
            V2GateStage.SOURCE_BOUNDARY_FROZEN.value
        ]
        if (
            evidence.get("certification_mode") != "LIVE_OFFICIAL_BOUNDED"
            or not isinstance(matrix, Mapping)
            or set(matrix) != set(AUTHORIZED_CURRENCIES)
            or any(status != "PASS" for status in matrix.values())
            or evidence.get("source_boundary_checkpoint_sha256")
            != source_checkpoint["evidence_sha256"]
            or evidence.get("integrity_boundary_pre_network_sha")
            != V2_INTEGRITY_BOUNDARY_PRE_NETWORK_SHA
            or evidence.get("response_firewall_status") != "PASS"
            or evidence.get("server_side_date_bounds_status") != "PASS"
            or evidence.get("eonia_estr_transition_status") != "PASS"
        ):
            raise EvidenceError("Live V2 adapter certification is incomplete")

    @staticmethod
    def _validate_storage_recheck(value: object, stage: V2GateStage) -> None:
        if not isinstance(value, Mapping):
            raise EvidenceError("Acquisition requires a storage recheck")
        if (
            value.get("status") != "PASS"
            or value.get("checked_for_stage") != stage.value
            or not isinstance(value.get("free_bytes"), int)
            or not isinstance(value.get("required_bytes"), int)
            or value["required_bytes"] <= 0
            or value["free_bytes"] < value["required_bytes"]
        ):
            raise EvidenceError("Storage recheck is missing, stale, or insufficient")
        _validate_sha(value.get("evidence_sha256"), label="storage recheck hash")

    def _validate_acquisition(self, stage: V2GateStage, evidence: Mapping[str, Any]) -> None:
        infrastructure = self.state["checkpoints"].get(V2GateStage.INFRASTRUCTURE_FROZEN.value)
        live = self.state["checkpoints"].get(V2GateStage.LIVE_ADAPTERS_CERTIFIED.value)
        certifications = self.state.get("live_adapter_certifications")
        if (
            infrastructure is None
            or evidence.get("infrastructure_pre_observation_sha")
            != infrastructure["stage_commit_sha"]
        ):
            raise EvidenceError("Acquisition requires the committed infrastructure freeze")
        if (
            live is None
            or evidence.get("live_adapter_certification_sha256") != live["evidence_sha256"]
            or not isinstance(certifications, Mapping)
            or set(certifications) != set(AUTHORIZED_CURRENCIES)
            or any(status != "PASS" for status in certifications.values())
        ):
            raise EvidenceError("Acquisition requires all seven live official adapters to pass")
        if stage in {
            V2GateStage.VALIDATION_DATASET_FROZEN,
            V2GateStage.REPLICATION_DATASET_FROZEN,
        }:
            checks = evidence.get("storage_rechecks")
            if not isinstance(checks, Mapping) or set(checks) != {"rates", "market"}:
                raise EvidenceError("Conditional acquisition requires two storage rechecks")
            self._validate_storage_recheck(checks["rates"], stage)
            self._validate_storage_recheck(checks["market"], stage)
            if evidence.get("acquisition_order") != "RATES_CERTIFIED_BEFORE_MARKET":
                raise EvidenceError("Conditional rates must be certified before market access")
        else:
            self._validate_storage_recheck(evidence.get("storage_recheck"), stage)
        counts = evidence.get("provider_request_counts")
        expected = (
            {"rates"}
            if stage is V2GateStage.DEVELOPMENT_RATES_ACQUIRED
            else {"market"}
            if stage is V2GateStage.DEVELOPMENT_MARKET_ACQUIRED
            else {"rates", "market"}
        )
        if (
            not isinstance(counts, Mapping)
            or set(counts) != expected
            or any(not isinstance(count, int) or count <= 0 for count in counts.values())
        ):
            raise EvidenceError("Provider request counts must be positive and stage-specific")
        if evidence.get("response_scope_status") != "PASS":
            raise EvidenceError("Acquisition response scope must pass atomically")

    @staticmethod
    def _validate_dataset_freeze(phase: str, evidence: Mapping[str, Any]) -> None:
        if (
            evidence.get("dataset_freeze_id") != V2_DATASET_FREEZE_IDS[phase]
            or evidence.get("authorized_interval") != list(PHASE_INTERVALS[phase])
            or evidence.get("rate_certification_status") != "PASS"
            or evidence.get("market_certification_status") != "PASS"
        ):
            raise EvidenceError(f"{phase.title()} V2 dataset freeze is incomplete")
        manifest = evidence.get("freeze_manifest")
        required = {
            "market_hashes",
            "m1_hashes",
            "m5_hashes",
            "source_snapshot_hashes",
            "rate_version_ids_hash",
            "aligned_panel_hash",
            "calendar_versions_hash",
            "parser_versions_hash",
            "software_sha",
        }
        if not isinstance(manifest, Mapping) or set(manifest) != required:
            raise EvidenceError("V2 dataset freeze manifest is incomplete")
        for name, value in manifest.items():
            _validate_sha(value, commit=name == "software_sha", label=f"freeze_manifest.{name}")

    def _validate_execution(self, phase: str, evidence: Mapping[str, Any]) -> None:
        freeze_stage = {
            "development": V2GateStage.DEVELOPMENT_DATASET_FROZEN,
            "validation": V2GateStage.VALIDATION_DATASET_FROZEN,
            "replication": V2GateStage.REPLICATION_DATASET_FROZEN,
        }[phase]
        checkpoint = self.state["checkpoints"].get(freeze_stage.value)
        if checkpoint is None or evidence.get("dataset_checkpoint_sha256") != checkpoint[
            "evidence_sha256"
        ]:
            raise EvidenceError("Outcome evidence is not bound to the frozen V2 dataset")
        if (
            evidence.get("execution_status") != "PASS"
            or evidence.get("metrics_status") != "COMPLETE"
        ):
            raise EvidenceError("Execution requires complete, non-placeholder metrics")
        results_hash = _validate_sha(
            evidence.get("results_artifact_sha256"), label="results artifact hash"
        )
        metrics_hash = _validate_sha(
            evidence.get("metrics_manifest_sha256"), label="metrics manifest hash"
        )
        if results_hash in {"0" * 64, "f" * 64} or metrics_hash in {"0" * 64, "f" * 64}:
            raise EvidenceError("Placeholder outcome hashes are prohibited")
        expected = (
            FROZEN_CANDIDATES
            if phase == "development"
            else self.state["shortlists"][phase]["candidates"]
        )
        if evidence.get("candidate_ids") != list(expected or ()):
            raise EvidenceError(f"{phase.title()} candidate set changed")

    @staticmethod
    def _validate_shortlist(evidence: Mapping[str, Any], *, maximum: int, status: str) -> None:
        candidates = evidence.get("candidates")
        if (
            not isinstance(candidates, list)
            or len(candidates) > maximum
            or len(set(candidates)) != len(candidates)
            or any(candidate not in FROZEN_CANDIDATES for candidate in candidates)
            or evidence.get("freeze_status") != status
        ):
            raise EvidenceError("V2 shortlist is not a frozen subset of the six candidates")
        _validate_sha(evidence.get("shortlist_freeze_sha256"), label="shortlist hash")

    def _validate_final(self, evidence: Mapping[str, Any]) -> None:
        decision = evidence.get("decision")
        if decision not in V2_FINAL_DECISIONS:
            raise EvidenceError("Final V2 decision is outside the frozen decision set")
        validation = self.state["shortlists"]["validation"]["candidates"]
        replication = self.state["shortlists"]["replication"]["candidates"]
        if decision == "F0RPE2ER_NO_PORTFOLIO_PASSED_DEVELOPMENT" and validation:
            raise EvidenceError("Development decision conflicts with its shortlist")
        if decision == "F0RPE2ER_NO_PORTFOLIO_PASSED_INTERNAL_VALIDATION" and replication:
            raise EvidenceError("Validation decision conflicts with its shortlist")
        if decision == "F0RPE2ER_PORTFOLIO_FROZEN_FOR_FUTURE_CONFIRMATION":
            selected = evidence.get("selected_candidates")
            if (
                not isinstance(selected, list)
                or len(selected) != 1
                or selected[0] not in (replication or [])
                or evidence.get("future_freeze_status")
                != "FROZEN_BEFORE_FUTURE_DATA_GENERATION"
                or evidence.get("future_observations_accessed") is not False
                or evidence.get("minimum_eligible_trading_days") != 252
                or evidence.get("minimum_calendar_months") != 12
            ):
                raise EvidenceError("Future portfolio protocol is incomplete or retrospective")

    def _checkpoint(
        self, stage: V2GateStage, evidence_hash: str, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        checkpoint = {
            "stage": stage.value,
            "evidence_sha256": evidence_hash,
            "stage_commit_sha": evidence["stage_commit_sha"],
            "artifact_hashes": evidence["artifacts"],
            "task_identity": canonical_sha256(
                {
                    "program_id": V2_PROGRAM_ID,
                    "lineage_id": V2_LINEAGE_ID,
                    "stage": stage.value,
                    "evidence_sha256": evidence_hash,
                }
            ),
        }
        checkpoint["checkpoint_sha256"] = canonical_sha256(checkpoint)
        return checkpoint

    @staticmethod
    def _apply_stage(
        state: dict[str, Any], stage: V2GateStage, evidence: Mapping[str, Any]
    ) -> None:
        if stage in _V2_ACQUISITION_STAGES:
            for kind, count in evidence["provider_request_counts"].items():
                previous = state["provider_requests"][kind]
                state["provider_requests"][kind] = (previous or 0) + count
        if stage in V2_EXECUTION_STAGES:
            phase = V2_EXECUTION_STAGES[stage]
            state["outcomes"][phase] = {
                "status": "PASS",
                "results_artifact_sha256": evidence["results_artifact_sha256"],
                "metrics_manifest_sha256": evidence["metrics_manifest_sha256"],
            }
        if stage is V2GateStage.VALIDATION_SHORTLIST_FROZEN:
            state["shortlists"]["validation"] = {
                "status": evidence["freeze_status"],
                "candidates": list(evidence["candidates"]),
                "freeze_sha256": evidence["shortlist_freeze_sha256"],
            }
        if stage is V2GateStage.REPLICATION_SHORTLIST_FROZEN:
            state["shortlists"]["replication"] = {
                "status": evidence["freeze_status"],
                "candidates": list(evidence["candidates"]),
                "freeze_sha256": evidence["shortlist_freeze_sha256"],
            }
        if stage is V2GateStage.FINAL_ADJUDICATION:
            state["final_decision"] = evidence["decision"]
        if stage is V2GateStage.SOURCE_BOUNDARY_FROZEN:
            state["integrity_boundary_pre_network_sha"] = evidence["stage_commit_sha"]
        if stage is V2GateStage.LIVE_ADAPTERS_CERTIFIED:
            state["live_adapter_certifications"] = dict(evidence["adapter_certifications"])
        if stage is V2GateStage.INFRASTRUCTURE_FROZEN:
            state["infrastructure_pre_observation_sha"] = evidence["stage_commit_sha"]

    def _persist_transition(
        self, next_state: Mapping[str, Any], checkpoint: Mapping[str, Any]
    ) -> None:
        number = len(next_state["completed_stages"])
        name = f"{number:02d}-{checkpoint['stage']}.json"
        body: dict[str, Any] = {
            "state": next_state,
            "checkpoint": checkpoint,
            "checkpoint_name": name,
        }
        body["transaction_sha256"] = canonical_sha256(body)
        _atomic_write_json(self.pending_path, body)
        _atomic_write_json(self.output_dir / "checkpoints_v2" / name, checkpoint)
        _atomic_write_json(self.state_path, next_state)
        self.pending_path.unlink()

    def _persist_failure(self, target: V2GateStage, detail: str) -> None:
        failure = {
            "decision": "BLOCKED_BY_EMPIRICAL_ORCHESTRATION",
            "attempted_stage": target.value,
            "detail": detail,
        }
        failure["failure_id"] = canonical_sha256(failure)
        self.state["status"] = "BLOCKED"
        self.state["failure"] = failure
        self._append_audit(self.state, "STAGE_BLOCKED", failure["failure_id"])
        self.persist()

    @staticmethod
    def _append_audit(state: dict[str, Any], action: str, payload_hash: str) -> None:
        event = {
            "sequence": len(state["audit"]) + 1,
            "action": action,
            "payload_sha256": payload_hash,
        }
        event["event_id"] = canonical_sha256(event)
        state["audit"].append(event)


F0RPE2EROrchestrator = ClassicalFXV2Orchestrator


def build_v2_stage_evidence_template(stage: V2GateStage | str) -> dict[str, Any]:
    """Return a V2 schema template without observations or placeholder metrics."""
    target = V2GateStage(stage)
    return {
        "stage": target.value,
        "stage_commit_sha": None,
        "predecessor_stage_commit_sha": None,
        "access_predecessor_commit_sha": None,
        "artifacts": None,
        "instrument_universe": list(AUTHORIZED_INSTRUMENTS),
        "currency_universe": list(AUTHORIZED_CURRENCIES),
        "storage_recheck": None,
        "integrity_boundary_pre_network_sha": None,
        "infrastructure_pre_observation_sha": None,
        "live_adapter_certification_sha256": None,
        "provider_request_counts": None,
        "results_artifact_sha256": None,
        "metrics_manifest_sha256": None,
        "status": "NOT_RUN",
    }
