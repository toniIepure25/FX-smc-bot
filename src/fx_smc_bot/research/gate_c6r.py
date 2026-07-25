"""Gate C.6-R review and merge-readiness helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_C6_DECISION = "ACCEPTANCE_RESEARCH_PROGRAM_CLOSED_WITH_MIXED_NONTRANSPORTABLE_RESULT"
EXPECTED_MANIFEST_HASH = "9b3d806fec2a5730c30854b82cdf57f1f17b8cf185f6a6826658e3bf394808bb"
EXPECTED_SEAL_ID = "USDJPY_ACCEPTANCE_RESEARCH_LINEAGE_V1"
EXPECTED_SEAL_HASH = "00581da471f6c7c7d06d10d59c2b58fd03fab7a654bf4dac792451a829e4b1e4"
EXPECTED_SEAL_STATUS = "CLOSED_MIXED_NONTRANSPORTABLE_RESULT"
REVIEW_ID = "USDJPY_ACCEPTANCE_RESEARCH_PACKAGE_REVIEW_V1"

HOLDOUT_FLAGS = [
    "holdout_market_data_loaded",
    "holdout_structural_data_inspected",
    "holdout_files_enumerated_for_content",
    "holdout_events_detected",
    "holdout_event_counts_computed",
    "holdout_controls_constructed",
    "holdout_outcomes_computed",
    "holdout_results_reported",
]

PROHIBITED_DATA_PATTERNS = [
    ".bi5",
    ".parquet",
    "data/raw/",
    "data/canonical/",
    "node_modules/",
    "__pycache__/",
    ".pytest_tmp_",
    ".pytest_cache/",
]

MISLEADING_PHRASES = [
    "confirmed alpha",
    "profitable strategy",
    "validated trading edge",
    "guaranteed",
    "production ready strategy",
    "holdout confirmed",
    "standalone alpha",
]


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    data = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def validate_holdout_closed(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {flag: bool(payload.get(flag, False)) for flag in HOLDOUT_FLAGS}
    violations = [flag for flag, value in checks.items() if value]
    return {
        "checks": checks,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def validate_temp_ignore(gitignore_text: str) -> bool:
    return ".pytest_tmp_*/" in gitignore_text.splitlines()


def find_prohibited_paths(paths: list[str]) -> list[str]:
    lowered = [path.replace("\\", "/").lower() for path in paths]
    return [
        path
        for path in lowered
        if any(pattern in path for pattern in PROHIBITED_DATA_PATTERNS)
    ]


def find_misleading_phrases(text: str) -> list[str]:
    lowered = text.lower()
    findings = []
    for phrase in MISLEADING_PHRASES:
        index = lowered.find(phrase)
        if index < 0:
            continue
        window = lowered[max(0, index - 40) : index + len(phrase) + 40]
        if "not " in window or "no " in window or "prohibited" in window:
            continue
        findings.append(phrase)
    return findings


def validate_manifest_hash(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_manifest_hash": EXPECTED_MANIFEST_HASH,
        "observed_manifest_hash": manifest.get("manifest_hash"),
        "status": "PASS"
        if manifest.get("manifest_hash") == EXPECTED_MANIFEST_HASH
        else "FAIL",
    }


def validate_c6_seal(seal: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "seal_id": seal.get("seal_id") == EXPECTED_SEAL_ID,
        "seal_hash": seal.get("lineage_seal_hash") == EXPECTED_SEAL_HASH,
        "status": seal.get("status") == EXPECTED_SEAL_STATUS,
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def validate_claim_statuses(claims: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {
        "A": "SUPPORTED_IN_DEVELOPMENT",
        "B": "SUPPORTED_IN_VALIDATION",
        "C": "DESCRIPTIVELY_SUPPORTED_BUT_NOT_CONFIRMED",
        "D": "NOT_SUPPORTED",
        "E": "NOT_TESTED_AND_NOT_CLAIMABLE",
    }
    observed = {claim["claim_id"]: claim["status"] for claim in claims}
    checks = {claim_id: observed.get(claim_id) == status for claim_id, status in expected.items()}
    return {
        "expected": expected,
        "observed": observed,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def review_lock_hash(lock: dict[str, Any]) -> str:
    payload = {key: value for key, value in lock.items() if key != "review_lock_hash"}
    return canonical_json_sha256(payload)
