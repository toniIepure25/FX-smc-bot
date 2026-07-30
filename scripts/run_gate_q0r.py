"""Gate Q.0-R clean-room orchestration."""

from __future__ import annotations

import argparse
import json
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        choices=("development-acquisition", "development-certification"),
        required=True,
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.group == "development-acquisition":
        run_development_acquisition(args.workers)
    if args.group == "development-certification":
        run_development_certification(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
