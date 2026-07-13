"""Historical FX data provider interfaces and adapters for research.

Implements a provider protocol with concrete adapters for:
- Dukascopy: tick/M1 bar acquisition from public bi5 data
- OANDA: REST API v20 candles (requires OANDA_API_TOKEN env var)
- MT5: CSV import from MetaTrader 5 broker exports

Provider cross-validation utility for comparing overlapping data sources.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import lzma
import os
import struct
import time as time_mod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadResult:
    """Result of a data download operation."""
    pair: TradingPair
    resolution: str
    start: datetime
    end: datetime
    rows: int
    provider: str
    has_bid_ask: bool
    raw_files: list[str] = field(default_factory=list)
    checksums: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    data: BidAskBarSeries | None = None


@runtime_checkable
class HistoricalFxDataProvider(Protocol):
    """Protocol for FX data providers."""
    provider_name: str

    def download(
        self,
        pair: TradingPair,
        start: datetime,
        end: datetime,
        resolution: str = "M1",
    ) -> DownloadResult: ...


DUKASCOPY_PAIR_MAP = {
    TradingPair.EURUSD: "EURUSD",
    TradingPair.GBPUSD: "GBPUSD",
    TradingPair.USDJPY: "USDJPY",
    TradingPair.GBPJPY: "GBPJPY",
}


class DukascopyProvider:
    """Dukascopy historical tick data provider.

    Downloads bi5-compressed tick data from Dukascopy's public servers.
    Each file contains one hour of tick data with bid/ask prices and volumes.
    """

    provider_name = "dukascopy"
    _BASE_URL = "https://datafeed.dukascopy.com/datafeed"

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._cache_dir = cache_dir or Path("data/raw/dukascopy")
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def download(
        self,
        pair: TradingPair,
        start: datetime,
        end: datetime,
        resolution: str = "M1",
    ) -> DownloadResult:
        """Download tick data and resample to the requested resolution."""
        symbol = DUKASCOPY_PAIR_MAP.get(pair)
        if symbol is None:
            return DownloadResult(
                pair=pair, resolution=resolution,
                start=start, end=end, rows=0,
                provider=self.provider_name, has_bid_ask=True,
                errors=[f"Unsupported pair: {pair.value}"],
            )

        raw_files: list[str] = []
        checksums: dict[str, str] = {}
        errors: list[str] = []
        all_ticks: list[tuple[datetime, float, float, float, float]] = []

        current = start.replace(minute=0, second=0, microsecond=0)
        while current < end:
            try:
                ticks, file_path = self._download_hour(symbol, current)
                if ticks:
                    all_ticks.extend(ticks)
                if file_path:
                    raw_files.append(str(file_path))
                    checksums[str(file_path)] = self._file_checksum(file_path)
            except Exception as exc:
                errors.append(f"Failed {current}: {exc}")
            current += timedelta(hours=1)

        if not all_ticks:
            return DownloadResult(
                pair=pair, resolution=resolution,
                start=start, end=end, rows=0,
                provider=self.provider_name, has_bid_ask=True,
                raw_files=raw_files, checksums=checksums,
                errors=errors or ["No tick data downloaded"],
            )

        series = self._resample_ticks(pair, all_ticks, resolution)

        return DownloadResult(
            pair=pair, resolution=resolution,
            start=start, end=end,
            rows=len(series) if series else 0,
            provider=self.provider_name, has_bid_ask=True,
            raw_files=raw_files, checksums=checksums,
            errors=errors, data=series,
        )

    def _download_hour(
        self,
        symbol: str,
        hour: datetime,
    ) -> tuple[list[tuple[datetime, float, float, float, float]], Path | None]:
        """Download one hour of bi5 tick data."""
        month_0 = hour.month - 1
        url = (
            f"{self._BASE_URL}/{symbol}/"
            f"{hour.year}/{month_0:02d}/{hour.day:02d}/"
            f"{hour.hour:02d}h_ticks.bi5"
        )

        cache_file = (
            self._cache_dir / symbol /
            f"{hour.year}" / f"{month_0:02d}" / f"{hour.day:02d}" /
            f"{hour.hour:02d}h_ticks.bi5"
        )

        if cache_file.exists() and cache_file.stat().st_size > 0:
            return self._parse_bi5(cache_file, hour), cache_file

        cache_file.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(self._max_retries):
            try:
                req = Request(url, headers={"User-Agent": "FX-SMC-Research/1.0"})
                with urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                if raw:
                    cache_file.write_bytes(raw)
                    return self._parse_bi5(cache_file, hour), cache_file
                return [], None
            except (URLError, OSError) as exc:
                if attempt < self._max_retries - 1:
                    time_mod.sleep(self._retry_delay * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"Download failed after {self._max_retries} retries: {url}"
                    ) from exc
        return [], None

    @staticmethod
    def _parse_bi5(
        path: Path,
        base_hour: datetime,
    ) -> list[tuple[datetime, float, float, float, float]]:
        """Parse bi5 (LZMA-compressed) tick file.

        Each tick record is 20 bytes:
          uint32: milliseconds since hour start
          uint32: ask price (point format)
          uint32: bid price (point format)
          float32: ask volume
          float32: bid volume
        """
        try:
            raw = lzma.decompress(path.read_bytes())
        except (lzma.LZMAError, EOFError):
            return []

        if len(raw) == 0:
            return []

        record_size = 20
        n_records = len(raw) // record_size
        ticks = []

        for i in range(n_records):
            offset = i * record_size
            ms, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack_from(
                ">IIIff", raw, offset
            )
            ts = base_hour + timedelta(milliseconds=ms)
            ask_price = ask_raw / 100000.0
            bid_price = bid_raw / 100000.0
            ticks.append((ts, bid_price, ask_price, bid_vol, ask_vol))

        return ticks

    @staticmethod
    def _resample_ticks(
        pair: TradingPair,
        ticks: list[tuple[datetime, float, float, float, float]],
        resolution: str,
    ) -> BidAskBarSeries | None:
        """Resample raw ticks to OHLC bars at the given resolution."""
        if not ticks:
            return None

        minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}
        period_minutes = minutes.get(resolution, 1)

        ticks.sort(key=lambda t: t[0])

        bars: dict[datetime, list[tuple[datetime, float, float, float, float]]] = {}
        for tick in ticks:
            ts = tick[0]
            bar_start = ts.replace(second=0, microsecond=0)
            bar_minute = (bar_start.minute // period_minutes) * period_minutes
            bar_start = bar_start.replace(minute=bar_minute)
            if bar_start not in bars:
                bars[bar_start] = []
            bars[bar_start].append(tick)

        sorted_bars = sorted(bars.keys())
        n = len(sorted_bars)
        if n == 0:
            return None

        timestamps = np.array(
            [np.datetime64(ts.replace(tzinfo=None)) for ts in sorted_bars],
            dtype="datetime64[ns]"
        )
        bid_o = np.zeros(n, dtype=np.float64)
        bid_h = np.zeros(n, dtype=np.float64)
        bid_l = np.zeros(n, dtype=np.float64)
        bid_c = np.zeros(n, dtype=np.float64)
        ask_o = np.zeros(n, dtype=np.float64)
        ask_h = np.zeros(n, dtype=np.float64)
        ask_l = np.zeros(n, dtype=np.float64)
        ask_c = np.zeros(n, dtype=np.float64)
        vol = np.zeros(n, dtype=np.float64)

        for i, bar_ts in enumerate(sorted_bars):
            bar_ticks = bars[bar_ts]
            bids = [t[1] for t in bar_ticks]
            asks = [t[2] for t in bar_ticks]
            bid_o[i] = bids[0]
            bid_h[i] = max(bids)
            bid_l[i] = min(bids)
            bid_c[i] = bids[-1]
            ask_o[i] = asks[0]
            ask_h[i] = max(asks)
            ask_l[i] = min(asks)
            ask_c[i] = asks[-1]
            vol[i] = sum(t[3] + t[4] for t in bar_ticks)

        tf_map = {
            "M1": Timeframe.M1, "M5": Timeframe.M5,
            "M15": Timeframe.M15, "H1": Timeframe.H1,
        }

        return BidAskBarSeries(
            pair=pair,
            timeframe=tf_map.get(resolution, Timeframe.M1),
            timestamps=timestamps,
            bid_open=bid_o, bid_high=bid_h, bid_low=bid_l, bid_close=bid_c,
            ask_open=ask_o, ask_high=ask_h, ask_low=ask_l, ask_close=ask_c,
            volume=vol,
        )

    @staticmethod
    def _file_checksum(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()[:16]

    def manual_acquisition_instructions(self) -> str:
        return """
