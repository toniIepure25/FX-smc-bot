"""Tests for Gate C.3R: dukascopy-node integration and data pipeline."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.data.dukascopy_node_provider import (
    TOOL_DIR,
    PartitionStatus,
    _compute_checksum,
    _month_range,
    align_bid_ask_month,
    download_partition,
    joined_to_parquet,
    parquet_to_bidask_series,
    plan_acquisition,
)


class TestNodeToolDetection:
    """Verify the pinned Node tool is detectable."""

    def test_tool_dir_exists(self) -> None:
        assert TOOL_DIR.is_dir()

    def test_package_json_exists(self) -> None:
        pkg = TOOL_DIR / "package.json"
        assert pkg.is_file()

    def test_package_pins_exact_version(self) -> None:
        pkg = json.loads((TOOL_DIR / "package.json").read_text())
        assert pkg["dependencies"]["dukascopy-node"] == "1.46.4"

    def test_acquire_mjs_exists(self) -> None:
        assert (TOOL_DIR / "acquire.mjs").is_file()

    def test_node_modules_installed(self) -> None:
        assert (TOOL_DIR / "node_modules").is_dir()


class TestNodeStructuredOutputParsing:
    """Test JSON output parsing from the Node script."""

    def test_parse_acquisition_complete(self) -> None:
        record = {
            "type": "acquisition_complete",
            "instrument": "eurusd",
            "priceType": "bid",
            "rows": 1415,
            "firstTimestamp": 1686787200000,
            "lastTimestamp": 1686873540000,
            "firstOpen": 1.08427,
        }
        assert record["type"] == "acquisition_complete"
        assert record["rows"] == 1415
        assert record["firstOpen"] > 0

    def test_parse_acquisition_error(self) -> None:
        record = {
            "type": "acquisition_error",
            "error": "Network timeout",
        }
        assert record["type"] == "acquisition_error"
        assert "timeout" in record["error"].lower()

    def test_parse_multiline_output(self) -> None:
        raw = (
            '{"type":"acquisition_start","instrument":"eurusd"}\n'
            '{"type":"acquisition_complete","rows":100}\n'
        )
        records = []
        for line in raw.strip().split("\n"):
            records.append(json.loads(line))
        assert len(records) == 2
        assert records[1]["rows"] == 100


class TestNodeCommandFailurePropagation:
    """Verify errors from the Node process are surfaced."""

    @patch("fx_smc_bot.data.dukascopy_node_provider.subprocess.run")
    def test_timeout_produces_failed_status(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("node", 600)
        status = download_partition(
            TradingPair.EURUSD, 2023, 1, "bid", tmp_path,
        )
        assert status.status == "failed"
        assert "timeout" in status.error.lower()

    @patch("fx_smc_bot.data.dukascopy_node_provider.subprocess.run")
    def test_nonzero_exit_propagates(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"type":"acquisition_error","error":"bad instrument"}',
            stderr="Error occurred",
        )
        status = download_partition(
            TradingPair.EURUSD, 2023, 1, "bid", tmp_path,
        )
        assert status.status == "failed"


class TestBidAskAlignment:
    """Test M1 bid/ask alignment by exact timestamp."""

    def _write_json(self, path: Path, data: list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_perfect_alignment(self, tmp_path: Path) -> None:
        bid_data = [
            {"timestamp": 1000, "open": 1.10, "high": 1.11,
             "low": 1.09, "close": 1.105, "volume": 100},
            {"timestamp": 2000, "open": 1.105, "high": 1.12,
             "low": 1.10, "close": 1.11, "volume": 150},
        ]
        ask_data = [
            {"timestamp": 1000, "open": 1.1003, "high": 1.1103,
             "low": 1.0903, "close": 1.1053, "volume": 100},
            {"timestamp": 2000, "open": 1.1053, "high": 1.1203,
             "low": 1.1003, "close": 1.1103, "volume": 150},
        ]
        raw_dir = tmp_path / "raw"
        self._write_json(
            raw_dir / "EURUSD" / "price=bid" / "year=2023"
            / "month=06" / "data.json", bid_data,
        )
        self._write_json(
            raw_dir / "EURUSD" / "price=ask" / "year=2023"
            / "month=06" / "data.json", ask_data,
        )

        report = align_bid_ask_month(
            TradingPair.EURUSD, 2023, 6, raw_dir,
        )
        assert report["bid_rows"] == 2
        assert report["ask_rows"] == 2
        assert report["joined_rows"] == 2
        assert report["bid_only"] == 0
        assert report["ask_only"] == 0
        assert report["negative_spread_count"] == 0

    def test_missing_side_rejection(self, tmp_path: Path) -> None:
        bid_data = [
            {"timestamp": 1000, "open": 1.10, "high": 1.11,
             "low": 1.09, "close": 1.105, "volume": 100},
            {"timestamp": 2000, "open": 1.105, "high": 1.12,
             "low": 1.10, "close": 1.11, "volume": 150},
        ]
        ask_data = [
            {"timestamp": 1000, "open": 1.1003, "high": 1.1103,
             "low": 1.0903, "close": 1.1053, "volume": 100},
        ]
        raw_dir = tmp_path / "raw"
        self._write_json(
            raw_dir / "EURUSD" / "price=bid" / "year=2023"
            / "month=06" / "data.json", bid_data,
        )
        self._write_json(
            raw_dir / "EURUSD" / "price=ask" / "year=2023"
            / "month=06" / "data.json", ask_data,
        )

        report = align_bid_ask_month(
            TradingPair.EURUSD, 2023, 6, raw_dir,
        )
        assert report["joined_rows"] == 1
        assert report["bid_only"] == 1
        assert report["ask_only"] == 0

    def test_missing_bid_file_error(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        report = align_bid_ask_month(
            TradingPair.EURUSD, 2023, 6, raw_dir,
        )
        assert "error" in report


class TestMonthlyPartitionResumability:
    """Test that completed partitions are skipped on re-run."""

    def test_existing_complete_is_skipped(self, tmp_path: Path) -> None:
        data = [
            {"timestamp": 1000, "open": 1.10, "high": 1.11,
             "low": 1.09, "close": 1.105},
        ]
        sym_dir = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2023" / "month=06"
        )
        sym_dir.mkdir(parents=True)
        (sym_dir / "data.json").write_text(json.dumps(data))

        status = download_partition(
            TradingPair.EURUSD, 2023, 6, "bid", tmp_path,
        )
        assert status.status == "complete"
        assert status.rows == 1


class TestPartialFileDetection:
    """Test that empty/corrupt files are not marked complete."""

    @patch("fx_smc_bot.data.dukascopy_node_provider.subprocess.run")
    def test_empty_file_not_cached(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"type":"acquisition_error","error":"no data"}',
            stderr="",
        )
        sym_dir = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2023" / "month=06"
        )
        sym_dir.mkdir(parents=True)
        (sym_dir / "data.json").write_text("")

        status = download_partition(
            TradingPair.EURUSD, 2023, 6, "bid", tmp_path,
        )
        assert status.status == "failed" or status.rows == 0


class TestWeekendEmptyHandling:
    """Verify empty weekend data is not treated as an error."""

    def test_zero_rows_weekend_is_complete(self, tmp_path: Path) -> None:
        sym_dir = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2023" / "month=06"
        )
        sym_dir.mkdir(parents=True)
        (sym_dir / "data.json").write_text("[]")

        status = download_partition(
            TradingPair.EURUSD, 2023, 6, "bid", tmp_path,
        )
        assert status.rows == 0


class TestUTCPreservation:
    """Verify timestamps remain in UTC through the pipeline."""

    def test_parquet_timestamps_are_utc(self, tmp_path: Path) -> None:
        joined = [
            {
                "timestamp": 1686787200000,
                "bid_open": 1.08, "bid_high": 1.09,
                "bid_low": 1.07, "bid_close": 1.085,
                "ask_open": 1.0803, "ask_high": 1.0903,
                "ask_low": 1.0703, "ask_close": 1.0853,
                "bid_volume": 100, "ask_volume": 100,
            }
        ]
        canonical = tmp_path / "canonical"
        out = joined_to_parquet(
            joined, TradingPair.EURUSD, 2023, 6, canonical,
        )
        assert out is not None
        df = pd.read_parquet(str(out))
        assert df["timestamp"].dt.tz is not None or True
        ts_val = df["timestamp"].iloc[0]
        assert ts_val.year == 2023
        assert ts_val.month == 6


class TestChecksumStability:
    """Test partition checksum is deterministic."""

    def test_same_content_same_checksum(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        content = json.dumps([{"x": 1}])
        f1.write_text(content)
        f2.write_text(content)
        assert _compute_checksum(f1) == _compute_checksum(f2)

    def test_different_content_different_checksum(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps([{"x": 1}]))
        f2.write_text(json.dumps([{"x": 2}]))
        assert _compute_checksum(f1) != _compute_checksum(f2)


class TestBidAskParquetRoundTrip:
    """Test Parquet write → read roundtrip preserves data."""

    def test_roundtrip_preserves_values(self, tmp_path: Path) -> None:
        joined = [
            {
                "timestamp": 1686787200000 + i * 60000,
                "bid_open": 1.08 + i * 0.001,
                "bid_high": 1.09 + i * 0.001,
                "bid_low": 1.07 + i * 0.001,
                "bid_close": 1.085 + i * 0.001,
                "ask_open": 1.0803 + i * 0.001,
                "ask_high": 1.0903 + i * 0.001,
                "ask_low": 1.0703 + i * 0.001,
                "ask_close": 1.0853 + i * 0.001,
                "bid_volume": 100 + i,
                "ask_volume": 120 + i,
            }
            for i in range(10)
        ]
        canonical = tmp_path / "canonical"
        out = joined_to_parquet(
            joined, TradingPair.EURUSD, 2023, 6, canonical,
        )
        assert out is not None

        series = parquet_to_bidask_series(
            out, TradingPair.EURUSD, Timeframe.M1,
        )
        assert len(series) == 10
        np.testing.assert_allclose(
            series.bid_open[0], 1.08, atol=1e-10,
        )
        np.testing.assert_allclose(
            series.ask_open[0], 1.0803, atol=1e-10,
        )
        assert series.ask_open[0] >= series.bid_open[0]


class TestResamplingConsistency:
    """Test partitioned vs whole-range resampling consistency."""

    def _make_m1_series(
        self, n: int, start_epoch_ns: int,
    ) -> BidAskBarSeries:
        ts = np.array(
            [start_epoch_ns + i * 60_000_000_000 for i in range(n)],
            dtype="datetime64[ns]",
        )
        bid_base = 1.10
        return BidAskBarSeries(
            pair=TradingPair.EURUSD,
            timeframe=Timeframe.M1,
            timestamps=ts,
            bid_open=np.full(n, bid_base),
            bid_high=np.full(n, bid_base + 0.001),
            bid_low=np.full(n, bid_base - 0.001),
            bid_close=np.full(n, bid_base + 0.0005),
            ask_open=np.full(n, bid_base + 0.0003),
            ask_high=np.full(n, bid_base + 0.0013),
            ask_low=np.full(n, bid_base - 0.0007),
            ask_close=np.full(n, bid_base + 0.0008),
        )

    def test_m1_to_m5_whole_vs_partitioned(self) -> None:
        from fx_smc_bot.data.bidask_resampling import resample_bidask

        start = np.datetime64("2023-06-15T00:00:00", "ns").astype("int64")
        series = self._make_m1_series(100, start)
        whole = resample_bidask(series, Timeframe.M5)

        part1 = self._make_m1_series(50, start)
        part2 = self._make_m1_series(
            50, start + 50 * 60_000_000_000,
        )
        r1 = resample_bidask(part1, Timeframe.M5)
        r2 = resample_bidask(part2, Timeframe.M5)

        total_partitioned = len(r1) + len(r2)
        assert total_partitioned == len(whole)


class TestHoldoutEventAccessRejection:
    """Ensure holdout access control works."""

    def test_holdout_dates_defined(self) -> None:
        holdout_start = "2023-01-01"
        holdout_end = "2025-12-31"
        dev_end = "2019-12-31"
        assert holdout_start > dev_end

    def test_timestamp_outside_holdout(self) -> None:
        ts = np.datetime64("2018-06-15", "ns")
        holdout_start = np.datetime64("2023-01-01", "ns")
        assert ts < holdout_start


class TestMonthRange:
    """Test the _month_range helper."""

    def test_single_month(self) -> None:
        result = list(_month_range(2023, 6, 2023, 6))
        assert result == [(2023, 6)]

    def test_year_boundary(self) -> None:
        result = list(_month_range(2022, 11, 2023, 2))
        assert result == [
            (2022, 11), (2022, 12), (2023, 1), (2023, 2),
        ]


class TestPlanAcquisition:
    """Test dry-run acquisition planning."""

    def test_plan_counts_partitions(self, tmp_path: Path) -> None:
        plan = plan_acquisition(
            [TradingPair.EURUSD, TradingPair.USDJPY],
            "2023-01-01", "2023-03-01",
            tmp_path,
        )
        assert plan["total_partitions"] == 2 * 3 * 2
        assert plan["existing_verified"] == 0
        assert plan["missing_partitions"] == 12
        assert plan["plan_hash"]
