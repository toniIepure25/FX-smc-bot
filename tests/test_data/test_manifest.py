"""Tests for the dataset manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.data.manifest import DataManifest, DatasetEntry


class TestDatasetEntry:
    def test_auto_created_at(self) -> None:
        entry = DatasetEntry(
            pair="EURUSD", timeframe="15m", source="test",
            file_path="test.parquet", bar_count=100,
            start_date="2024-01-02", end_date="2024-03-31",
        )
        assert entry.created_at != ""


class TestDataManifest:
    def test_add_and_get_entry(self) -> None:
        m = DataManifest(name="test")
        entry = DatasetEntry(
            pair="EURUSD", timeframe="15m", source="test",
            file_path="test.parquet", bar_count=100,
            start_date="2024-01-02", end_date="2024-03-31",
        )
        m.add_entry(entry)
        assert m.get_entry("EURUSD", "15m") == entry

    def test_replace_existing_entry(self) -> None:
        m = DataManifest(name="test")
        entry1 = DatasetEntry(
            pair="EURUSD", timeframe="15m", source="v1",
            file_path="v1.parquet", bar_count=100,
            start_date="2024-01-02", end_date="2024-03-31",
        )
        entry2 = DatasetEntry(
            pair="EURUSD", timeframe="15m", source="v2",
            file_path="v2.parquet", bar_count=200,
            start_date="2024-01-02", end_date="2024-06-30",
        )
        m.add_entry(entry1)
        m.add_entry(entry2)
        assert len(m.entries) == 1
        assert m.get_entry("EURUSD", "15m").bar_count == 200

    def test_save_and_load(self, tmp_path: Path) -> None:
        m = DataManifest(name="test_manifest", description="unit test")
        m.add_entry(DatasetEntry(
            pair="EURUSD", timeframe="15m", source="test",
            file_path="test.parquet", bar_count=100,
            start_date="2024-01-02", end_date="2024-03-31",
        ))
        manifest_path = tmp_path / "manifest.json"
        m.save(manifest_path)
        loaded = DataManifest.load(manifest_path)
        assert loaded.name == "test_manifest"
        assert len(loaded.entries) == 1

    def test_summary(self) -> None:
        m = DataManifest(name="test")
        m.add_entry(DatasetEntry(
            pair="EURUSD", timeframe="15m", source="test",
            file_path="test.parquet", bar_count=1000,
            start_date="2024-01-02", end_date="2024-06-30",
        ))
        text = m.summary()
        assert "EURUSD" in text
        assert "1,000" in text

    def test_get_nonexistent_returns_none(self) -> None:
        m = DataManifest(name="test")
        assert m.get_entry("GBPUSD", "1h") is None
