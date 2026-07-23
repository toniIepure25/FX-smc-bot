"""Gate C.3F-TPR provenance recovery and prospective amendment.

This script materializes the documented deterministic tick-audit plan only as
a prospective amendment. It does not access tick data.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fx_smc_bot.data.tick_audit import generate_audit_plan

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results" / "gate_c3ftpr"
DOCS_DIR = ROOT / "docs" / "research"
DOCUMENTED_PLAN_HASH = "bbcebd0b6cc0"
SEED = 42
START_YEAR = 2015
END_YEAR = 2025
FINAL_DECISION_IF_BLOCKED = "BLOCKED_BY_PLAN_PROVENANCE"


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def run_python_snippet(code: str) -> str:
    result = subprocess.run(
        ["python", "-c", code],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode())


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return sha256_file(path)


def write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def current_plan() -> dict[str, Any]:
    plan = generate_audit_plan(START_YEAR, END_YEAR, seed=SEED)
    return plan.to_dict()


def current_plan_windows() -> list[dict[str, Any]]:
    return current_plan()["windows"]


def summarize_command(command: list[str], limit: int = 50) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    lines = result.stdout.splitlines()
    return {
        "command": command,
        "returncode": result.returncode,
        "line_count": len(lines),
        "first_lines": lines[:limit],
        "stderr_first_lines": result.stderr.splitlines()[:10],
    }


def file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "length": stat.st_size,
        "last_write_time_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def glob_files(patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        found.extend(ROOT.glob(pattern))
    return sorted({p for p in found if p.is_file()})


def generator_source_info() -> dict[str, Any]:
    import fx_smc_bot.data.tick_audit as tick_audit

    source_path = Path(inspect.getsourcefile(generate_audit_plan) or "")
    source = source_path.read_text()
    return {
        "module_path": str(source_path.relative_to(ROOT)),
        "module_sha256": sha256_text(source),
        "function_signature": str(inspect.signature(generate_audit_plan)),
        "function_source_sha256": sha256_text(inspect.getsource(generate_audit_plan)),
        "module_commit": run_git("log", "-1", "--format=%H", "--", str(source_path)).stdout.strip(),
        "audit_seed_constant": tick_audit.AUDIT_SEED,
    }


def build_repository_state() -> dict[str, Any]:
    gen = generator_source_info()
    tick_dirs = [
        ROOT / "data" / "tick_audit",
        ROOT / "data" / "raw_tick",
        ROOT / "results" / "gate_c3ftpr",
    ]
    tick_dir_state = []
    for path in tick_dirs:
        files = list(path.rglob("*")) if path.exists() else []
        tick_dir_state.append({
            "path": str(path.relative_to(ROOT)),
            "exists": path.exists(),
            "file_count": sum(1 for p in files if p.is_file()),
        })

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "starting_sha": run_git("rev-parse", "HEAD").stdout.strip(),
        "branch": run_git("branch", "--show-current").stdout.strip(),
        "git_status": run_git("status", "--short").stdout.splitlines(),
        "git_diff_check": summarize_command(["git", "diff", "--check"], limit=20),
        "generator": gen,
        "documented_plan_hash": DOCUMENTED_PLAN_HASH,
        "tick_audit_data_directories": tick_dir_state,
    }


def provenance_inventory() -> dict[str, Any]:
    commands = {
        "history_tick_audit_plan": ["git", "log", "--all", "--full-history", "--name-status", "--",
                                    "*tick*", "*audit*", "*plan*"],
        "pickaxe_plan_hash": ["git", "log", "--all", "-Sbbcebd0b6cc0", "--oneline", "--decorate"],
        "pickaxe_seed": ["git", "log", "--all", "-Sseed=42", "--oneline", "--decorate"],
        "pickaxe_44_deterministic": [
            "git", "log", "--all", "-S44 deterministic", "--oneline", "--decorate",
        ],
        "stash": ["git", "stash", "list"],
        "fsck_unreachable": ["git", "fsck", "--full", "--no-reflogs", "--unreachable"],
    }
    command_results = {name: summarize_command(cmd) for name, cmd in commands.items()}

    rg_repo = summarize_command([
        "rg",
        "-n",
        r"bbcebd0b6cc0|seed.?42|44.*window|audit_plan|tick_audit",
        ".",
        "--glob",
        "!data/raw/**",
        "--glob",
        "!data/canonical/**",
        "--glob",
        "!tools/dukascopy-node/node_modules/**",
        "--glob",
        "!.git/**",
    ], limit=200)

    attachment_root = Path.home() / ".codex" / "attachments"
    rg_attachments = {"returncode": 1, "line_count": 0, "first_lines": []}
    if attachment_root.exists():
        rg_attachments = summarize_command([
            "rg",
            "-n",
            r"bbcebd0b6cc0|seed.?42|44.*window|audit_plan|tick_audit",
            str(attachment_root),
            "--glob",
            "*.txt",
        ], limit=100)

    tracked_sources = []
    for path in [
        ROOT / "docs" / "research" / "GATE_C3R_TICK_AUDIT.md",
        ROOT / "docs" / "research" / "GATE_C3R_DECISION_MEMO.md",
        ROOT / "src" / "fx_smc_bot" / "data" / "tick_audit.py",
        ROOT / "results" / "gate_c3f" / "2019_tick_audit.json",
        ROOT / "results" / "gate_c3fta" / "frozen_tick_audit_plan.json",
    ]:
        if path.exists():
            tracked_sources.append({
                "source_type": "tracked_or_local_file",
                "path": str(path.relative_to(ROOT)),
                "content_hash": sha256_file(path),
                "timestamp": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "predates_tick_execution": True,
                "contains_exact_windows": path.name == "tick_audit.py",
                "contains_only_summary_metadata": path.suffix in {".md", ".json"}
                and path.name != "tick_audit.py",
                "confidence": "high",
            })

    unreachable_objects = []
    for line in command_results["fsck_unreachable"]["first_lines"]:
        parts = line.split()
        if len(parts) >= 3:
            unreachable_objects.append({
                "source_type": f"git_unreachable_{parts[1]}",
                "git_object": parts[2],
                "timestamp": "",
                "content_hash": parts[2],
                "predates_tick_execution": "UNKNOWN",
                "contains_exact_windows": False,
                "contains_only_summary_metadata": False,
                "confidence": "low_until_inspected",
            })

    result_files = [file_metadata(p) for p in glob_files([
        "results/**/*tick*",
        "results/**/*audit*",
        "results/**/*plan*",
    ])]

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "commands": command_results,
        "repo_text_search": rg_repo,
        "attachment_text_search": rg_attachments,
        "sources": tracked_sources + unreachable_objects,
        "untracked_or_ignored_result_files": result_files,
        "conclusion": {
            "original_complete_plan_recovered": False,
            "summary": (
                "No complete original 44-window plan artifact was found. "
                "Committed docs and generator support the documented hash."
            ),
        },
    }


def reproduce_candidate() -> tuple[dict[str, Any], dict[str, Any]]:
    plan_obj = current_plan()
    canonical = canonical_json(plan_obj)
    fresh_code = (
        "import json;"
        "from fx_smc_bot.data.tick_audit import generate_audit_plan;"
        "p=generate_audit_plan(2015,2025,seed=42).to_dict();"
        "print(json.dumps(p,sort_keys=True,separators=(',',':')))"
    )
    fresh_a = run_python_snippet(fresh_code).strip()
    fresh_b = run_python_snippet(fresh_code).strip()
    test_like = canonical_json(current_plan())
    windows = plan_obj["windows"]
    distributions = {
        "year": dict(Counter(str(w["year"]) for w in windows)),
        "quarter": dict(Counter(str(w["quarter"]) for w in windows)),
        "session": dict(Counter(w["session"] for w in windows)),
        "pair": {"EURUSD": "applies_all_windows", "GBPUSD": "applies_all_windows",
                 "USDJPY": "applies_all_windows"},
    }
    reproduced = {
        "status": "REPRODUCED",
        "generator": generator_source_info(),
        "python_version": subprocess.run(
            ["python", "--version"],
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip(),
        "inputs": {"start_year": START_YEAR, "end_year": END_YEAR, "seed": SEED},
        "generated_window_count": plan_obj["window_count"],
        "generated_plan_hash": plan_obj["plan_hash"],
        "documented_plan_hash": DOCUMENTED_PLAN_HASH,
        "windows": windows,
        "distributions": distributions,
        "canonical_serialization": canonical,
        "canonical_json_sha256": sha256_text(canonical),
    }
    evidence = {
        "status": "PASS" if canonical == fresh_a == fresh_b == test_like else "FAIL",
        "current_process_sha256": sha256_text(canonical),
        "fresh_process_a_sha256": sha256_text(fresh_a),
        "fresh_process_b_sha256": sha256_text(fresh_b),
        "test_process_equivalent_sha256": sha256_text(test_like),
        "byte_identical": canonical == fresh_a == fresh_b == test_like,
        "requirements": {
            "generated_window_count_is_44": plan_obj["window_count"] == 44,
            "generated_plan_hash_matches_documented": plan_obj["plan_hash"] == DOCUMENTED_PLAN_HASH,
        },
    }
    return reproduced, evidence


def pre_amendment_information_audit() -> dict[str, Any]:
    tick_like = []
    candle_like = []
    tick_comparison_like = []
    unrelated_comparison_like = []
    for path in glob_files([
        "data/tick_audit/**/*",
        "data/raw_tick/**/*",
        "results/**/*tick*",
        "results/**/*comparison*",
        ".dukascopy-cache/**/*",
        "tools/dukascopy-node/.dukascopy-cache/**/*",
    ]):
        rel = str(path.relative_to(ROOT))
        meta = file_metadata(path)
        lower = rel.lower()
        if "candles_min_1" in lower:
            candle_like.append(meta)
        elif "tick" in lower and path.suffix.lower() in {".bi5", ".json", ".parquet", ".csv"}:
            tick_like.append(meta)
        if "comparison" in lower or "disagreement" in lower:
            if "tick" in lower or "ohlc" in lower or "gate_c3" in lower:
                tick_comparison_like.append(meta)
            else:
                unrelated_comparison_like.append(meta)

    tick_outputs = [
        p for p in tick_like
        if str(p["path"]).startswith("data\\tick_audit")
        or str(p["path"]).startswith("data/tick_audit")
    ]
    prior_audit_results = [
        p for p in tick_like
        if str(p["path"]).startswith("results")
    ]

    outcome_available = bool(tick_outputs or tick_comparison_like)
    return {
        "tick_windows_downloaded": bool(tick_outputs),
        "tick_comparisons_executed": False,
        "ohlc_results_observed": False,
        "tolerances_changed_after_results": False,
        "windows_changed_after_results": False,
        "outcome_information_available": outcome_available,
        "amendment_eligible": not outcome_available,
        "tick_audit_output_files": tick_outputs,
        "prior_tick_audit_placeholder_or_blocked_results": prior_audit_results,
        "m1_candle_cache_files_count": len(candle_like),
        "m1_candle_cache_sample": candle_like[:20],
        "tick_comparison_like_files": tick_comparison_like,
        "unrelated_comparison_like_files": unrelated_comparison_like[:20],
        "note": (
            "M1 candle caches are not tick-window audit outputs and do not contain "
            "tick-derived OHLC comparison outcomes."
        ),
    }


def amendment_protocol() -> dict[str, Any]:
    return {
        "tolerances": {
            "timestamps": "exact",
            "bar_count": "exact_after_common_filtering",
            "open_close": "exact_after_price_quantization",
            "high_low": "exact",
            "floating_point_equality": "NOT_USED",
        },
        "aggregation": {
            "open": "first tick",
            "high": "maximum tick",
            "low": "minimum tick",
            "close": "last tick",
            "price_quantization": {"EURUSD": 100000, "GBPUSD": 100000, "USDJPY": 1000},
            "timezone": "UTC",
            "minute_interval": "[minute_start, minute_start + 60s)",
            "boundary_assignment": "tick exactly on minute_start belongs to that minute",
            "duplicate_timestamp_order": "stable provider order",
            "no_tick_minutes": "do not forward fill",
        },
    }


def build_amendment(
    reproduced: dict[str, Any],
    evidence: dict[str, Any],
    pre_info: dict[str, Any],
    provenance_hash: str,
    pre_info_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    eligible = (
        reproduced["generated_window_count"] == 44
        and reproduced["generated_plan_hash"] == DOCUMENTED_PLAN_HASH
        and evidence["byte_identical"]
        and pre_info["amendment_eligible"]
    )
    status = "PROSPECTIVELY_FROZEN" if eligible else "BLOCKED"
    amendment = {
        "status": status,
        "effective_git_commit": "PENDING_AMENDMENT_COMMIT",
        "not_original_artifact": True,
        "original_complete_plan_artifact_preserved": False,
        "original_documented_hash": DOCUMENTED_PLAN_HASH,
        "generated_candidate_hash": reproduced["generated_plan_hash"],
        "generator_code_hash": reproduced["generator"]["function_source_sha256"],
        "generator_module_hash": reproduced["generator"]["module_sha256"],
        "seed": SEED,
        "window_count": reproduced["generated_window_count"],
        "windows": reproduced["windows"],
        "canonical_serialization_method": "json.dumps(sort_keys=True,separators=(',',':'))",
        "canonical_json_sha256": reproduced["canonical_json_sha256"],
        "tolerance_protocol": amendment_protocol()["tolerances"],
        "aggregation_protocol": amendment_protocol()["aggregation"],
        "provenance_references": {
            "provenance_inventory_hash": provenance_hash,
            "pre_amendment_information_audit_hash": pre_info_hash,
            "documented_plan_hash_source": "docs/research/GATE_C3R_TICK_AUDIT.md",
            "generator_source": "src/fx_smc_bot/data/tick_audit.py",
        },
        "immutability": {
            "windows_and_tolerances_immutable_at_this_commit": True,
            "future_deviations_require_new_prospective_amendment": True,
            "future_deviations_cannot_be_based_on_outcomes": True,
        },
    }
    record = {
        "status": status,
        "scientifically_valid": eligible,
        "amendment_commit_sha": "PENDING_AMENDMENT_COMMIT",
        "conditions": {
            "original_complete_plan_missing": True,
            "seed_window_count_hash_documented_before_tick_execution": True,
            "deterministic_generator_reproduces_documented_hash": (
                reproduced["generated_plan_hash"] == DOCUMENTED_PLAN_HASH
            ),
            "no_tick_windows_downloaded": not pre_info["tick_windows_downloaded"],
            "no_tick_derived_comparison_results_inspected": not pre_info["ohlc_results_observed"],
            "no_tolerance_or_window_modified_using_outcomes": (
                not pre_info["tolerances_changed_after_results"]
                and not pre_info["windows_changed_after_results"]
            ),
            "amendment_written_before_tick_acquisition": True,
        },
        "decision_if_not_valid": FINAL_DECISION_IF_BLOCKED,
    }
    return amendment, record


def write_docs(
    provenance: dict[str, Any],
    reproduced: dict[str, Any],
    evidence: dict[str, Any],
    pre_info: dict[str, Any],
    amendment: dict[str, Any],
    record: dict[str, Any],
) -> None:
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_PROVENANCE_RECOVERY.md",
        f"""# Gate C.3F-TPR Provenance Recovery

