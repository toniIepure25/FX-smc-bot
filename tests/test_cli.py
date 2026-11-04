"""Tests for the developer CLI."""

from __future__ import annotations

import json

import pytest

from fx_smc_bot import __version__
from fx_smc_bot.cli import main


def test_info_json_contains_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["version"] == __version__
    assert payload["status"] == "CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED"
    assert "2018+" in payload["holdout"]
    assert "doctor" in payload["commands"]


def test_doctor_validates_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--config", "configs/base.yaml"]) == 0
    output = capsys.readouterr().out

    assert "[ok  ] python" in output
    assert "[ok  ] config" in output
    assert "Doctor: checkout is usable." in output


def test_doctor_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--config", "configs/base.yaml", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    checks = {check["name"]: check["status"] for check in payload["checks"]}
    assert payload["status"] == "ok"
    assert checks["python"] == "ok"
    assert checks["config"] == "ok"


def test_backtest_synthetic_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backtest", "--synthetic", "--bars", "120", "--log-level", "ERROR"]) == 0
    output = capsys.readouterr().out

    assert "synthetic demo" in output
    assert "Total Trades:" in output


def test_dashboard_rejects_a_missing_app(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("streamlit")
    assert main(["dashboard", "--app", "does-not-exist/app.py"]) == 1
    assert "Dashboard app not found" in capsys.readouterr().err
