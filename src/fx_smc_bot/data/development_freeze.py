"""Development dataset freeze validation helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FreezeValidationResult:
    """Result of validating a downstream research freeze."""

    passed: bool
    reasons: list[str]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def validate_ready_development_freeze(
    freeze_path: Path,
    expected_manifest_hash: str,
    expected_canonical_checksum_set_hash: str,
    requested_pairs: list[str],
) -> FreezeValidationResult:
    """Validate that downstream research can use a development freeze.

    The function deliberately requires a READY freeze and exact manifest/hash
    matches before any research command can proceed.
    """
    reasons: list[str] = []
    if not freeze_path.exists():
        return FreezeValidationResult(False, ["freeze file missing"])

    freeze = _load_json(freeze_path)
    if freeze.get("status") != "READY":
        reasons.append("freeze status is not READY")

    if freeze.get("monthly_quality_manifest_hash") != expected_manifest_hash:
        reasons.append("monthly quality manifest hash mismatch")

    if (
        freeze.get("canonical_checksum_set_hash")
        != expected_canonical_checksum_set_hash
    ):
        reasons.append("canonical checksum set hash mismatch")

    allowed = set(freeze.get("selected_research_universe", []))
    missing = sorted(set(requested_pairs) - allowed)
    if missing:
        reasons.append(f"requested pairs outside research universe: {missing}")

    return FreezeValidationResult(not reasons, reasons)


def freeze_scope_hash(freeze: dict[str, Any]) -> str:
    """Hash the pair-scoped dataset identity used by downstream commands."""
    import hashlib

    scoped = {
        "audit_hash": freeze.get("development_audit_hash"),
        "canonical_checksums": freeze.get("included_canonical_checksums", {}),
        "certification_hash": freeze.get("development_certification_hash"),
        "scope": freeze.get("scope"),
        "selected_research_universe": freeze.get("selected_research_universe", []),
    }
    payload = json.dumps(scoped, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_pair_scoped_development_freeze(
    freeze_path: Path,
    requested_pairs: list[str],
    expected_audit_hash: str,
    expected_certification_hash: str,
    expected_pair_checksums: dict[str, str],
) -> FreezeValidationResult:
    """Validate a READY pair-scoped development freeze.

    Unlike the legacy all-pair check, this permits excluded pairs to remain
    exploratory as long as every requested pair is inside the certified universe
    and every included pair checksum matches the freeze.
    """
    reasons: list[str] = []
    if not freeze_path.exists():
        return FreezeValidationResult(False, ["freeze file missing"])

    freeze = _load_json(freeze_path)
    if freeze.get("status") != "READY":
        reasons.append("freeze status is not READY")
    if freeze.get("scope") != "PAIR_SCOPED":
        reasons.append("freeze scope is not PAIR_SCOPED")

    allowed = set(freeze.get("selected_research_universe", []))
    requested = set(requested_pairs)
    outside = sorted(requested - allowed)
    if outside:
        reasons.append(f"requested pairs outside research universe: {outside}")

    if freeze.get("development_audit_hash") != expected_audit_hash:
        reasons.append("development audit hash mismatch")
    if freeze.get("development_certification_hash") != expected_certification_hash:
        reasons.append("development certification hash mismatch")

    included_checksums = freeze.get("included_canonical_checksums", {})
    for pair in sorted(requested):
        expected = expected_pair_checksums.get(pair)
        actual = included_checksums.get(pair)
        if expected is None:
            reasons.append(f"missing expected checksum for requested pair: {pair}")
        elif actual != expected:
            reasons.append(f"canonical checksum mismatch for {pair}")

    return FreezeValidationResult(not reasons, reasons)
