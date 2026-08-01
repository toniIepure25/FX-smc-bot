from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_gate_f0rpe2erusdsrlpa_live_adapters.py"
EXTERNAL_TMP = ROOT.parent / "FX-smc-bot-local-data" / "test-tmp"


def test_live_adapter_runner_dry_run_is_value_blind_and_plans_eur_transition() -> None:
    external_root = EXTERNAL_TMP / f"lpa-live-adapters-{uuid.uuid4().hex}"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--clean-room-root",
            str(external_root),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "DRY_RUN"
    assert result["official_rate_provider_requests_sent"] == 0
    assert result["source_snapshots_persisted"] == 0
    assert result["numerical_rows_exposed_to_parser"] == 0
    assert result["rate_versions_persisted"] == 0
    assert result["market_provider_requests_sent"] == 0

    eur_series = {
        item["series_id"] for item in result["request_windows"] if item["currency"] == "EUR"
    }
    assert eur_series == {"EONIA", "ESTR"}


def test_live_adapter_runner_rejects_clean_room_inside_git() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--clean-room-root",
            str(ROOT / "forbidden-live-adapter-snapshots"),
            "--dry-run",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "CLEAN_ROOM_ROOT_MUST_BE_OUTSIDE_GIT" in completed.stderr
    assert not (ROOT / "forbidden-live-adapter-snapshots").exists()


def test_live_adapter_runner_source_keeps_prohibited_scope_out() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "2023" not in source
    assert "2024" not in source
    assert "2025" not in source
    assert "NZD" not in source
