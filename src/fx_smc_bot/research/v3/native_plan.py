"""Native-transport acquisition plan (request counts derived from the calendar).

Rebuilds the bulk plan around native per-day M1 candle files instead of hourly ticks. Weekends
are deterministically classified as non-market by the calendar rule (not from provider
silence); each trading weekday needs one BID and one ASK native file. This replaces the old
~649k tick-request estimate as the primary plan when the native transport is certified.

Pre-2018 only. The unit iterator is firewall-safe by construction (it never emits a 2018+
date), and callers must still firewall every generated URL before I/O.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition_state import is_weekend
from fx_smc_bot.research.v3.capabilities import INSTRUMENTS

PLAN_START = date(2010, 1, 1)
PLAN_END = date(2017, 12, 31)  # strictly pre-2018
HOURS_PER_TRADING_DAY = 24     # tick-path equivalence for the comparison estimate


def trading_days(start: date = PLAN_START, end: date = PLAN_END) -> Iterator[date]:
    d = start
    one = timedelta(days=1)
    while d <= end:
        if not is_weekend(d):
            yield d
        d += one


def iter_units() -> Iterator[tuple[str, date]]:
    """Every (instrument, trading-day) acquisition unit in the pre-2018 plan."""

    instruments = [i.symbol for i in INSTRUMENTS]
    for inst in instruments:
        for d in trading_days():
            yield inst, d


def plan_counts() -> dict[str, int]:
    n_instruments = len(INSTRUMENTS)
    n_trading_days = sum(1 for _ in trading_days())
    day_units = n_instruments * n_trading_days
    native_requests = day_units * 2           # BID + ASK per day
    tick_requests_equivalent = day_units * HOURS_PER_TRADING_DAY  # old primary estimate
    return {
        "instruments": n_instruments,
        "trading_days_per_instrument": n_trading_days,
        "day_units": day_units,
        "native_requests_planned": native_requests,
        "tick_requests_equivalent": tick_requests_equivalent,
        "monthly_canonical_partitions": n_instruments * 8 * 12 * 2,  # instr x yr x mo x side
    }


def native_plan_payload() -> dict[str, Any]:
    counts = plan_counts()
    reduction = round(
        counts["tick_requests_equivalent"] / max(1, counts["native_requests_planned"]), 1
    )
    return {
        "artifact_id": "V3_NATIVE_ACQUISITION_PLAN_V1",
        "region": "pre_2018_only",
        "plan_start": PLAN_START.isoformat(),
        "plan_end": PLAN_END.isoformat(),
        "weekend_rule": "deterministic calendar exclusion (Sat/Sun); never inferred from "
                        "provider silence.",
        "granularity": {"acquisition_unit": "instrument_x_trading_day",
                        "files_per_unit": 2, "canonical_storage": "instrument/year/month"},
        **counts,
        "request_reduction_vs_tick": f"{reduction}x fewer requests than the tick path",
        "old_primary_estimate_tick_requests": counts["tick_requests_equivalent"],
        "new_primary_estimate_native_requests": counts["native_requests_planned"],
    }


def native_plan_hash() -> str:
    return canonical_hash(native_plan_payload())
