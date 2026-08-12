"""Run the A0R4 V2 prospective readiness gate and print the terminal verdict.

Usage:
    python scripts/run_gate_a0r4.py

This never opens a 2018+ market/outcome file. It writes the ``results/gate_a0r4`` artifact
set and the ``docs/research/fx_alpha_discovery`` closure/protocol documents are maintained
separately.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fx_smc_bot.research.v2 import gate_a0r4

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001 - provenance is best-effort
        return ""


def main() -> None:
    git_sha = _git("rev-parse", "HEAD")
    remote_sha = _git("rev-parse", "@{u}")
    readiness = gate_a0r4.run(REPO, git_sha=git_sha, remote_sha=remote_sha)
    print("verdict:", readiness["verdict"])
    print("admitted_executable_trials:", readiness["admitted_executable_trials"])
    print("rejected_pre_outcome:", readiness["rejected_pre_outcome"])
    print("denominator:", readiness["registered_candidate_equivalent_denominator"])
    print("2018_plus_opened:", readiness["2018_plus_market_or_outcome_files_opened"])
    for name, ok in readiness["checks"].items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print("next_gate:", readiness["next_gate"])


if __name__ == "__main__":
    main()
