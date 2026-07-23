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
