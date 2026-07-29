"""Tests for data provenance tracking."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.provenance import (
    DataProvenance,
    build_provenance,
    compute_series_checksum,
    detect_duplicate_timestamps,
    detect_missing_intervals,
)
from fx_smc_bot.domain import MarketBar


def _make_simple_series(n: int = 50) -> BarSeries:
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=5)
    bars = []
    for i in range(n):
        bars.append(MarketBar(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
            timestamp=start + delta * i,
            open=1.1, high=1.101, low=1.099, close=1.1,
            bar_index=i, spread=0.00015,
        ))
    return BarSeries.from_bars(bars)


class TestDetectMissingIntervals:

    def test_no_gaps(self):
        series = _make_simple_series(50)
        gaps = detect_missing_intervals(series.timestamps, 5)
        assert len(gaps) == 0

    def test_detects_gap(self):
        start = datetime(2024, 1, 2, 0, 0)
        delta = timedelta(minutes=5)
        bars = []
        for i in range(20):
            ts = start + delta * i
            if i == 10:
                ts = start + timedelta(minutes=100)  # big gap
            bars.append(MarketBar(
                pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
                timestamp=ts, open=1.1, high=1.101, low=1.099, close=1.1,
                bar_index=i,
            ))
        series = BarSeries.from_bars(bars)
        gaps = detect_missing_intervals(series.timestamps, 5, max_gap_multiple=3.0)
        assert len(gaps) > 0


class TestDetectDuplicates:

    def test_no_duplicates(self):
        series = _make_simple_series(20)
        assert detect_duplicate_timestamps(series.timestamps) == 0

    def test_counts_duplicates(self):
        ts = np.array([
            np.datetime64("2024-01-02T00:00"),
            np.datetime64("2024-01-02T00:00"),
            np.datetime64("2024-01-02T00:05"),
        ])
        assert detect_duplicate_timestamps(ts) == 1


class TestBuildProvenance:

    def test_basic_provenance(self):
        series = _make_simple_series(50)
        prov = build_provenance(series, source="test")
        assert prov.source == "test"
        assert prov.bar_count == 50
        assert prov.instrument == "EURUSD"
        assert prov.resolution == "5m"
        assert len(prov.checksum_sha256) == 64

    def test_provenance_roundtrip(self, tmp_path):
        series = _make_simple_series(20)
        prov = build_provenance(series, source="test", price_type="mid")

        path = tmp_path / "provenance.json"
        prov.save(path)
        loaded = DataProvenance.load(path)

        assert loaded.source == prov.source
        assert loaded.bar_count == prov.bar_count
        assert loaded.checksum_sha256 == prov.checksum_sha256


class TestSeriesChecksum:

    def test_deterministic(self):
        s1 = _make_simple_series(20)
        s2 = _make_simple_series(20)
        assert compute_series_checksum(s1) == compute_series_checksum(s2)

    def test_different_data_different_checksum(self):
        s1 = _make_simple_series(20)
        s2 = _make_simple_series(30)
        assert compute_series_checksum(s1) != compute_series_checksum(s2)
