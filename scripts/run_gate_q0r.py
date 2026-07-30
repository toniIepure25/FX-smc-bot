"""Gate Q.0-R clean-room orchestration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fx_smc_bot.research.quant_polarity_q0r_data import (
    acquire_plan,
    certify_development_plan,
    development_authorizations,
)
from fx_smc_bot.research.quant_safe_io import configured_q0r_root

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "gate_q0r"
PLAN_PATH = RESULTS / "development_acquisition_plan.json"
EXPECTED_PROTOCOL = "Q0R_CLEAN_ROOM_DATA_RECOVERY_PROTOCOL_V1"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _require_frozen_plan() -> dict[str, Any]:
    plan = _read_json(PLAN_PATH)
    if plan.get("protocol_id") != EXPECTED_PROTOCOL:
        raise RuntimeError("Q.0-R acquisition protocol mismatch")
    if plan.get("status") != "FROZEN_BEFORE_PROVIDER_ACCESS":
        raise RuntimeError("Q.0-R acquisition protocol is not frozen")
    if not _git("ls-files", PLAN_PATH.relative_to(ROOT).as_posix()):
        raise RuntimeError("Q.0-R acquisition plan must be committed before provider access")
    return plan


def run_development_acquisition(workers: int) -> None:
    plan = _require_frozen_plan()
    data_root = configured_q0r_root(ROOT)
    authorizations = development_authorizations(data_root, ROOT)
    result = acquire_plan(ROOT, authorizations, workers=workers)
    result.update(
        {
            "program_id": "FX_QUANT_POLARITY_META_V2",
            "protocol_id": plan["protocol_id"],
            "provider_request_latest_permitted_date": "2019-12-31",
            "replication_provider_requests_sent": False,
            "quarantined_interval_provider_requests_sent": False,
        }
    )
    _write_json(RESULTS / "development_acquisition_progress.json", result)
    _write_json(
        RESULTS / "development_provider_failures.json",
        {
            "failed_partitions": result["failed_partitions"],
            "failures": result["failure_summaries"],
            "status": "PASS" if result["failed_partitions"] == 0 else "REPAIR_REQUIRED",
        },
    )
    _write_json(
        RESULTS / "development_repair_results.json",
        {
            "resumable_exact_plan": True,
            "remaining_failed_partitions": result["failed_partitions"],
            "status": "NOT_REQUIRED" if result["failed_partitions"] == 0 else "REPAIR_REQUIRED",
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def run_development_certification(workers: int) -> None:
    progress = _read_json(RESULTS / "development_acquisition_progress.json")
    if progress.get("status") != "COMPLETE_PENDING_CERTIFICATION":
        raise RuntimeError("Development acquisition is not complete")
    data_root = configured_q0r_root(ROOT)
    authorizations = development_authorizations(data_root, ROOT)
    certification, freeze = certify_development_plan(authorizations, workers=workers)
    _write_json(RESULTS / "development_data_certification.json", certification)
    _write_json(RESULTS / "development_dataset_freeze.json", freeze)
    print(json.dumps(certification, indent=2, sort_keys=True))


def _enable_q0r_execution() -> None:
    os.environ["FX_Q0R_EXECUTION"] = "1"


def run_execution_certification() -> None:
    from fx_smc_bot.research.quant_polarity_execution import certify_execution_integrity

    certification = _read_json(RESULTS / "development_data_certification.json")
    if certification.get("status") != "PASS":
        raise RuntimeError("Execution certification requires certified development data")
    _enable_q0r_execution()
    audits = certify_execution_integrity(ROOT)
    for name, payload in audits.items():
        _write_json(RESULTS / f"{name}.json", payload)
    if any(payload.get("status") != "PASS" for payload in audits.values()):
        raise RuntimeError("Q.0-R execution certification failed")
    print(json.dumps({name: payload["status"] for name, payload in audits.items()}))


def run_development_execution(workers: int) -> None:
    from fx_smc_bot.research.quant_polarity_execution import execute_development_program

    certification = _read_json(RESULTS / "development_data_certification.json")
    if certification.get("status") != "PASS":
        raise RuntimeError("Development execution requires certified data")
    _enable_q0r_execution()
    predecessor = _git("rev-parse", "HEAD")
    result = execute_development_program(ROOT, workers=workers)
    result["development_outcome_predecessor_sha"] = predecessor
    result["derived_root_outside_repository"] = True
    result["row_level_ledgers_committed"] = False
    _write_json(RESULTS / "development_execution_manifest.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))


def run_development_evaluation() -> None:
    from fx_smc_bot.research.quant_polarity_development import (
        adjudicate_development,
        run_development_analysis,
    )

    execution = _read_json(RESULTS / "development_execution_manifest.json")
    if execution.get("status") != "PASS":
        raise RuntimeError("Development evaluation requires complete execution")
    _enable_q0r_execution()
    results = run_development_analysis(ROOT, execution)
    adjudication = adjudicate_development(results)
    _write_json(
        RESULTS / "development_candidate_results.json",
        {
            "results": results["candidate_results"],
            "model": results["model"],
            "integrity": results["integrity"],
            "status": "PASS",
        },
    )
    _write_json(
        RESULTS / "development_benchmark_results.json",
        {"results": results["benchmark_results"], "status": "PASS"},
    )
    _write_json(
        RESULTS / "development_factor_alpha.json",
        {
            "results": {
                candidate_id: payload["factor_adjusted_hac"]
                for candidate_id, payload in results["inference"].items()
            },
            "status": "PASS",
        },
    )
    _write_json(
        RESULTS / "development_inference.json",
        {"results": results["inference"], "status": "PASS"},
    )
    _write_json(RESULTS / "development_overfitting_audit.json", results["overfitting"])
    _write_json(RESULTS / "development_candidate_adjudication.json", adjudication)
    print(json.dumps(adjudication, indent=2, sort_keys=True))


def freeze_replication_shortlist() -> None:
    from fx_smc_bot.research.quant_polarity import canonical_json_sha256

    candidates = _read_json(RESULTS / "development_candidate_results.json")
    adjudication = _read_json(RESULTS / "development_candidate_adjudication.json")
    selected = list(adjudication["selected_candidates"])
    if len(selected) > 2:
        raise RuntimeError("Development adjudication exceeds the frozen shortlist maximum")
    payload: dict[str, Any] = {
        "shortlist_status": "FROZEN_BEFORE_REPLICATION_DATA_ACCESS",
        "shortlist_freeze_predecessor_sha": _git("rev-parse", "HEAD"),
        "selected_candidates": selected,
        "selected_count": len(selected),
        "maximum_selected": 2,
        "candidate_family_hash": "fd4f0a73b1277edf55160a3c844b6b5ab9b6e72622fcaed4aa8bd2aa8c1960e3",
        "model_hash": candidates["model"]["final_model_hash"],
        "selected_hyperparameters": candidates["model"]["selected_hyperparameters"],
        "development_rules_applied_mechanically": True,
        "manual_override": False,
        "replication_data_accessed": False,
        "replication_provider_request_sent": False,
        "status": "PASS",
    }
    payload["shortlist_hash"] = canonical_json_sha256(payload)
    _write_json(RESULTS / "replication_shortlist_freeze.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        choices=(
            "development-acquisition",
            "development-certification",
            "execution-certification",
            "development-execution",
            "development-evaluation",
            "replication-shortlist",
        ),
        required=True,
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.group == "development-acquisition":
        run_development_acquisition(args.workers)
    if args.group == "development-certification":
        run_development_certification(args.workers)
    if args.group == "execution-certification":
        run_execution_certification()
    if args.group == "development-execution":
        run_development_execution(args.workers)
    if args.group == "development-evaluation":
        run_development_evaluation()
    if args.group == "replication-shortlist":
        freeze_replication_shortlist()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
