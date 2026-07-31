from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_gate_f0rpe2erusdsr.py"


def test_runner_dry_run_freezes_exact_legacy_window(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--window",
            "legacy",
            "--clean-room-root",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["start"] == "2016-01-04"
    assert result["end"] == "2016-01-08"
    assert result["role"] == "LEGACY_PRE_FIELD_CHANGE_SCHEMA"
    assert result["request_count"] == result["snapshot_count"] == 0


def test_runner_dry_run_freezes_exact_modern_window(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--window",
            "modern",
            "--clean-room-root",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["start"] == "2016-03-01"
    assert result["end"] == "2016-03-04"
    assert result["role"] == "MODERN_POST_FIELD_CHANGE_SCHEMA"
    assert result["request_count"] == result["snapshot_count"] == 0
