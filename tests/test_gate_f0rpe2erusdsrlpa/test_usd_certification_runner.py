from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_gate_f0rpe2erusdsrlpa_usd.py"
RESULTS = ROOT / "results" / "gate_f0rpe2erusdsrlpa"
EXTERNAL_TMP = ROOT.parent / "FX-smc-bot-local-data" / "test-tmp"


def test_runner_dry_run_is_offline_and_does_not_create_database(tmp_path: Path) -> None:
    external_root = EXTERNAL_TMP / f"effr-v4-{uuid.uuid4().hex}"
    database = external_root / "rate-vintage-v4.sqlite3"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-clean-room-root",
            str(external_root / "source"),
            "--v4-database",
            str(database),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "DRY_RUN"
    assert result["request_count"] == 2
    assert result["network_request_count"] == 0
    assert result["parse_count"] == 0
    assert result["v4_database_created"] is False
    assert not database.exists()


def test_runner_rejects_a_database_inside_git(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-clean-room-root",
            str(EXTERNAL_TMP / f"effr-source-{uuid.uuid4().hex}"),
            "--v4-database",
            str(ROOT / "forbidden-rate-vintage-v4.sqlite3"),
            "--dry-run",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "V4_DATABASE_MUST_BE_OUTSIDE_GIT" in completed.stderr
    assert not (ROOT / "forbidden-rate-vintage-v4.sqlite3").exists()


def test_runner_contains_no_network_client_or_2023_2025_nzd_scope() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "OfficialRateSnapshotClient" not in source
    assert "urlopen" not in source
    assert "requests." not in source
    assert "2023" not in source
    assert "2024" not in source
    assert "2025" not in source
    assert "NZD" not in source


def test_usd_certification_artifacts_pass_and_contain_no_official_rows() -> None:
    adapter = json.loads((RESULTS / "usd_adapter_v3_certification.json").read_text())
    store = json.loads((RESULTS / "vintage_store_v4_certification.json").read_text())
    asof = json.loads((RESULTS / "usd_asof_availability_audit.json").read_text())

    assert adapter["status"] == store["status"] == asof["status"] == "PASS"
    assert adapter["request_count"] == adapter["reused_snapshot_count"] == 2
    assert adapter["legacy_version_count"] == 5
    assert adapter["modern_version_count"] == 4
    assert adapter["actual_publication_timestamp_non_null_count"] == 0
    assert asof["asof_before_availability_missing"] == 9
    assert asof["asof_at_availability_available"] == 9
    assert asof["asof_after_availability_available"] == 9

    serialized = json.dumps([adapter, store, asof], sort_keys=True)
    for forbidden in ('"value"', "percentRate", "effectiveDate", "refRates"):
        assert forbidden not in serialized
