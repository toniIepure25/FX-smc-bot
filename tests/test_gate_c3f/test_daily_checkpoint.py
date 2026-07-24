"""Tests for daily checkpoint acquisition, manifest persistence, and recovery."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fx_smc_bot.data.daily_checkpoint import (
    DayStatus,
    MonthManifest,
    compact_month,
    download_day_with_checkpoint,
    find_missing_days,
    load_month_manifest,
    save_month_manifest,
)


class TestManifestPersistence:
    def test_roundtrip(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=1,
            status="complete", rows=1440, checksum="abc",
        ))
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=5,
            status="market_closed", failure_category="MARKET_CLOSED_WEEKEND",
        ))
        save_month_manifest(tmp_path, manifest)

        loaded = load_month_manifest(tmp_path, "EURUSD", "bid", 2019, 1)
        assert loaded is not None
        assert len(loaded.days) == 2
        assert loaded.days[0].rows == 1440
        assert loaded.days[1].status == "market_closed"

    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        assert load_month_manifest(tmp_path, "EURUSD", "bid", 2019, 1) is None

    def test_manifest_is_json(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        save_month_manifest(tmp_path, manifest)
        path = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2019" / "month=01" / "manifest.json"
        )
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["pair"] == "EURUSD"


class TestDailyCheckpoint:
    @patch("fx_smc_bot.data.daily_checkpoint._download_single_day")
    def test_successful_day_download(
        self, mock_download, tmp_path: Path,
    ) -> None:
        mock_download.return_value = (
            [{"timestamp": 1546300800000, "open": 1.1, "high": 1.2,
              "low": 1.0, "close": 1.15, "volume": 100}],
            "",
        )
        ds = download_day_with_checkpoint(
            "EURUSD", "bid", 2019, 1, 1, tmp_path,
            instrument="eurusd",
        )
        assert ds.status == "complete"
        assert ds.rows == 1

    @patch("fx_smc_bot.data.daily_checkpoint._download_single_day")
    def test_weekend_not_failed(
        self, mock_download, tmp_path: Path,
    ) -> None:
        mock_download.return_value = ([], "")
        ds = download_day_with_checkpoint(
            "EURUSD", "bid", 2019, 1, 5, tmp_path,
            instrument="eurusd",
        )
        assert ds.status == "market_closed"

    @patch("fx_smc_bot.data.daily_checkpoint._download_single_day")
    def test_empty_business_day_is_failed(
        self, mock_download, tmp_path: Path,
    ) -> None:
        mock_download.return_value = ([], "")
        ds = download_day_with_checkpoint(
            "EURUSD", "bid", 2019, 1, 7, tmp_path,
            instrument="eurusd",
        )
        assert ds.status == "failed"
        assert ds.failure_category == "NO_PROVIDER_DATA"

    @patch("fx_smc_bot.data.daily_checkpoint._download_single_day")
    def test_network_failure_retried(
        self, mock_download, tmp_path: Path,
    ) -> None:
        mock_download.side_effect = [
            ([], "fetch failed"),
            ([], "fetch failed"),
            ([{"timestamp": 1546300800000}], ""),
        ]
        ds = download_day_with_checkpoint(
            "EURUSD", "bid", 2019, 1, 7, tmp_path,
            instrument="eurusd",
        )
        assert ds.status == "complete"
        assert ds.attempts == 3

    def test_cached_day_not_redownloaded(self, tmp_path: Path) -> None:
        day_dir = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2019" / "month=01" / "day=01"
        )
        day_dir.mkdir(parents=True)
        (day_dir / "data.json").write_text(
            json.dumps([{"timestamp": 1}]),
        )
        ds = download_day_with_checkpoint(
            "EURUSD", "bid", 2019, 1, 1, tmp_path,
            instrument="eurusd",
        )
        assert ds.status == "complete"
        assert ds.rows == 1
        assert ds.attempts == 0


class TestInterruptedRecovery:
    def test_find_missing_days_no_manifest(self, tmp_path: Path) -> None:
        missing = find_missing_days(tmp_path, "EURUSD", "bid", 2019, 1)
        assert len(missing) == 31

    def test_find_missing_days_partial_manifest(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        for day_num in [1, 2, 3]:
            manifest.days.append(DayStatus(
                pair="EURUSD", side="bid", year=2019, month=1, day=day_num,
                status="complete", rows=1440,
            ))
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=5,
            status="market_closed",
            failure_category="MARKET_CLOSED_WEEKEND",
        ))
        save_month_manifest(tmp_path, manifest)

        missing = find_missing_days(tmp_path, "EURUSD", "bid", 2019, 1)
        assert 1 not in missing
        assert 2 not in missing
        assert 5 not in missing
        assert 4 in missing
        assert 6 in missing

    def test_failed_retryable_is_missing(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=7,
            status="failed",
            failure_category="TRANSIENT_NETWORK_ERROR",
            error="fetch failed",
        ))
        save_month_manifest(tmp_path, manifest)

        missing = find_missing_days(tmp_path, "EURUSD", "bid", 2019, 1)
        assert 7 in missing

    def test_failed_nonretryable_is_missing_for_repair(
        self, tmp_path: Path,
    ) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=7,
            status="failed",
            failure_category="PARSER_ERROR",
            error="bad json",
        ))
        save_month_manifest(tmp_path, manifest)

        missing = find_missing_days(tmp_path, "EURUSD", "bid", 2019, 1)
        assert 7 in missing


class TestMonthlyCompaction:
    def test_compaction_combines_days(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=2,
        )

        for day_num in range(1, 29):
            day_dir = (
                tmp_path / "EURUSD" / "price=bid"
                / "year=2019" / "month=02" / f"day={day_num:02d}"
            )
            day_dir.mkdir(parents=True, exist_ok=True)
            rows = [{"timestamp": 1548979200000 + (day_num - 1) * 86400000 + i * 60000}
                    for i in range(10)]
            (day_dir / "data.json").write_text(json.dumps(rows))
            manifest.days.append(DayStatus(
                pair="EURUSD", side="bid", year=2019, month=2, day=day_num,
                status="complete", rows=10,
            ))

        compact_month(tmp_path, manifest)

        assert manifest.compacted
        assert manifest.compacted_rows == 280
        monthly_file = (
            tmp_path / "EURUSD" / "price=bid"
            / "year=2019" / "month=02" / "data.json"
        )
        assert monthly_file.exists()
        data = json.loads(monthly_file.read_text())
        assert len(data) == 280

    def test_compaction_skips_if_not_all_terminal(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=1,
            status="complete", rows=10,
        ))
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=2,
            status="pending",
        ))

        compact_month(tmp_path, manifest)
        assert not manifest.compacted

    def test_compaction_skips_failed_days(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        for day_num in range(1, 32):
            status = "complete"
            rows = 10
            if day_num == 7:
                status = "failed"
                rows = 0
            manifest.days.append(DayStatus(
                pair="EURUSD", side="bid", year=2019, month=1,
                day=day_num, status=status, rows=rows,
                failure_category="UNKNOWN_ERROR" if status == "failed" else "",
            ))

        compact_month(tmp_path, manifest)
        assert not manifest.compacted

    def test_compaction_skips_all_zero_rows(self, tmp_path: Path) -> None:
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        for day_num in range(1, 32):
            manifest.days.append(DayStatus(
                pair="EURUSD", side="bid", year=2019, month=1,
                day=day_num, status="complete", rows=0,
            ))

        compact_month(tmp_path, manifest)
        assert not manifest.compacted


class TestPersistentRunnerHeartbeat:
    def test_status_no_state(self, tmp_path: Path) -> None:
        from scripts.run_persistent_acquisition import PersistentRunner
        status = PersistentRunner.get_status(tmp_path)
        assert status["classifier"] == "PID_MISSING"


class TestHoldoutEventRejection:
    def test_persistent_runner_does_not_import_strategy(self) -> None:
        """The persistent runner module must not import strategy/event code."""
        import importlib
        spec = importlib.util.find_spec("scripts.run_persistent_acquisition")
        assert spec is not None
        source = Path(spec.origin).read_text()
        forbidden = [
            "strategy", "detector", "event_detection",
            "alpha_research", "campaign",
        ]
        for word in forbidden:
            assert word not in source.lower(), (
                f"Persistent runner imports/references '{word}'"
            )