## Dukascopy Manual Data Acquisition

1. Download JForex from https://www.dukascopy.com/trading-tools/jforex-platform/
2. Open Historical Data Export
3. Configure: Instrument (EUR/USD, GBP/USD, USD/JPY), Period (Ticks or M1),
   Date range, Bid/Ask: Both, Format: CSV
4. Export to data/raw/dukascopy/<PAIR>/
5. Run: python scripts/ingest_data.py --provider dukascopy --format csv
"""


class OandaProvider:
    """OANDA REST API v20 candles provider.

    Requires OANDA_API_TOKEN environment variable.
    """

    provider_name = "oanda"
    _PRACTICE_URL = "https://api-fxpractice.oanda.com"
    _LIVE_URL = "https://api-fxtrade.oanda.com"
    _MAX_CANDLES = 5000

    PAIR_MAP = {
        TradingPair.EURUSD: "EUR_USD",
        TradingPair.GBPUSD: "GBP_USD",
        TradingPair.USDJPY: "USD_JPY",
        TradingPair.GBPJPY: "GBP_JPY",
    }

    GRANULARITY_MAP = {
        "M1": "M1", "M5": "M5", "M15": "M15",
        "H1": "H1", "H4": "H4", "D1": "D",
    }

    def __init__(self, practice: bool = True) -> None:
        self._token = os.environ.get("OANDA_API_TOKEN", "")
        self._base_url = self._PRACTICE_URL if practice else self._LIVE_URL

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def download(
        self,
        pair: TradingPair,
        start: datetime,
        end: datetime,
        resolution: str = "M1",
    ) -> DownloadResult:
        if not self.is_configured:
            return DownloadResult(
                pair=pair, resolution=resolution,
                start=start, end=end, rows=0,
                provider=self.provider_name, has_bid_ask=True,
                errors=["OANDA_API_TOKEN not set"],
            )

        instrument = self.PAIR_MAP.get(pair)
        granularity = self.GRANULARITY_MAP.get(resolution)
        if not instrument or not granularity:
            return DownloadResult(
                pair=pair, resolution=resolution,
                start=start, end=end, rows=0,
                provider=self.provider_name, has_bid_ask=True,
                errors=[f"Unsupported pair/resolution: {pair.value}/{resolution}"],
            )

        all_candles: list[dict] = []
        errors: list[str] = []
        current_start = start

        while current_start < end:
            try:
                batch = self._fetch_candles(instrument, granularity, current_start, end)
                if not batch:
                    break
                all_candles.extend(batch)
                last_time = datetime.fromisoformat(
                    batch[-1]["time"].replace("Z", "+00:00")
                )
                current_start = last_time + timedelta(seconds=1)
            except Exception as exc:
                errors.append(str(exc))
                break

        if not all_candles:
            return DownloadResult(
                pair=pair, resolution=resolution,
                start=start, end=end, rows=0,
                provider=self.provider_name, has_bid_ask=True,
                errors=errors or ["No candles returned"],
            )

        seen: set[str] = set()
        deduped = []
        for c in all_candles:
            if c["time"] not in seen:
                seen.add(c["time"])
                deduped.append(c)
        deduped = [c for c in deduped if c.get("complete", True)]

        series = self._to_bidask_series(pair, deduped, resolution)

        return DownloadResult(
            pair=pair, resolution=resolution,
            start=start, end=end,
            rows=len(series) if series else 0,
            provider=self.provider_name, has_bid_ask=True,
            errors=errors, data=series,
        )

    def _fetch_candles(
        self, instrument: str, granularity: str,
        start: datetime, end: datetime,
    ) -> list[dict]:
        url = (
            f"{self._base_url}/v3/instruments/{instrument}/candles"
            f"?granularity={granularity}"
            f"&from={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&to={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&price=BA&count={self._MAX_CANDLES}"
        )
        req = Request(url)
        req.add_header("Authorization", f"Bearer {self._token}")
        with urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        return body.get("candles", [])

    @staticmethod
    def _to_bidask_series(
        pair: TradingPair, candles: list[dict], resolution: str,
    ) -> BidAskBarSeries | None:
        if not candles:
            return None
        n = len(candles)
        timestamps = np.empty(n, dtype="datetime64[ns]")
        bid_o = np.zeros(n, dtype=np.float64)
        bid_h = np.zeros(n, dtype=np.float64)
        bid_l = np.zeros(n, dtype=np.float64)
        bid_c = np.zeros(n, dtype=np.float64)
        ask_o = np.zeros(n, dtype=np.float64)
        ask_h = np.zeros(n, dtype=np.float64)
        ask_l = np.zeros(n, dtype=np.float64)
        ask_c = np.zeros(n, dtype=np.float64)
        vol = np.zeros(n, dtype=np.float64)

        for i, c in enumerate(candles):
            timestamps[i] = np.datetime64(c["time"].replace("Z", "").split(".")[0])
            bid = c.get("bid", {})
            ask = c.get("ask", {})
            bid_o[i] = float(bid.get("o", 0))
            bid_h[i] = float(bid.get("h", 0))
            bid_l[i] = float(bid.get("l", 0))
            bid_c[i] = float(bid.get("c", 0))
            ask_o[i] = float(ask.get("o", 0))
            ask_h[i] = float(ask.get("h", 0))
            ask_l[i] = float(ask.get("l", 0))
            ask_c[i] = float(ask.get("c", 0))
            vol[i] = float(c.get("volume", 0))

        tf_map = {"M1": Timeframe.M1, "M5": Timeframe.M5, "M15": Timeframe.M15, "H1": Timeframe.H1}
        return BidAskBarSeries(
            pair=pair, timeframe=tf_map.get(resolution, Timeframe.M1),
            timestamps=timestamps,
            bid_open=bid_o, bid_high=bid_h, bid_low=bid_l, bid_close=bid_c,
            ask_open=ask_o, ask_high=ask_h, ask_low=ask_l, ask_close=ask_c,
            volume=vol,
        )


class MT5CsvImporter:
    """Import MT5 broker CSV exports."""

    provider_name = "mt5"

    def __init__(self, broker_timezone: str = "UTC") -> None:
        self._broker_tz = broker_timezone

    def import_csv(
        self, path: Path, pair: TradingPair,
        timeframe: Timeframe = Timeframe.M1,
    ) -> BidAskBarSeries | None:
        """Import CSV with mid-price OHLC. Sets ask=bid (zero spread)."""
        rows: list[dict[str, float]] = []
        timestamps: list[np.datetime64] = []

        with open(path, newline="", encoding="utf-8-sig") as f:
            sample = f.read(1024)
            f.seek(0)
            delimiter = "\t" if "\t" in sample else ","
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                date_str = row.get("Date", row.get("<DATE>", ""))
                time_str = row.get("Time", row.get("<TIME>", ""))
                ts_str = f"{date_str} {time_str}".strip()
                for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(ts_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                timestamps.append(np.datetime64(dt))
                o = float(row.get("Open", row.get("<OPEN>", 0)))
                h = float(row.get("High", row.get("<HIGH>", 0)))
                lo = float(row.get("Low", row.get("<LOW>", 0)))
                c = float(row.get("Close", row.get("<CLOSE>", 0)))
                v = float(row.get("Volume", row.get("<TICKVOL>", 0)))
                rows.append({"o": o, "h": h, "l": lo, "c": c, "v": v})

        if not rows:
            return None

        ts_arr = np.array(timestamps, dtype="datetime64[ns]")
        o_arr = np.array([r["o"] for r in rows], dtype=np.float64)
        h_arr = np.array([r["h"] for r in rows], dtype=np.float64)
        l_arr = np.array([r["l"] for r in rows], dtype=np.float64)
        c_arr = np.array([r["c"] for r in rows], dtype=np.float64)
        v_arr = np.array([r["v"] for r in rows], dtype=np.float64)

        return BidAskBarSeries(
            pair=pair, timeframe=timeframe, timestamps=ts_arr,
            bid_open=o_arr, bid_high=h_arr, bid_low=l_arr, bid_close=c_arr,
            ask_open=o_arr.copy(), ask_high=h_arr.copy(),
            ask_low=l_arr.copy(), ask_close=c_arr.copy(),
            volume=v_arr,
        )

    def download(
        self, pair: TradingPair, start: datetime, end: datetime,
        resolution: str = "M1",
    ) -> DownloadResult:
        return DownloadResult(
            pair=pair, resolution=resolution, start=start, end=end, rows=0,
            provider=self.provider_name, has_bid_ask=False,
            errors=["MT5 requires manual CSV export. Use import_csv() instead."],
        )


def cross_validate_providers(
    series_a: BidAskBarSeries,
    series_b: BidAskBarSeries,
    provider_a: str,
    provider_b: str,
) -> dict[str, Any]:
    """Compare two data sources for overlapping periods."""
    ts_a = set(series_a.timestamps.astype("datetime64[s]"))
    ts_b = set(series_b.timestamps.astype("datetime64[s]"))
    common = ts_a & ts_b

    result: dict[str, Any] = {
        "provider_a": provider_a,
        "provider_b": provider_b,
        "pair": series_a.pair.value,
        "bars_a": len(series_a),
        "bars_b": len(series_b),
        "common_timestamps": len(common),
        "only_in_a": len(ts_a - ts_b),
        "only_in_b": len(ts_b - ts_a),
    }

    if len(common) < 2:
        result["note"] = "Insufficient overlap for comparison"
        return result

    common_sorted = sorted(common)
    idx_a = {ts: i for i, ts in enumerate(series_a.timestamps.astype("datetime64[s]"))}
    idx_b = {ts: i for i, ts in enumerate(series_b.timestamps.astype("datetime64[s]"))}

    mid_a = np.array([
        (float(series_a.bid_close[idx_a[ts]]) + float(series_a.ask_close[idx_a[ts]])) / 2
        for ts in common_sorted
    ])
    mid_b = np.array([
        (float(series_b.bid_close[idx_b[ts]]) + float(series_b.ask_close[idx_b[ts]])) / 2
        for ts in common_sorted
    ])

    price_diff = np.abs(mid_a - mid_b)
    result["median_abs_price_diff"] = float(np.median(price_diff))

    if len(mid_a) > 1:
        ret_a = np.diff(mid_a) / mid_a[:-1]
        ret_b = np.diff(mid_b) / mid_b[:-1]
        if np.std(ret_a) > 0 and np.std(ret_b) > 0:
            result["return_correlation"] = float(np.corrcoef(ret_a, ret_b)[0, 1])

    return result
