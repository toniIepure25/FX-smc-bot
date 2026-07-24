"""Gate C.5-A-R-IR artifact forensics helpers.

These helpers deliberately operate only on compact JSON artifacts. They do not
read market data, row-level event/control tables, or holdout data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

C5AR_DECISION = "USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_NOT_VALIDATED"
RECONCILIATION_ID = "C5AR_ARTIFACT_RECONCILIATION_V1"


SCIENTIFIC_KEYS = {
    "criterion",
    "criterion_number",
    "mandatory",
    "observed_value",
    "operator",
    "passed",
    "threshold",
    "final_decision",
    "all_mandatory_criteria_passed",
    "status",
}


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return raw_sha256(canonical_json_bytes(payload))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def crlf_sha256_from_lf_bytes(data: bytes) -> str:
    lf_data = data.replace(b"\r\n", b"\n")
    return raw_sha256(lf_data.replace(b"\n", b"\r\n"))


def hash_representations(data: bytes, payload: Any | None = None) -> dict[str, str]:
    lf_data = data.replace(b"\r\n", b"\n")
    result = {
        "raw_file_sha256": raw_sha256(data),
        "lf_normalized_sha256": raw_sha256(lf_data),
        "crlf_normalized_sha256": crlf_sha256_from_lf_bytes(data),
        "raw_without_trailing_lf_sha256": raw_sha256(lf_data.removesuffix(b"\n")),
        "raw_utf8_bom_prefixed_lf_sha256": raw_sha256(b"\xef\xbb\xbf" + lf_data),
    }
    if payload is not None:
        result["canonical_json_sha256"] = canonical_json_sha256(payload)
    return result


def classify_hash_match(expected_hash: str, data: bytes, payload: Any | None = None) -> str:
    hashes = hash_representations(data, payload)
    for name, digest in hashes.items():
        if digest == expected_hash:
            return name
    return "NO_MATCH"


def classify_json_path(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    if leaf == "source_hash":
        return "SOURCE_REFERENCE_ONLY"
    if leaf.endswith("hash") or leaf.endswith("_hash") or leaf == "hashes":
        return "HASH_FIELD_ONLY"
    if leaf in SCIENTIFIC_KEYS:
        if leaf == "final_decision":
            return "FINAL_DECISION_CHANGE"
        if leaf == "passed":
            return "CRITERION_STATUS_CHANGE"
        if leaf == "observed_value":
            return "SCIENTIFIC_VALUE_CHANGE"
        return "SCIENTIFIC_VALUE_CHANGE"
    return "UNKNOWN"


def semantic_diff(old: Any, new: Any, path: str = "$") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            child = f"{path}.{key}"
            if key not in old:
                changes.append(
                    {
                        "json_path": child,
                        "old_value": None,
                        "new_value": new[key],
                        "classification": "SCHEMA_ADDITION_NONSCIENTIFIC",
                        "scientific_relevance": False,
                    }
                )
            elif key not in new:
                changes.append(
                    {
                        "json_path": child,
                        "old_value": old[key],
                        "new_value": None,
                        "classification": "UNKNOWN",
                        "scientific_relevance": True,
                    }
                )
            else:
                changes.extend(semantic_diff(old[key], new[key], child))
        return changes
    if isinstance(old, list) and isinstance(new, list):
        for idx in range(max(len(old), len(new))):
            child = f"{path}[{idx}]"
            if idx >= len(old):
                changes.append(
                    {
                        "json_path": child,
                        "old_value": None,
                        "new_value": new[idx],
                        "classification": "SCHEMA_ADDITION_NONSCIENTIFIC",
                        "scientific_relevance": False,
                    }
                )
            elif idx >= len(new):
                changes.append(
                    {
                        "json_path": child,
                        "old_value": old[idx],
                        "new_value": None,
                        "classification": "UNKNOWN",
                        "scientific_relevance": True,
                    }
                )
            else:
                changes.extend(semantic_diff(old[idx], new[idx], child))
        return changes
    if old != new:
        classification = classify_json_path(path)
        changes.append(
            {
                "json_path": path,
                "old_value": old,
                "new_value": new,
                "classification": classification,
                "scientific_relevance": classification
                in {
                    "SCIENTIFIC_VALUE_CHANGE",
                    "CRITERION_STATUS_CHANGE",
                    "FINAL_DECISION_CHANGE",
                },
            }
        )
    return changes


def scientific_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [change for change in changes if change["scientific_relevance"]]


def validate_holdout_closed(holdout: dict[str, Any]) -> dict[str, Any]:
    flags = {
        "holdout_market_data_loaded": False,
        "holdout_structural_data_inspected": False,
        "holdout_events_detected": False,
        "holdout_event_counts_computed": False,
        "holdout_controls_constructed": False,
        "holdout_outcomes_computed": False,
        "holdout_results_reported": False,
    }
    observed = {name: bool(holdout.get(name, False)) for name in flags}
    violations = [name for name, value in observed.items() if value]
    return {
        "checks": observed,
        "missing_flags_treated_as_false": [
            name for name in flags if name not in holdout
        ],
        "status": "PASS" if not violations and holdout.get("status") == "PASS" else "FAIL",
        "violations": violations,
    }


def overlay_preserves_lock(
    original_lock: dict[str, Any],
    overlay: dict[str, Any],
) -> bool:
    preserved = overlay.get("preserved_original_lock_fields", {})
    return (
        overlay.get("overlay_id") == RECONCILIATION_ID
        and preserved.get("final_decision") == original_lock.get("final_decision")
        and preserved.get("status") == original_lock.get("status")
        and preserved.get("statement") == original_lock.get("statement")
    )


def c5b_handoff_ready(handoff: dict[str, Any], overlay: dict[str, Any]) -> bool:
    return (
        handoff.get("status") == "READY_TO_RESUME_C5B_PHASE_0"
        and handoff.get("reconciliation_overlay_hash")
        == overlay.get("reconciliation_overlay_hash")
        and handoff.get("require_c5b_to_validate_original_lock_and_overlay") is True
    )


@dataclass(frozen=True, slots=True)
class CompactSources:
    primary: dict[str, Any]
    inference: dict[str, Any]
    placebo: dict[str, Any]
    matching: dict[str, Any]
    holdout: dict[str, Any]
    hashes: dict[str, str]


def regenerate_adjudication(sources: CompactSources) -> dict[str, Any]:
    primary = sources.primary
    inference = sources.inference
    placebo = sources.placebo
    matching = sources.matching
    holdout = sources.holdout
    ci = inference["ci95_day_cluster_bootstrap"]
    rows = [
        (
            "artifact_integrity",
            "PASS",
            "equals",
            "PASS",
            True,
            "results/gate_c5ar/post_validation_lock.json",
        ),
        (
            "validation_data_quality",
            "PASS",
            "equals",
            "PASS",
            True,
            "results/gate_c5adqr/validation_data_quality.json",
        ),
        (
            "successfully_matched_primary_events",
            matching["successfully_matched_events"],
            ">=",
            40,
            matching["successfully_matched_events"] >= 40,
            "results/gate_c5ar/control_matching_audit.json",
        ),
        (
            "exact_key_relaxations",
            matching["exact_key_relaxations"],
            "equals",
            0,
            matching["exact_key_relaxations"] == 0,
            "results/gate_c5ar/control_matching_audit.json",
        ),
        (
            "every_post_match_abs_SMD",
            matching["post_match_smd"],
            "every_abs<=",
            0.1,
            bool(matching["balance_pass"]),
            "results/gate_c5ar/control_matching_audit.json",
        ),
        (
            "mean_event_minus_control_executable_differential",
            primary["mean_event_minus_control_points"],
            ">",
            0,
            primary["mean_event_minus_control_points"] > 0,
            "results/gate_c5ar/validation_primary_estimand.json",
        ),
        (
            "paired_permutation_p_value",
            inference["raw_permutation_p_value"],
            "<=",
            0.05,
            inference["raw_permutation_p_value"] <= 0.05,
            "results/gate_c5ar/validation_inference.json",
        ),
        (
            "95pct_day_cluster_bootstrap_CI_lower_bound",
            ci[0],
            ">",
            0,
            ci[0] > 0,
            "results/gate_c5ar/validation_inference.json",
        ),
        (
            "mean_absolute_event_executable_markout",
            primary["mean_event_executable_markout_points"],
            "<=",
            0,
            primary["mean_event_executable_markout_points"] <= 0,
            "results/gate_c5ar/validation_primary_estimand.json",
        ),
        (
            "plus_24h_placebo_reproduces_relative_resilience",
            placebo["placebo_reproduces_relative_resilience"],
            "equals",
            False,
            placebo["placebo_reproduces_relative_resilience"] is False,
            "results/gate_c5ar/validation_placebo.json",
        ),
        (
            "holdout_integrity",
            holdout["status"],
            "equals",
            "PASS",
            holdout["status"] == "PASS",
            "results/gate_c5ar/holdout_integrity.json",
        ),
    ]
    criteria = []
    for idx, (name, observed, operator, threshold, passed, artifact) in enumerate(rows, start=1):
        criteria.append(
            {
                "criterion": name,
                "criterion_number": idx,
                "mandatory": True,
                "observed_value": observed,
                "operator": operator,
                "passed": bool(passed),
                "source_artifact": artifact,
                "source_hash": sources.hashes.get(artifact),
                "threshold": threshold,
            }
        )
    all_passed = all(row["passed"] for row in criteria)
    return {
        "all_mandatory_criteria_passed": all_passed,
        "criteria": criteria,
        "final_decision": (
            "USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_VALIDATED"
            if all_passed
            else C5AR_DECISION
        ),
        "status": "PASS",
    }


def scientific_projection(adjudication: dict[str, Any]) -> dict[str, Any]:
    return {
        "all_mandatory_criteria_passed": adjudication["all_mandatory_criteria_passed"],
        "final_decision": adjudication["final_decision"],
        "status": adjudication["status"],
        "criteria": [
            {
                key: row[key]
                for key in (
                    "criterion",
                    "criterion_number",
                    "mandatory",
                    "observed_value",
                    "operator",
                    "passed",
                    "threshold",
                )
            }
            for row in adjudication["criteria"]
        ],
    }
