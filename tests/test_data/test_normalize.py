"""Tests for the multi-format CSV normalizer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from fx_smc_bot.data.normalize import (
    CsvFormat,
    detect_format,
    load_parquet,
    normalize_csv,
    save_parquet,
)


@pytest.fixture
def generic_csv(tmp_path: Path) -> Path:
    path = tmp_path / "test.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-02 00:00:00,1.1000,1.1010,1.0990,1.1005,100\n"
        "2024-01-02 00:15:00,1.1005,1.1020,1.0995,1.1015,150\n"
        "2024-01-02 00:15:00,1.1005,1.1020,1.0995,1.1016,160\n"  # duplicate
    )
    return path


@pytest.fixture
def metatrader_csv(tmp_path: Path) -> Path:
    path = tmp_path / "mt4.csv"
    path.write_text(
        "<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<TICKVOL>\n"
        "2024.01.02,00:00,1.1000,1.1010,1.0990,1.1005,100\n"
        "2024.01.02,00:15,1.1005,1.1020,1.0995,1.1015,150\n"
    )
    return path


@pytest.fixture
def dukascopy_csv(tmp_path: Path) -> Path:
    path = tmp_path / "duka.csv"
    path.write_text(
        "Gmt time,Open,High,Low,Close,Volume\n"
        "02.01.2024 00:00:00,1.1000,1.1010,1.0990,1.1005,100\n"
        "02.01.2024 00:15:00,1.1005,1.1020,1.0995,1.1015,150\n"
    )
    return path


class TestDetectFormat:
    def test_generic(self, generic_csv: Path) -> None:
        assert detect_format(generic_csv) == CsvFormat.GENERIC

    def test_metatrader(self, metatrader_csv: Path) -> None:
        assert detect_format(metatrader_csv) == CsvFormat.METATRADER

    def test_dukascopy(self, dukascopy_csv: Path) -> None:
        assert detect_format(dukascopy_csv) == CsvFormat.DUKASCOPY


class TestNormalizeCsv:
    def test_generic_has_canonical_columns(self, generic_csv: Path) -> None:
        df = normalize_csv(generic_csv)
        assert "timestamp" in df.columns
        assert "open" in df.columns
        assert "close" in df.columns
        assert df["timestamp"].dt.tz is not None

    def test_deduplication(self, generic_csv: Path) -> None:
        df = normalize_csv(generic_csv)
        assert len(df) == 2  # duplicate row removed

    def test_metatrader_normalization(self, metatrader_csv: Path) -> None:
        df = normalize_csv(metatrader_csv)
        assert len(df) == 2
        assert df["timestamp"].dt.tz is not None

    def test_dukascopy_normalization(self, dukascopy_csv: Path) -> None:
        df = normalize_csv(dukascopy_csv)
        assert len(df) == 2

    def test_sorted_by_timestamp(self, generic_csv: Path) -> None:
        df = normalize_csv(generic_csv)
        assert df["timestamp"].is_monotonic_increasing


class TestParquetRoundTrip:
    def test_save_and_load(self, generic_csv: Path, tmp_path: Path) -> None:
        df = normalize_csv(generic_csv)
        pq_path = save_parquet(df, tmp_path / "test.parquet")
        loaded = load_parquet(pq_path)
        assert len(loaded) == len(df)
        assert list(loaded.columns) == list(df.columns)
