from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "run_gate_a0r2.py"
SPEC = importlib.util.spec_from_file_location("a0r2_native_route_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _artifact(root: Path, name: str, status: str) -> None:
    runner.write_json(root / name, {"status": status})


def test_native_selection_requires_independent_health_and_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path)
    _artifact(tmp_path, "native_bi5_health_controls.json", "PASS")
    _artifact(tmp_path, "dual_transport_parity_certification.json", "PASS")
    _artifact(tmp_path, "provider_health_controls.json", "PROVIDER_COOLDOWN_REQUIRED")

    transport, reason, health = runner.select_transport("native")

    assert (transport, reason) == ("native", "EXPLICIT_NATIVE_CERTIFIED")
    assert health["native"] == "PASS"


def test_auto_does_not_use_native_without_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path)
    _artifact(tmp_path, "native_bi5_health_controls.json", "PASS")
    _artifact(tmp_path, "dual_transport_parity_certification.json", "FAIL")
    _artifact(tmp_path, "provider_health_controls.json", "PROVIDER_COOLDOWN_REQUIRED")

    with pytest.raises(ValueError, match="A0R2_NO_CERTIFIED_HEALTHY_TRANSPORT"):
        runner.select_transport("auto")
