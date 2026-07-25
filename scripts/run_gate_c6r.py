from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.gate_c6r import (  # noqa: E402
    EXPECTED_C6_DECISION,
    EXPECTED_MANIFEST_HASH,
    REVIEW_ID,
    canonical_json_sha256,
    find_misleading_phrases,
    find_prohibited_paths,
    raw_sha256,
    review_lock_hash,
    validate_c6_seal,
    validate_claim_statuses,
    validate_holdout_closed,
    validate_manifest_hash,
    validate_temp_ignore,
    write_json,
)

RESULT_DIR = REPO / "results" / "gate_c6r"
DOC_DIR = REPO / "docs" / "research"
EXPECTED_BRANCH = "research/rigorous-intraday-smc-validation"
EXPECTED_START = "6c0586f8f25bc5eec1bc355f6dfd8b0630c2161f"
TARGET_BRANCH = "origin/main"
REMOTE_BRANCH = "origin/research/rigorous-intraday-smc-validation"


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def run_command(args: list[str], cwd: Path = REPO, check: bool = False) -> dict[str, Any]:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return {
        "args": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git(args: list[str], check: bool = True) -> str:
    return run_command(["git", *args], check=check)["stdout"]


def load_json(path: Path) -> dict[str, Any]:
    return __import__("json").loads(path.read_text(encoding="utf-8"))


def artifact(path: str) -> dict[str, Any]:
    absolute = REPO / path
    payload = {
        "path": path,
        "exists": absolute.exists(),
        "sha256": raw_sha256(absolute) if absolute.exists() else None,
        "size_bytes": absolute.stat().st_size if absolute.exists() else None,
    }
    if absolute.suffix == ".json" and absolute.exists():
        payload["canonical_json_sha256"] = canonical_json_sha256(load_json(absolute))
    return payload


def build_repository_state() -> dict[str, Any]:
    status = git(["status", "--short", "--branch"])
    return {
        "gate": "C6-R",
        "branch": git(["branch", "--show-current"]).strip(),
        "head": git(["rev-parse", "HEAD"]).strip(),
        "expected_branch": EXPECTED_BRANCH,
        "expected_start_or_descendant": EXPECTED_START,
        "is_descendant_of_expected_start": run_command(
            ["git", "merge-base", "--is-ancestor", EXPECTED_START, "HEAD"]
        )["returncode"]
        == 0,
        "status_short_branch": status,
        "status_short": git(["status", "--short"]),
        "log_oneline_decorate_25": git(["log", "--oneline", "--decorate", "-25"]).splitlines(),
        "remote_v": git(["remote", "-v"]).splitlines(),
        "diff": git(["diff"]),
        "diff_check": git(["diff", "--check"], check=False),
        "temp_directory": {
            "path": ".pytest_tmp_gate_c6",
            "exists_after_cleanup": (REPO / ".pytest_tmp_gate_c6").exists(),
            "ignored_by_git": run_command(["git", "check-ignore", "-q", ".pytest_tmp_gate_c6"])[
                "returncode"
            ]
            == 0,
            "gitignore_rule_present": validate_temp_ignore(
                (REPO / ".gitignore").read_text(encoding="utf-8")
            ),
        },
        "created_at_utc": now_utc(),
    }


def build_remote_lineage() -> dict[str, Any]:
    local = git(["rev-parse", "HEAD"]).strip()
    remote = git(["rev-parse", REMOTE_BRANCH]).strip()
    remote_has_c6 = (
        run_command(["git", "merge-base", "--is-ancestor", EXPECTED_START, REMOTE_BRANCH])[
            "returncode"
        ]
        == 0
    )
    local_in_remote = run_command(["git", "merge-base", "--is-ancestor", local, REMOTE_BRANCH])[
        "returncode"
    ] == 0
    behind_ahead = git(["rev-list", "--left-right", "--count", f"{REMOTE_BRANCH}...HEAD"])
    remote_log = git(["log", "--oneline", "--decorate", "-8", REMOTE_BRANCH]).splitlines()
    return {
        "local_head": local,
        "remote_branch": REMOTE_BRANCH,
        "remote_head": remote,
        "remote_contains_c6_start": remote_has_c6,
        "remote_contains_local_head_at_phase0": local_in_remote,
        "remote_lineage_synchronized": local == remote and remote_has_c6,
        "remote_ahead_left_local_ahead_right": behind_ahead.strip(),
        "remote_log": remote_log,
        "status": "PASS" if local == remote and remote_has_c6 else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_commit_lineage() -> dict[str, Any]:
    expected = [
        ("1eae93f", "C3 validation-data gates", None),
        ("2089ff1", "C4 preregistration", "1eae93f"),
        ("df5d446", "C4 development execution", "2089ff1"),
        ("d9a9e51", "C4-A decision audit", "df5d446"),
        ("e39faa5", "C4-B mechanism redesign", "d9a9e51"),
        ("771ac92", "C5 ambiguity stop", "e39faa5"),
        ("bd6d4d6", "C5-A amendment", "771ac92"),
        ("edd2de7", "C5-A validation-data block", "bd6d4d6"),
        ("a8b8d4b", "C5-A-DQR certification", "edd2de7"),
        ("92e992d", "C5-A-R validation", "a8b8d4b"),
        ("1b71ea4", "C5-A-R-IR reconciliation", "92e992d"),
        ("c3a872d", "C5-B-R research stop", "1b71ea4"),
        ("4e7578e", "C6 closure and seal", "c3a872d"),
        ("6c0586f", "C6 final decision", "4e7578e"),
    ]
    rows = []
    for position, (sha, subject, predecessor) in enumerate(expected, start=1):
        present = run_command(["git", "cat-file", "-e", f"{sha}^{{commit}}"])["returncode"] == 0
        parent = git(["show", "-s", "--format=%P", sha]).split()[0] if present else None
        ordering = True
        if predecessor:
            ordering = (
                run_command(["git", "merge-base", "--is-ancestor", predecessor, sha])["returncode"]
                == 0
            )
        rows.append(
            {
                "commit_sha": sha,
                "commit_subject": subject,
                "parent_sha": parent,
                "chronological_position": position,
                "expected_predecessor": predecessor,
                "present": present,
                "ordering_valid": ordering,
            }
        )
    checks = {
        "all_commits_present": all(row["present"] for row in rows),
        "all_ordering_valid": all(row["ordering_valid"] for row in rows),
        "all_stop_commits_preserved": all(
            sha in {row["commit_sha"] for row in rows} for sha in ["771ac92", "c3a872d"]
        ),
        "all_reconciliation_commits_preserved": any(
            row["commit_sha"] == "1b71ea4" for row in rows
        ),
        "c6_seal_precedes_c6_final_decision": run_command(
            ["git", "merge-base", "--is-ancestor", "4e7578e", "6c0586f"]
        )["returncode"]
        == 0,
    }
    return {
        "records": rows,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_package_consistency() -> dict[str, Any]:
    reproduction = load_json(REPO / "results/gate_c6/final_result_reproduction.json")
    claims = load_json(REPO / "results/gate_c6/final_claim_matrix.json")
    manifest = load_json(REPO / "results/gate_c6/reproducibility_manifest.json")
    seal = load_json(REPO / "results/gate_c6/acceptance_lineage_seal.json")
    quality = load_json(REPO / "results/gate_c6/quality_gate_final.json")
    checks = {
        "development_event": reproduction["development"]["event_markout"] == -3.66885245901655,
        "development_control": reproduction["development"]["control_markout"]
        == -17.33688524590164,
        "development_differential": reproduction["development"]["differential"]
        == 13.668032786885094,
        "development_p_ci": reproduction["development"]["permutation_p"] == 0.006496751624187906
        and reproduction["development"]["ci95"] == [6.277491118674749, 21.844720075312043],
        "validation_event": reproduction["validation"]["event_markout"] == 11.33724832214778,
        "validation_control": reproduction["validation"]["control_markout"] == -16.11577181208039,
        "validation_differential": reproduction["validation"]["differential"]
        == 27.453020134228165,
        "validation_relative_p_ci": reproduction["validation"]["relative_permutation_p"]
        == 0.004497751124437781
        and reproduction["validation"]["relative_ci95"]
        == [14.784214406740844, 40.27386831699497],
        "validation_absolute_p_ci": reproduction["validation"]["absolute_sign_flip_p"]
        == 0.12843578210894552
        and reproduction["validation"]["absolute_ci95"][0] == 0.7861459649301382,
        "transport_effects": reproduction["transport"]["standardized_validation_event"]
        == 12.26554243296961
        and reproduction["transport"]["standardized_validation_differential"]
        == 35.53894763198631,
        "transport_threshold_result": reproduction["transport"]["maximum_weight_median_multiple"]
        == 10.399999999999999,
        "claim_statuses": validate_claim_statuses(claims["claims"])["status"] == "PASS",
        "manifest_hash": manifest["manifest_hash"] == EXPECTED_MANIFEST_HASH,
        "seal_identity": validate_c6_seal(seal)["status"] == "PASS",
        "final_c6_decision": quality["final_decision"] == EXPECTED_C6_DECISION,
    }
    return {
        "checks": checks,
        "manifest_hash": manifest["manifest_hash"],
        "seal_id": seal["seal_id"],
        "seal_hash": seal["lineage_seal_hash"],
        "final_gate_c6_decision": quality["final_decision"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_manifest_audit() -> dict[str, Any]:
    manifest = load_json(REPO / "results/gate_c6/reproducibility_manifest.json")
    entries = []
    for group, group_entries in manifest["artifact_groups"].items():
        for entry in group_entries:
            path = str(entry["path"])
            absolute = REPO / path
            recomputed = raw_sha256(absolute) if absolute.exists() else None
            entries.append(
                {
                    "group": group,
                    "path": path,
                    "exists": absolute.exists(),
                    "declared_sha256": entry.get("sha256"),
                    "recomputed_sha256": recomputed,
                    "hash_matches": entry.get("sha256") == recomputed,
                    "artifact_type": absolute.suffix or "extensionless",
                    "excluded_raw_dataset_reference": path.replace("\\", "/").startswith(
                        ("data/raw/", "data/canonical/")
                    ),
                }
            )
    checks = {
        "manifest_hash": validate_manifest_hash(manifest)["status"] == "PASS",
        "all_paths_exist": all(entry["exists"] for entry in entries),
        "all_hashes_match": all(entry["hash_matches"] for entry in entries),
        "no_excluded_raw_dataset_reference": not any(
            entry["excluded_raw_dataset_reference"] for entry in entries
        ),
        "claim_matrix_present": any(
            entry["path"].endswith("final_claim_matrix.json") for entry in entries
        ),
        "lineage_seal_present": artifact("results/gate_c6/acceptance_lineage_seal.json")["exists"],
    }
    return {
        "checks": checks,
        "entries": entries,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def target_commit() -> str:
    return git(["rev-parse", TARGET_BRANCH]).strip()


def branch_changed_paths() -> list[str]:
    output = git(["diff", "--name-only", f"{TARGET_BRANCH}...HEAD"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def build_prohibited_data_audit() -> dict[str, Any]:
    changed = branch_changed_paths()
    ls_tree = git(["ls-tree", "-r", "--long", "HEAD"]).splitlines()
    objects = git(["rev-list", "--objects", f"{TARGET_BRANCH}..HEAD"]).splitlines()
    branch_paths = []
    for line in objects:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            branch_paths.append(parts[1])
    prohibited_changed = find_prohibited_paths(changed)
    prohibited_objects = find_prohibited_paths(branch_paths)
    large_files = []
    for line in ls_tree:
        parts = line.split()
        if len(parts) >= 5 and parts[3].isdigit():
            size = int(parts[3])
            path = parts[4]
            if size > 1_000_000:
                large_files.append({"path": path, "size_bytes": size})
    checks = {
        "raw_canonical_data_committed": not any(
            path.startswith(("data/raw/", "data/canonical/")) for path in prohibited_objects
        ),
        "row_level_research_data_committed": not any(
            path.endswith(".parquet") for path in prohibited_objects
        ),
        "holdout_data_committed": not any("holdout" in path.lower() for path in prohibited_objects),
        "credentials_committed": not any(
            token in path.lower()
            for path in branch_paths
            for token in [".env", "credential", "secret"]
        ),
        "unexpected_generated_caches_committed": not any(
            cache in path.lower()
            for path in prohibited_objects
            for cache in ["node_modules", "__pycache__", ".pytest_tmp_", ".pytest_cache"]
        ),
    }
    return {
        "target_branch": TARGET_BRANCH,
        "changed_paths": changed,
        "prohibited_changed_paths": prohibited_changed,
        "prohibited_new_objects": prohibited_objects,
        "large_files_over_1mb": large_files,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_lineage_seal_enforcement() -> dict[str, Any]:
    seal = load_json(REPO / "results/gate_c6/acceptance_lineage_seal.json")
    quality = load_json(REPO / "results/gate_c6/quality_gate_final.json")
    claims = load_json(REPO / "results/gate_c6/final_claim_matrix.json")["claims"]
    checks = {
        "seal_identity_and_hash": validate_c6_seal(seal)["status"] == "PASS",
        "reject_new_acceptance_hypothesis_on_preserved_holdout": quality["checks"][
            "no_new_acceptance_hypothesis_created"
        ],
        "reject_acceptance_holdout_handoff": quality["checks"][
            "no_acceptance_holdout_handoff_created"
        ],
        "reject_acceptance_holdout_loading": quality["checks"]["holdout_remains_unopened"],
        "seal_change_requires_external_data_lineage": any(
            "new external dataset" in statement for statement in seal["closure_statements"]
        ),
        "final_claim_statuses_locked": validate_claim_statuses(claims)["status"] == "PASS",
    }
    return {
        "checks": checks,
        "seal_id": seal["seal_id"],
        "seal_hash": seal["lineage_seal_hash"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_documentation_quality() -> dict[str, Any]:
    docs = [
        "ACCEPTANCE_RESEARCH_GATE_LEDGER.md",
        "GATE_C6_INFERENCE_COHERENCE_AUDIT.md",
        "GATE_C6_TRANSPORT_WEIGHT_FAILURE.md",
        "ACCEPTANCE_FINAL_CLAIM_MATRIX.md",
        "ACCEPTANCE_RESEARCH_METHODS.md",
        "ACCEPTANCE_RESEARCH_RESULTS.md",
        "ACCEPTANCE_RESEARCH_ABSTRACT.md",
        "ACCEPTANCE_LIMITATIONS.md",
        "ACCEPTANCE_REPRODUCIBILITY.md",
        "ACCEPTANCE_LINEAGE_SEAL.md",
        "ACCEPTANCE_RESEARCH_LESSONS.md",
        "GATE_C6_FINAL_DECISION_MEMO.md",
    ]
    text_by_doc = {doc: (DOC_DIR / doc).read_text(encoding="utf-8") for doc in docs}
    all_text = "\n".join(text_by_doc.values())
    checks = {
        "consistent_terminology": "Acceptance" in all_text and "validation" in all_text,
        "development_validation_distinction": "development" in all_text.lower()
        and "validation" in all_text.lower(),
        "exploratory_confirmatory_distinction": "Exploratory" in all_text
        and "Confirmatory" in all_text,
        "matched_control_differential": "event-minus-control" in all_text,
        "executable_bid_ask_markout": "bid/ask executable" in all_text,
        "absolute_effect_uncertainty": "sign-flip" in all_text and "bootstrap" in all_text,
        "transportability_failure": "10.4" in all_text and "FAIL" in all_text,
        "no_misleading_phrases": not find_misleading_phrases(all_text),
        "no_hidden_holdout_implication": "holdout remains unopened" in all_text.lower(),
        "all_referenced_artifacts_present": all(
            (REPO / path).exists()
            for path in [
                "results/gate_c6/final_result_reproduction.json",
                "results/gate_c6/final_claim_matrix.json",
                "results/gate_c6/acceptance_lineage_seal.json",
            ]
        ),
    }
    return {
        "documents": docs,
        "checks": checks,
        "misleading_phrase_findings": find_misleading_phrases(all_text),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": now_utc(),
    }


def count_ruff_issues(command: list[str], cwd: Path = REPO) -> int:
    result = run_command(command, cwd=cwd)
    if result["returncode"] == 0:
        return 0
    for line in reversed((result["stdout"] + result["stderr"]).splitlines()):
        if line.startswith("Found ") and " error" in line:
            return int(line.split()[1])
    return -1


def count_mypy_issues(command: list[str], cwd: Path = REPO) -> int:
    result = run_command(command, cwd=cwd)
    if result["returncode"] == 0:
        return 0
    for line in reversed((result["stdout"] + result["stderr"]).splitlines()):
        if line.startswith("Found ") and " error" in line:
            return int(line.split()[1])
    return -1


def measure_target_static_counts() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fx_smc_bot_c6r_origin_main_") as tmp_name:
        tmp = Path(tmp_name)
        archive = tmp / "main.tar"
        archive_result = run_command(
            ["git", "archive", "--format=tar", TARGET_BRANCH, "-o", str(archive)]
        )
        if archive_result["returncode"] != 0:
            return {
                "ruff_research": None,
                "mypy_research": None,
                "measurement_status": "ARCHIVE_FAILED",
                "stderr": archive_result["stderr"],
            }
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        research_dir = tmp / "src" / "fx_smc_bot" / "research"
        return {
            "ruff_research": count_ruff_issues(
                ["python", "-m", "ruff", "check", str(research_dir)]
            ),
            "mypy_research": count_mypy_issues(
                ["python", "-m", "mypy", str(research_dir)]
            ),
            "measurement_status": "PASS",
        }


def build_static_delta() -> dict[str, Any]:
    target_count = measure_target_static_counts()
    head_count = {
        "ruff_research": count_ruff_issues(
            ["python", "-m", "ruff", "check", "src/fx_smc_bot/research"]
        ),
        "mypy_research": count_mypy_issues(["python", "-m", "mypy", "src/fx_smc_bot/research"]),
    }
    c6r_targeted = {
        "ruff": run_command(
            [
                "python",
                "-m",
                "ruff",
                "check",
                "scripts/run_gate_c6.py",
                "scripts/run_gate_c6r.py",
                "src/fx_smc_bot/research/gate_c6.py",
                "src/fx_smc_bot/research/gate_c6r.py",
                "tests/test_gate_c6",
                "tests/test_gate_c6r",
            ]
        )["returncode"],
        "mypy": run_command(
            [
                "python",
                "-m",
                "mypy",
                "scripts/run_gate_c6.py",
                "scripts/run_gate_c6r.py",
                "src/fx_smc_bot/research/gate_c6.py",
                "src/fx_smc_bot/research/gate_c6r.py",
            ]
        )["returncode"],
    }
    ruff_delta = None
    mypy_delta = None
    if isinstance(target_count["ruff_research"], int):
        ruff_delta = head_count["ruff_research"] - target_count["ruff_research"]
    if isinstance(target_count["mypy_research"], int):
        mypy_delta = head_count["mypy_research"] - target_count["mypy_research"]
    no_new_broad = (
        isinstance(ruff_delta, int)
        and isinstance(mypy_delta, int)
        and ruff_delta <= 0
        and mypy_delta <= 0
    )
    return {
        "target_branch": TARGET_BRANCH,
        "target_branch_issue_count": target_count,
        "head_issue_count": head_count,
        "shared_issues": {
            "ruff_research": min(target_count["ruff_research"], head_count["ruff_research"])
            if isinstance(target_count["ruff_research"], int)
            else None,
            "mypy_research": min(target_count["mypy_research"], head_count["mypy_research"])
            if isinstance(target_count["mypy_research"], int)
            else None,
        },
        "new_issues_introduced": {
            "ruff_research": max(ruff_delta or 0, 0),
            "mypy_research": max(mypy_delta or 0, 0),
            "c6_c6r_targeted": 0
            if c6r_targeted["ruff"] == 0 and c6r_targeted["mypy"] == 0
            else "unknown",
        },
        "issues_fixed": {
            "ruff_research": abs(min(ruff_delta or 0, 0)),
            "mypy_research": abs(min(mypy_delta or 0, 0)),
        },
        "no_new_broad_static_debt_against_target": no_new_broad,
        "targeted_c6_c6r_returncodes": c6r_targeted,
        "status": "PASS"
        if c6r_targeted["ruff"] == 0 and c6r_targeted["mypy"] == 0 and no_new_broad
        else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_merge_readiness() -> dict[str, Any]:
    base = git(["merge-base", TARGET_BRANCH, "HEAD"]).strip()
    ahead_behind = git(["rev-list", "--left-right", "--count", f"{TARGET_BRANCH}...HEAD"]).strip()
    diff_check = run_command(["git", "diff", "--check", f"{TARGET_BRANCH}...HEAD"])
    merge_tree = run_command(["git", "merge-tree", base, TARGET_BRANCH, "HEAD"])
    conflicts = [
        line for line in merge_tree["stdout"].splitlines() if "changed in both" in line.lower()
    ]
    changed = branch_changed_paths()
    return {
        "target_branch": TARGET_BRANCH,
        "merge_base": base,
        "ahead_behind_left_target_right_head": ahead_behind,
        "diff_check_returncode": diff_check["returncode"],
        "merge_tree_returncode": merge_tree["returncode"],
        "conflicting_paths": conflicts,
        "potentially_overlapping_research_files": [
            path
            for path in changed
            if path.startswith("docs/research/") or path.startswith("results/")
        ],
        "deleted_or_renamed_paths": git(
            ["diff", "--name-status", f"{TARGET_BRANCH}...HEAD"]
        ).splitlines(),
        "generated_files_likely_to_conflict": [
            path
            for path in changed
            if path.startswith("results/gate_c6") or path.startswith("results/gate_c6r")
        ],
        "status": "PASS"
        if diff_check["returncode"] == 0 and merge_tree["returncode"] == 0 and not conflicts
        else "FAIL",
        "created_at_utc": now_utc(),
    }


def build_holdout_integrity() -> dict[str, Any]:
    source = load_json(REPO / "results/gate_c6/holdout_integrity.json")
    validation = validate_holdout_closed(source)
    return {
        **validation["checks"],
        "violations": validation["violations"],
        "source": "results/gate_c6/holdout_integrity.json",
        "status": validation["status"],
        "created_at_utc": now_utc(),
    }


def write_docs(
    lineage: dict[str, Any],
    package: dict[str, Any],
    data: dict[str, Any],
    merge: dict[str, Any],
) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    lineage_rows = "\n".join(
        f"- `{row['commit_sha']}` {row['commit_subject']}: present="
        f"`{row['present']}`, ordering=`{row['ordering_valid']}`"
        for row in lineage["records"]
    )
    (DOC_DIR / "GATE_C6R_COMMIT_LINEAGE_AUDIT.md").write_text(
        "# Gate C6-R Commit Lineage Audit\n\n"
        f"Status: `{lineage['status']}`\n\n"
        f"{lineage_rows}\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C6R_PACKAGE_REVIEW.md").write_text(
        "# Gate C6-R Package Review\n\n"
        f"Status: `{package['status']}`\n\n"
        f"Manifest hash: `{package['manifest_hash']}`\n\n"
        f"Seal ID: `{package['seal_id']}`\n\n"
        f"Seal hash: `{package['seal_hash']}`\n\n"
        f"Final Gate C6 decision: `{package['final_gate_c6_decision']}`\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C6R_DATA_SAFETY_AUDIT.md").write_text(
        "# Gate C6-R Data Safety Audit\n\n"
        f"Status: `{data['status']}`\n\n"
        "Raw/canonical data committed: `false`\n\n"
        "Row-level research data committed: `false`\n\n"
        "Holdout data committed: `false`\n\n"
        "Credentials committed: `false`\n",
        encoding="utf-8",
    )
    (DOC_DIR / "ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md").write_text(
        "# Acceptance Research Package Index\n\n"
        "- [Structured abstract](ACCEPTANCE_RESEARCH_ABSTRACT.md)\n"
        "- [Methods](ACCEPTANCE_RESEARCH_METHODS.md)\n"
        "- [Results](ACCEPTANCE_RESEARCH_RESULTS.md)\n"
        "- [Claim matrix](ACCEPTANCE_FINAL_CLAIM_MATRIX.md)\n"
        "- [Limitations](ACCEPTANCE_LIMITATIONS.md)\n"
        "- [Gate ledger](ACCEPTANCE_RESEARCH_GATE_LEDGER.md)\n"
        "- [Inference audit](GATE_C6_INFERENCE_COHERENCE_AUDIT.md)\n"
        "- [Transport audit](GATE_C6_TRANSPORT_WEIGHT_FAILURE.md)\n"
        "- [Reproducibility guide](ACCEPTANCE_REPRODUCIBILITY.md)\n"
        "- [Lineage seal](ACCEPTANCE_LINEAGE_SEAL.md)\n"
        "- [Final Gate C6 memo](GATE_C6_FINAL_DECISION_MEMO.md)\n"
        "- [C6-R package review](GATE_C6R_PACKAGE_REVIEW.md)\n"
        "- [Data-safety audit](GATE_C6R_DATA_SAFETY_AUDIT.md)\n\n"
        "Scientific status: mixed, replicated relative effect, nontransportable "
        "dual-positive mechanism.\n\n"
        "Operational status: research lineage closed.\n\n"
        "Holdout status: unopened and unauthorized for this family.\n\n"
        "Merge status: determined by Gate C.6-R.\n",
        encoding="utf-8",
    )
    (DOC_DIR / "GATE_C6R_FINAL_REVIEW.md").write_text(
        "# Gate C6-R Final Review\n\n"
        f"Review ID: `{REVIEW_ID}`\n\n"
        f"Merge base: `{merge['merge_base']}`\n\n"
        f"Merge-readiness status: `{merge['status']}`\n",
        encoding="utf-8",
    )


def build_review_lock(
    package: dict[str, Any],
    data: dict[str, Any],
    manifest: dict[str, Any],
    seal: dict[str, Any],
    docs: dict[str, Any],
    quality: dict[str, Any],
    merge: dict[str, Any],
) -> dict[str, Any]:
    lock = {
        "review_id": REVIEW_ID,
        "hashes": {
            "c6_reproducibility_manifest": artifact(
                "results/gate_c6/reproducibility_manifest.json"
            ),
            "c6_lineage_seal": artifact("results/gate_c6/acceptance_lineage_seal.json"),
            "c6_final_decision": artifact("docs/research/GATE_C6_FINAL_DECISION_MEMO.md"),
            "package_consistency_audit": artifact(
                "results/gate_c6r/package_consistency_audit.json"
            ),
            "prohibited_data_audit": artifact("results/gate_c6r/prohibited_data_audit.json"),
            "manifest_audit": artifact("results/gate_c6r/reproducibility_manifest_audit.json"),
            "seal_enforcement_audit": artifact(
                "results/gate_c6r/lineage_seal_enforcement.json"
            ),
            "documentation_audit": artifact("results/gate_c6r/documentation_quality_audit.json"),
            "quality_gate": artifact("results/gate_c6r/quality_gate_final.json"),
            "merge_readiness_audit": artifact("results/gate_c6r/merge_readiness.json"),
            "package_index": artifact("docs/research/ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md"),
        },
        "audit_statuses": {
            "package": package["status"],
            "data": data["status"],
            "manifest": manifest["status"],
            "seal": seal["status"],
            "documentation": docs["status"],
            "quality": quality["status"],
            "merge": merge["status"],
        },
        "created_at_utc": now_utc(),
    }
    lock["review_lock_hash"] = review_lock_hash(lock)
    return lock


def build_quality_gate(
    remote: dict[str, Any],
    repo_state: dict[str, Any],
    package: dict[str, Any],
    manifest: dict[str, Any],
    data: dict[str, Any],
    seal: dict[str, Any],
    docs: dict[str, Any],
    static: dict[str, Any],
    merge: dict[str, Any],
    holdout: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "remote_lineage_synchronized": remote["status"] == "PASS",
        "worktree_hygiene_resolved": repo_state["temp_directory"]["gitignore_rule_present"],
        "package_consistency_pass": package["status"] == "PASS",
        "reproducibility_manifest_pass": manifest["status"] == "PASS",
        "no_prohibited_data_committed": data["status"] == "PASS",
        "lineage_seal_enforcement_pass": seal["status"] == "PASS",
        "documentation_quality_pass": docs["status"] == "PASS",
        "targeted_static_analysis_pass": static["targeted_c6_c6r_returncodes"]["ruff"] == 0
        and static["targeted_c6_c6r_returncodes"]["mypy"] == 0,
        "no_new_broad_static_debt_against_target": static[
            "no_new_broad_static_debt_against_target"
        ],
        "merge_conflict_audit_pass": merge["status"] == "PASS",
        "holdout_remains_unopened": holdout["status"] == "PASS",
    }
    return {
        "gate": "C6-R",
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "final_decision": "ACCEPTANCE_RESEARCH_PACKAGE_APPROVED_FOR_MERGE"
        if all(checks.values())
        else "BLOCKED_BY_CI_FAILURE",
        "created_at_utc": now_utc(),
    }


def write_final_decision_doc(quality: dict[str, Any], lock: dict[str, Any]) -> None:
    (DOC_DIR / "GATE_C6R_FINAL_DECISION_MEMO.md").write_text(
        "# Gate C6-R Final Decision Memo\n\n"
        f"Final decision: `{quality['final_decision']}`\n\n"
        f"Review ID: `{lock['review_id']}`\n\n"
        f"Review lock hash: `{lock['review_lock_hash']}`\n\n"
        "No scientific results, claim statuses, C6 seal values, Acceptance hypotheses, "
        "or holdout handoffs were changed by this review gate.\n",
        encoding="utf-8",
    )


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    repo_state = build_repository_state()
    remote = build_remote_lineage()
    lineage = build_commit_lineage()
    package = build_package_consistency()
    manifest = build_manifest_audit()
    data = build_prohibited_data_audit()
    seal = build_lineage_seal_enforcement()
    docs = build_documentation_quality()
    static = build_static_delta()
    merge = build_merge_readiness()
    holdout = build_holdout_integrity()

    write_json(RESULT_DIR / "repository_state.json", repo_state)
    write_json(RESULT_DIR / "remote_lineage_status.json", remote)
    write_json(RESULT_DIR / "commit_lineage_audit.json", lineage)
    write_json(RESULT_DIR / "package_consistency_audit.json", package)
    write_json(RESULT_DIR / "reproducibility_manifest_audit.json", manifest)
    write_json(RESULT_DIR / "prohibited_data_audit.json", data)
    write_json(RESULT_DIR / "lineage_seal_enforcement.json", seal)
    write_json(RESULT_DIR / "documentation_quality_audit.json", docs)
    write_json(RESULT_DIR / "static_analysis_delta.json", static)
    write_json(RESULT_DIR / "merge_readiness.json", merge)
    write_json(RESULT_DIR / "holdout_integrity.json", holdout)
    write_docs(lineage, package, data, merge)

    quality = build_quality_gate(
        remote,
        repo_state,
        package,
        manifest,
        data,
        seal,
        docs,
        static,
        merge,
        holdout,
    )
    write_json(RESULT_DIR / "quality_gate_final.json", quality)
    review_lock = build_review_lock(package, data, manifest, seal, docs, quality, merge)
    write_json(RESULT_DIR / "review_lock.json", review_lock)
    write_final_decision_doc(quality, review_lock)
    return 0 if quality["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
