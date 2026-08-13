"""Pre-2018 data-acquisition plan and firewalled, resumable downloader.

This module plans (and provides the safe machinery to execute) the reconstruction of the
expanded pre-2018 M1 bid/ask universe. It never acquires 2018+ data: every request passes
through the network firewall's date guard *before* any I/O, so a holdout request fails
before a byte is consumed. The downloader is transport-agnostic (an injected ``fetch_fn``
does the actual byte transfer), which lets the firewall + resume + checksum logic be tested
without touching the network, and lets bulk acquisition be deferred to the discovery-run
session without changing the frozen plan.

Estimates use explicit, transparent per-unit constants (stated in the payload) rather than
opaque precomputed totals, so they can be audited and adjusted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import CANONICAL_GRANULARITY, INSTRUMENTS
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall

# --- transparent estimate constants ---
TRADING_DAYS_PER_YEAR = 260
M1_BARS_PER_DAY = 1440
CANONICAL_BYTES_PER_M1_BAR = 20  # bid+ask OHLC, columnar parquet, compressed
SOURCE_TO_CANONICAL_RATIO = 3.0  # raw provider payload is ~3x canonical parquet on disk
FILES_PER_INSTRUMENT_YEAR = 24  # 12 months x {bid, ask}
SECONDS_PER_INSTRUMENT_YEAR = 45.0  # rate-limited fetch+parse+checksum, conservative
DISK_RESERVE_GB = 20.0

# Pre-2018 development years only; 2018+ is sealed and firewall-blocked.
PLAN_YEARS: tuple[int, ...] = (2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017)


@dataclass(frozen=True, slots=True)
class AcquisitionUnit:
    instrument: str
    year: int
    data_type: str
    files: int
    m1_bars_est: int
    canonical_bytes_est: int
    source_bytes_est: int
    runtime_seconds_est: float


def _units() -> list[AcquisitionUnit]:
    units: list[AcquisitionUnit] = []
    bars = TRADING_DAYS_PER_YEAR * M1_BARS_PER_DAY
    canonical = bars * CANONICAL_BYTES_PER_M1_BAR
    source = int(canonical * SOURCE_TO_CANONICAL_RATIO)
    for inst in INSTRUMENTS:
        for year in PLAN_YEARS:
            units.append(
                AcquisitionUnit(
                    instrument=inst.symbol, year=year, data_type=CANONICAL_GRANULARITY,
                    files=FILES_PER_INSTRUMENT_YEAR, m1_bars_est=bars,
                    canonical_bytes_est=canonical, source_bytes_est=source,
                    runtime_seconds_est=SECONDS_PER_INSTRUMENT_YEAR,
                )
            )
    return units


def acquisition_plan_payload() -> dict[str, Any]:
    units = _units()
    n = len(units)
    canonical_bytes = sum(u.canonical_bytes_est for u in units)
    source_bytes = sum(u.source_bytes_est for u in units)
    files = sum(u.files for u in units)
    runtime_s = sum(u.runtime_seconds_est for u in units)
    return {
        "artifact_id": "V3_ACQUISITION_PLAN_V1",
        "region": "pre_2018_development_only",
        "plan_years": list(PLAN_YEARS),
        "instrument_count": len(INSTRUMENTS),
        "granularity": CANONICAL_GRANULARITY,
        "tick_data": "NOT_IN_THIS_PLAN; if later acquired, restricted to a named "
                     "high-liquidity subset with a separate storage estimate; M1 is never "
                     "represented as tick data.",
        "estimate_constants": {
            "trading_days_per_year": TRADING_DAYS_PER_YEAR,
            "m1_bars_per_day": M1_BARS_PER_DAY,
            "canonical_bytes_per_m1_bar": CANONICAL_BYTES_PER_M1_BAR,
            "source_to_canonical_ratio": SOURCE_TO_CANONICAL_RATIO,
            "files_per_instrument_year": FILES_PER_INSTRUMENT_YEAR,
            "seconds_per_instrument_year": SECONDS_PER_INSTRUMENT_YEAR,
        },
        "totals": {
            "instrument_years": n,
            "files": files,
            "requests": files,
            "m1_bars_est": sum(u.m1_bars_est for u in units),
            "canonical_bytes_est": canonical_bytes,
            "canonical_gib_est": round(canonical_bytes / 2**30, 2),
            "source_bytes_est": source_bytes,
            "source_gib_est": round(source_bytes / 2**30, 2),
            "runtime_seconds_est": runtime_s,
            "runtime_hours_est": round(runtime_s / 3600, 2),
            "disk_reserve_gib": DISK_RESERVE_GB,
        },
        "acquisition_properties": [
            "resumable", "checksummed", "immutable", "partitioned_by_instrument_year",
            "rate_limit_aware", "bounded", "interruption_safe", "firewalled_pre_2018_only",
        ],
        "units": [
            {"instrument": u.instrument, "year": u.year, "files": u.files,
             "canonical_bytes_est": u.canonical_bytes_est}
            for u in units
        ],
    }


def acquisition_plan_hash() -> str:
    # Hash the structural plan (units + constants), not the volatile totals, so the frozen
    # identity is the plan itself.
    payload = acquisition_plan_payload()
    return canonical_hash(
        {"units": payload["units"], "constants": payload["estimate_constants"],
         "years": payload["plan_years"]}
    )


FetchFn = Callable[[str], bytes]


@dataclass(slots=True)
class DownloadResult:
    url: str
    instrument: str
    year: int
    bytes: int
    sha256: str
    resumed: bool


class FirewalledDownloader:
    """Resumable, checksummed downloader that firewalls every request before any I/O."""

    def __init__(self, firewall: V3HoldoutFirewall, fetch_fn: FetchFn) -> None:
        self._fw = firewall
        self._fetch = fetch_fn
        self._done: dict[str, str] = {}  # url -> sha256 (resume ledger)

    def fetch(self, url: str, instrument: str, day: date) -> DownloadResult:
        # 1. firewall FIRST: both the URL and the explicit date must clear before any I/O.
        self._fw.guard_url(url)
        self._fw.guard_date(day, context=f"{instrument} acquisition")
        # 2. resume: skip already-completed, checksum-verified units.
        if url in self._done:
            return DownloadResult(url, instrument, day.year, 0, self._done[url], resumed=True)
        # 3. only now transfer bytes.
        payload = self._fetch(url)
        digest = hashlib.sha256(payload).hexdigest()
        self._done[url] = digest
        return DownloadResult(url, instrument, day.year, len(payload), digest, resumed=False)

    def completed_count(self) -> int:
        return len(self._done)
