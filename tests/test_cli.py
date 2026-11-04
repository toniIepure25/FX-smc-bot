"""Tests for the developer CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from fx_smc_bot import __version__
from fx_smc_bot.backtesting.runner import synthetic_market_data
from fx_smc_bot.cli import main
from fx_smc_bot.config import Timeframe, TradingPair


def _write_csv_dataset(
    root: Path,
    *,
    pairs: list[TradingPair] | None = None,
    bars: int = 120,
) -> None:
    for pair, series in synthetic_market_data(bars, pairs=pairs).items():
        pair_dir = root / pair.value
        pair_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(series.timestamps),
                "open": series.open,
                "high": series.high,
                "low": series.low,
                "close": series.close,
            }
        ).to_csv(pair_dir / f"{Timeframe.M15.value}.csv", index=False)


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


def test_data_json_reports_loaded_pairs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_csv_dataset(tmp_path)
    assert main(["data", "--data-dir", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["expected_timeframe"] == "15m"
    assert payload["loaded_pairs"] == ["EURUSD", "GBPUSD", "USDJPY"]
    assert all(pair["timeframe_ok"] for pair in payload["pairs"])
    assert all(pair["quality_score"] > 0.8 for pair in payload["pairs"])


def test_data_writes_json_artifact(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_csv_dataset(data_dir)
    output = tmp_path / "audit.json"

    assert main(["data", "--data-dir", str(data_dir), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["loaded_pairs"] == ["EURUSD", "GBPUSD", "USDJPY"]


def test_data_strict_fails_when_a_pair_is_missing(tmp_path: Path) -> None:
    _write_csv_dataset(tmp_path, pairs=[TradingPair.EURUSD])
    assert main(["data", "--data-dir", str(tmp_path), "--strict"]) == 1


def test_doctor_with_data_dir_uses_the_audit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_csv_dataset(tmp_path, pairs=[TradingPair.EURUSD])
    assert main(["doctor", "--data-dir", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    checks = {check["name"]: check["status"] for check in payload["checks"]}
    assert checks["data"] == "warn"


def test_backtest_synthetic_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backtest", "--synthetic", "--bars", "120", "--log-level", "ERROR"]) == 0
    output = capsys.readouterr().out

    assert "synthetic demo" in output
    assert "Total Trades:" in output


def test_backtest_writes_reproducibility_manifest(
    tmp_path: Path,
) -> None:
    assert (
        main(
            [
                "backtest",
                "--synthetic",
                "--bars",
                "120",
                "--seed",
                "7",
                "--output-dir",
                str(tmp_path),
                "--label",
                "manifest-test",
                "--log-level",
                "ERROR",
            ]
        )
        == 0
    )
    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1

    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["label"] == "manifest-test"
    assert manifest["source"] == "synthetic"
    assert manifest["data"]["seed"] == 7
    assert manifest["data"]["requested_bars"] == 120
    assert manifest["data"]["pairs"] == ["EURUSD", "GBPUSD", "USDJPY"]
    assert manifest["data"]["bars"] == {"EURUSD": 120, "GBPUSD": 120, "USDJPY": 120}
    assert len(manifest["config"]["sha256"]) == 64
    assert len(manifest["data"]["fingerprint"]) == 64
    assert manifest["audit"] is None


def test_backtest_writes_local_audit_artifact(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "runs"
    _write_csv_dataset(data_dir)

    assert (
        main(
            [
                "backtest",
                "--data-dir",
                str(data_dir),
                "--output-dir",
                str(output_dir),
                "--require-quality",
                "--label",
                "local-audit",
                "--log-level",
                "ERROR",
            ]
        )
        == 0
    )
    run_dirs = [path for path in output_dir.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1

    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((run_dirs[0] / "audit.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "local"
    assert manifest["audit"]["status"] == "ok"
    assert audit["status"] == "ok"
    assert manifest["data"]["directory"] == str(data_dir.resolve())


def test_backtest_require_quality_rejects_missing_pairs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    _write_csv_dataset(data_dir, pairs=[TradingPair.EURUSD])

    assert (
        main(
            [
                "backtest",
                "--data-dir",
                str(data_dir),
                "--require-quality",
                "--log-level",
                "ERROR",
            ]
        )
        == 1
    )
    assert "data audit must be ok" in capsys.readouterr().err


def test_backtest_require_quality_requires_data_dir() -> None:
    assert (
        main(
            [
                "backtest",
                "--synthetic",
                "--bars",
                "120",
                "--require-quality",
                "--log-level",
                "ERROR",
            ]
        )
        == 1
    )


def test_dashboard_rejects_a_missing_app(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("streamlit")
    assert main(["dashboard", "--app", "does-not-exist/app.py"]) == 1
    assert "Dashboard app not found" in capsys.readouterr().err
