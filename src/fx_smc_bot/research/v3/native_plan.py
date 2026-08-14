"""Native-transport acquisition plan (request counts derived from the FX calendar contract).

Rebuilds the bulk plan around native per-day M1 candle files instead of hourly ticks, using
the corrected FX weekly-session calendar (Sunday 17:00 ET reopen ... Friday 17:00 ET close;
only Saturday fully closed). Each trading UTC date needs one BID and one ASK native file. This
replaces the old ~649k tick-request estimate as the primary plan when the native transport is
certified.

Pre-2018 only. The unit iterator is firewall-safe by construction (it never emits a 2018+
date), and callers must still firewall every generated URL before I/O.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import INSTRUMENTS
from fx_smc_bot.research.v3.fx_calendar import (
    classify_session,
    expected_minutes,
    fx_calendar_hash,
)
from fx_smc_bot.research.v3.fx_calendar import trading_dates as _trading_dates

PLAN_START = date(2010, 1, 1)
PLAN_END = date(2017, 12, 31)  # strictly pre-2018
HOURS_PER_TRADING_DAY = 24     # tick-path equivalence for the comparison estimate


def trading_days(start: date = PLAN_START, end: date = PLAN_END) -> Iterator[date]:
    yield from _trading_dates(start, end)


def iter_units() -> Iterator[tuple[str, date]]:
    """Every (instrument, trading-day) acquisition unit in the pre-2018 plan."""

    instruments = [i.symbol for i in INSTRUMENTS]
    for inst in instruments:
        for d in trading_days():
            yield inst, d


def session_class_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in trading_days():
        cls = classify_session(d)
        counts[cls] = counts.get(cls, 0) + 1
    return counts


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
    session_counts = session_class_counts()
    # session-aware expected M1 minutes per instrument (metadata; not enforced)
    expected_min_per_instrument = sum(expected_minutes(d) for d in trading_days())
    return {
        "artifact_id": "V3_NATIVE_ACQUISITION_PLAN_V1",
        "region": "pre_2018_only",
        "plan_start": PLAN_START.isoformat(),
        "plan_end": PLAN_END.isoformat(),
        "fx_calendar_contract_hash": fx_calendar_hash(),
        "calendar_rule": "FX weekly session (America/New_York): Sunday 17:00 ET reopen ... "
                         "Friday 17:00 ET close; only Saturday fully closed. Sunday/Friday "
                         "partial sessions are trading dates; never inferred from silence.",
        "session_class_counts_per_instrument": session_counts,
        "expected_m1_minutes_per_instrument": expected_min_per_instrument,
        "granularity": {"acquisition_unit": "instrument_x_trading_utc_date",
                        "files_per_unit": 2, "canonical_storage": "instrument/year/month"},
        **counts,
        "request_reduction_vs_tick": f"{reduction}x fewer requests than the tick path",
        "old_primary_estimate_tick_requests": counts["tick_requests_equivalent"],
        "new_primary_estimate_native_requests": counts["native_requests_planned"],
    }


def native_plan_hash() -> str:
    return canonical_hash(native_plan_payload())