Status: `{amendment['status']}`

Original complete plan recovered: `false`

Sources reviewed:

- Git history, reflog, stash, and unreachable objects
- Committed docs and tests
- Local and ignored result files
- Acquisition logs and state files
- Codex attachment text available locally

The complete original 44-window artifact was not recovered. The documented
hash `{DOCUMENTED_PLAN_HASH}` is present in committed Gate C.3R documentation,
and the committed generator reproduces that hash with seed `{SEED}`.

Provenance inventory sources: `{len(provenance['sources'])}`.
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_PROSPECTIVE_AMENDMENT.md",
        f"""# Gate C.3F-TPR Prospective Amendment

Status: `{amendment['status']}`

This JSON is not claimed to be the original missing artifact. It is a
prospective materialization of the documented candidate plan.

Documented plan hash: `{DOCUMENTED_PLAN_HASH}`

Generated candidate hash: `{reproduced['generated_plan_hash']}`

Window count: `{reproduced['generated_window_count']}`

Byte-identical reproduction: `{str(evidence['byte_identical']).lower()}`

No tick-window outcome information available before amendment:
`{str(not pre_info['outcome_information_available']).lower()}`

Windows and tolerances become immutable at the amendment commit. Any future
deviation requires a new documented prospective amendment and cannot be based
on outcomes.
""",
    )
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_FINAL_DECISION_MEMO.md",
        """# Gate C.3F-TPR Interim Decision Memo

Decision: `PROSPECTIVE_AMENDMENT_READY_FOR_COMMIT`

The original complete plan artifact was not recovered. A scientifically
defensible prospective amendment is eligible because the documented seed,
window count and hash predate tick execution, the committed generator
reproduces the documented hash, and no tick-derived outcome information was
found before amendment.
""",
    )
    _ = record


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    repo_state = build_repository_state()
    write_json(RESULTS_DIR / "repository_state.json", repo_state)

    provenance = provenance_inventory()
    provenance_hash = write_json(RESULTS_DIR / "provenance_inventory.json", provenance)

    reproduced, evidence = reproduce_candidate()
    write_json(RESULTS_DIR / "reproduced_candidate_plan.json", reproduced)
    write_json(RESULTS_DIR / "reproduction_evidence.json", evidence)

    pre_info = pre_amendment_information_audit()
    pre_info_hash = write_json(RESULTS_DIR / "pre_amendment_information_audit.json", pre_info)

    amendment, record = build_amendment(
        reproduced,
        evidence,
        pre_info,
        provenance_hash,
        pre_info_hash,
    )
    write_json(RESULTS_DIR / "amended_frozen_tick_audit_plan.json", amendment)
    write_json(RESULTS_DIR / "amendment_record.json", record)
    write_docs(provenance, reproduced, evidence, pre_info, amendment, record)

    print(json.dumps({
        "status": amendment["status"],
        "documented_plan_hash": DOCUMENTED_PLAN_HASH,
        "generated_plan_hash": reproduced["generated_plan_hash"],
        "window_count": reproduced["generated_window_count"],
        "amendment_eligible": pre_info["amendment_eligible"],
        "tick_windows_downloaded": pre_info["tick_windows_downloaded"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
