"""Tests for the market-data audit."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fx_smc_bot.backtesting.runner import synthetic_market_data
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.audit import audit_market_data, format_data_audit


def _write_dataset(
    root: Path,
    *,
    pairs: list[TradingPair] | None = None,
    bars: int = 120,
    duplicate_eurusd: bool = False,
) -> None:
    data = synthetic_market_data(bars, pairs=pairs)
    for pair, series in data.items():
        pair_dir = root / pair.value
        pair_dir.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(series.timestamps),
                "open": series.open,
                "high": series.high,
                "low": series.low,
                "close": series.close,
            }
        )
        if duplicate_eurusd and pair is TradingPair.EURUSD:
            frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        frame.to_csv(pair_dir / f"{Timeframe.M15.value}.csv", index=False)


def test_clean_dataset_is_ok(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    audit = audit_market_data(AppConfig(), tmp_path)

    assert audit.status == "ok"
    assert audit.error is None
    assert set(audit.loaded_pairs) == {"EURUSD", "GBPUSD", "USDJPY"}
    assert audit.missing_pairs == ()
    assert all(pair.status == "ok" for pair in audit.pairs)


def test_missing_configured_pair_is_a_warning(tmp_path: Path) -> None:
    _write_dataset(tmp_path, pairs=[TradingPair.EURUSD, TradingPair.GBPUSD])
    audit = audit_market_data(AppConfig(), tmp_path)

    assert audit.status == "warn"
    assert audit.missing_pairs == ("USDJPY",)
    assert "USDJPY" in format_data_audit(audit)


def test_empty_directory_fails(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    audit = audit_market_data(AppConfig(), empty)

    assert audit.status == "fail"
    assert audit.error is not None
    assert audit.pairs == ()


def test_duplicate_timestamp_warns(tmp_path: Path) -> None:
    _write_dataset(tmp_path, duplicate_eurusd=True)
    audit = audit_market_data(AppConfig(), tmp_path)

    assert audit.status == "warn"
    eurusd = next(pair for pair in audit.pairs if pair.pair == "EURUSD")
    assert eurusd.duplicates == 1
    assert eurusd.status == "warn"


def test_json_shape_is_serialisable(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    payload = audit_market_data(AppConfig(), tmp_path).as_dict()

    assert payload["status"] == "ok"
    assert payload["configured_pairs"] == ["EURUSD", "GBPUSD", "USDJPY"]
    assert payload["pairs"][0]["pair"] == "EURUSD"
    assert isinstance(payload["pairs"][0]["issues"], list)
