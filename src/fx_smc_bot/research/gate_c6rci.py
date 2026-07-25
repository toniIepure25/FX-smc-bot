"""Gate C.6-R-CI Ruff-remediation certification helpers."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REVIEW_ID_V1 = "USDJPY_ACCEPTANCE_RESEARCH_PACKAGE_REVIEW_V1"
REVIEW_ID_V2 = "USDJPY_ACCEPTANCE_RESEARCH_PACKAGE_REVIEW_V2"
APPROVED_FOR_MERGE = "ACCEPTANCE_RESEARCH_PACKAGE_APPROVED_FOR_MERGE"
EXPECTED_RUFF_TARGET_COUNT = 99
EXPECTED_RUFF_PRE_COUNT = 124
EXPECTED_RUFF_NEW_PRE_COUNT = 25
EXPECTED_RUFF_POST_COUNT = 99
EXPECTED_RUFF_NEW_POST_COUNT = 0
EXPECTED_MYPY_TARGET_COUNT = 4
EXPECTED_MYPY_HEAD_COUNT = 3

TOUCHED_SOURCE_FILES = [
    "src/fx_smc_bot/research/intraday_campaign.py",
    "src/fx_smc_bot/research/overfitting.py",
    "src/fx_smc_bot/research/placebos.py",
    "src/fx_smc_bot/research/prop_simulation.py",
    "src/fx_smc_bot/research/statistical_inference.py",
]

PROHIBITED_HOLDOUT_ACTIONS = [
    "holdout_market_data_loaded",
    "holdout_structural_data_inspected",
    "holdout_files_enumerated_for_content",
    "holdout_events_detected",
    "holdout_event_counts_computed",
    "holdout_controls_constructed",
    "holdout_outcomes_computed",
    "holdout_results_reported",
]

RUFF_SUPPRESSION_MARKERS = [
    "# ruff: noqa",
    "# noqa",
    "per-file-ignores",
    "extend-ignore",
    "ignore =",
]


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def repo_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    for marker in ("FX-smc-bot-c6rci-main/", "FX-smc-bot/"):
        if marker in normalized:
            return normalized.split(marker, 1)[1]
    return normalized


def normalize_message(message: str) -> str:
    return " ".join(message.split())


def ruff_finding_identity(finding: dict[str, Any]) -> str:
    source = finding.get("source_line") or finding.get("source") or ""
    source_hash = hashlib.sha256(str(source).strip().encode("utf-8")).hexdigest()
    parts = [
        repo_relative_path(str(finding.get("filename") or finding.get("relative_path") or "")),
        str(finding.get("code") or finding.get("rule_code") or ""),
        normalize_message(str(finding.get("message") or "")),
        source_hash,
    ]
    return "|".join(parts)


def enrich_ruff_source_lines(
    findings: list[dict[str, Any]],
    source_root: Path | None = None,
) -> list[dict[str, Any]]:
    enriched = []
    for finding in findings:
        item = dict(finding)
        if item.get("source_line"):
            enriched.append(item)
            continue
        filename = item.get("filename")
        row = (item.get("location") or {}).get("row")
        if filename and isinstance(row, int):
            path = Path(str(filename))
            if not path.is_absolute() and source_root is not None:
                path = source_root / path
            if path.exists():
                lines = path.read_text(encoding="utf-8").splitlines()
                if 1 <= row <= len(lines):
                    item["source_line"] = lines[row - 1].strip()
        enriched.append(item)
    return enriched


def ruff_delta(
    target_findings: list[dict[str, Any]],
    head_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    target_ids = [ruff_finding_identity(item) for item in target_findings]
    head_ids = [ruff_finding_identity(item) for item in head_findings]
    target_counts = Counter(target_ids)
    head_counts = Counter(head_ids)
    ambiguous = sorted(
        identity
        for identity, count in (target_counts | head_counts).items()
        if target_counts[identity] > 1 or head_counts[identity] > 1
    )
    if ambiguous:
        return {
            "target_count": len(target_findings),
            "head_count": len(head_findings),
            "new_on_branch_count": None,
            "fixed_on_branch_count": None,
            "ambiguous_identities": ambiguous,
            "status": "AMBIGUOUS_FINDING_IDENTITY",
        }
    target_set = set(target_ids)
    head_set = set(head_ids)
    new_on_branch = sorted(head_set - target_set)
    fixed_on_branch = sorted(target_set - head_set)
    return {
        "target_count": len(target_findings),
        "head_count": len(head_findings),
        "new_on_branch_count": len(new_on_branch),
        "fixed_on_branch_count": len(fixed_on_branch),
        "new_on_branch": new_on_branch,
        "fixed_on_branch": fixed_on_branch,
        "ambiguous_identities": [],
        "status": "PASS",
    }


def _signature_inventory(tree: ast.Module) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(
            node,
            ast.FunctionDef | ast.AsyncFunctionDef,
        ) and not node.name.startswith("_"):
            entries.append({"name": node.name, "args": ast.dump(node.args)})
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    and not child.name.startswith("_")
                ):
                    entries.append(
                        {"name": f"{node.name}.{child.name}", "args": ast.dump(child.args)}
                    )
    return entries


def _public_symbol_inventory(tree: ast.Module) -> list[dict[str, str]]:
    symbols: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                symbols.append({"name": node.name, "kind": type(node).__name__})
    return symbols


def _constant_inventory(tree: ast.Module) -> list[dict[str, str]]:
    constants: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if not targets:
                continue
            if all(target.isupper() for target in targets):
                constants.append({"name": ",".join(targets), "value_ast": ast.dump(node.value)})
    return constants


def _exception_inventory(tree: ast.Module) -> list[str]:
    entries: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            entries.append(ast.dump(node.exc) if node.exc is not None else "raise")
        if isinstance(node, ast.ExceptHandler):
            entries.append(ast.dump(node.type) if node.type is not None else "except")
    return sorted(entries)


def semantic_fingerprint(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    return {
        "path": path.as_posix(),
        "raw_sha256": raw_sha256(path),
        "lf_normalized_sha256": hashlib.sha256(
            text.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest(),
        "ast_dump_hash": hashlib.sha256(ast.dump(tree).encode("utf-8")).hexdigest(),
        "public_symbol_inventory": _public_symbol_inventory(tree),
        "function_class_signature_inventory": _signature_inventory(tree),
        "module_constant_inventory": _constant_inventory(tree),
        "exception_inventory": _exception_inventory(tree),
    }


def semantic_equivalence(
    pre_files: list[dict[str, Any]],
    post_files: list[dict[str, Any]],
) -> dict[str, Any]:
    pre_by_path = {item["path"]: item for item in pre_files}
    post_by_path = {repo_relative_path(item["path"]): item for item in post_files}
    file_checks = []
    for path, pre in pre_by_path.items():
        post = post_by_path[path]
        checks = {
            "public_symbols_preserved": pre["public_symbol_inventory"]
            == post["public_symbol_inventory"],
            "public_signatures_preserved": pre["function_class_signature_inventory"]
            == post["function_class_signature_inventory"],
            "module_constants_preserved": pre["module_constant_inventory"]
            == post["module_constant_inventory"],
            "exception_behavior_preserved": (
                "exception_inventory" not in pre
                or pre.get("exception_inventory", []) == post.get("exception_inventory", [])
            ),
            "not_c6_sealed_manifest_source": pre.get("sealed_manifest_references_hash") is False,
        }
        file_checks.append(
            {"path": path, "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
        )
    return {
        "files": file_checks,
        "status": "PASS" if all(item["status"] == "PASS" for item in file_checks) else "FAIL",
    }


def find_ruff_suppressions(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    return [marker for marker in RUFF_SUPPRESSION_MARKERS if marker in lowered]


def validate_holdout_closed(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {flag: bool(payload.get(flag, False)) for flag in PROHIBITED_HOLDOUT_ACTIONS}
    violations = [flag for flag, value in checks.items() if value]
    return {
        "checks": checks,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def validate_review_supersession(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "v1_review_lock_preserved": payload.get("v1_review_id") == REVIEW_ID_V1,
        "v2_review_id_present": payload.get("v2_review_id") == REVIEW_ID_V2,
        "v1_blocker_recorded": payload.get("v1_blocking_reason") == "25_NEW_BRANCH_RUFF_FINDINGS",
        "v2_supersedes_v1": payload.get("v2_supersedes_v1") is True,
        "decision_is_merge_approval": payload.get("final_decision") == APPROVED_FOR_MERGE,
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
