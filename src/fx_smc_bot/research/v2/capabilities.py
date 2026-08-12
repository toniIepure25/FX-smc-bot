"""Data capability contract for FX_INTRADAY_ALPHA_DISCOVERY_V2.

The V2 search space may only admit strategies whose every required input is *guaranteed*
by the frozen dataset actually on disk. The frozen dataset is:

* Instruments actually acquired: EURUSD, GBPUSD, USDJPY (three USD majors only).
* Granularity actually acquired: Dukascopy M1 bid/ask OHLCV bars.
* Development region (already legally inspected pre-outcome): 2015-2017.
* Holdout region (never opened during readiness): 2018-2019.

The V1 program *planned* nine instruments across 2010-2025 (see
``configs/research/fx_intraday_alpha_search_v1.yaml``) but only the three USD majors
across 2015-2019 were ever materialised. That gap -- not a coding bug -- is the true
root cause of most V1 "semantic blockers": families requiring JPY crosses, AUD pairs,
or tick-level quote arrival semantics were frozen at the idea level against data that
was never acquired.

Hard rule (never violated anywhere in V2):
    ``M1 bar count != quote update count``. The Dukascopy ``volume`` field is a
    tick-volume proxy, not a reliable quote-arrival count, and is therefore treated as
    UNSUPPORTED for any quote-rate / liquidity-microstructure semantics. V2 never reads
    the ``volume`` field for signal construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_INSTRUMENTS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY")
DEVELOPMENT_YEARS: tuple[int, ...] = (2015, 2016, 2017)
HOLDOUT_YEARS: tuple[int, ...] = (2018, 2019)
CANONICAL_GRANULARITY = "M1_BIDASK_OHLC"


@dataclass(frozen=True, slots=True)
class Capability:
    """One row of the capability matrix."""

    key: str
    supported: bool
    granularity: str
    fields: tuple[str, ...]
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.key,
            "supported": self.supported,
            "required_granularity": self.granularity,
            "required_fields": list(self.fields),
            "rationale": self.rationale,
        }


# The authoritative capability matrix. Keys are referenced by feature/model specs.
_CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "M1_BIDASK_OHLC",
        True,
        "M1",
        ("bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low",
         "ask_close"),
        "Directly acquired Dukascopy M1 bid and ask OHLC bars for the three USD majors.",
    ),
    Capability(
        "MID_OHLC",
        True,
        "M1",
        ("mid_open", "mid_high", "mid_low", "mid_close"),
        "Deterministically derived as (bid + ask) / 2 from acquired bid/ask OHLC.",
    ),
    Capability(
        "M1_SPREAD",
        True,
        "M1",
        ("ask_close", "bid_close"),
        "Per-bar quoted spread = ask_close - bid_close from acquired bid/ask bars.",
    ),
    Capability(
        "M1_RETURNS",
        True,
        "M1",
        ("mid_close",),
        "Log/percent returns of the derived mid close; fully causal at bar close.",
    ),
    Capability(
        "M1_REALIZED_VOL",
        True,
        "M1",
        ("mid_close",),
        "Rolling standard deviation of M1 mid returns; a realised-vol proxy at M1 scale.",
    ),
    Capability(
        "WILDER_ATR_M1",
        True,
        "M1",
        ("mid_high", "mid_low", "mid_close"),
        "Wilder ATR computed from mid true range; exact recursive definition.",
    ),
    Capability(
        "ROLLING_RANGE_M1",
        True,
        "M1",
        ("mid_high", "mid_low"),
        "Rolling high-low range and range-compression ratios from mid bars.",
    ),
    Capability(
        "SESSION_TIME_OF_DAY",
        True,
        "M1",
        ("timestamp",),
        "America/New_York wall-clock hour/minute derived from the UTC bar timestamp.",
    ),
    Capability(
        "CALENDAR_CELLS",
        True,
        "M1",
        ("timestamp",),
        "Day-of-week, month-end and quarter-end flags from the UTC bar timestamp.",
    ),
    Capability(
        "M5_DERIVED",
        True,
        "M5",
        ("mid_close",),
        "Deterministic M5 bars resampled from canonical M1; label-preserving.",
    ),
    Capability(
        "CROSS_PAIR_SYNC_3_MAJORS",
        True,
        "M1",
        ("timestamp", "mid_close"),
        "EURUSD/GBPUSD/USDJPY share the M1 grid and can be timestamp-joined.",
    ),
    # --- Explicitly UNSUPPORTED capabilities (never faked) ---
    Capability(
        "TICK_QUOTE_ARRIVAL_RATE",
        False,
        "TICK",
        ("quote_arrival_count",),
        "M1 bars carry no reliable per-quote arrival count; volume is a tick-volume "
        "proxy, not a quote count. Never reconstructed from M1.",
    ),
    Capability(
        "TICK_LEVEL_MICROSTRUCTURE",
        False,
        "TICK",
        ("tick_price", "tick_time"),
        "Sub-M1 tick prices/times were not acquired for the frozen dataset.",
    ),
    Capability(
        "ORDER_BOOK_DEPTH",
        False,
        "L2",
        ("bid_sizes", "ask_sizes"),
        "No order-book depth exists in the acquired Dukascopy dataset.",
    ),
    Capability(
        "JPY_CROSS_INSTRUMENTS",
        False,
        "M1",
        ("EURJPY", "GBPJPY", "AUDJPY"),
        "JPY cross instruments were never acquired; only USD majors exist.",
    ),
    Capability(
        "AUD_AND_OTHER_MAJORS",
        False,
        "M1",
        ("AUDUSD", "USDCAD", "USDCHF"),
        "These majors were planned in V1 but never materialised.",
    ),
    Capability(
        "CURRENCY_FACTOR_CROSS_SECTION",
        False,
        "M1",
        ("multi_currency_panel",),
        "Three USD pairs cannot identify robust EUR/GBP/JPY/AUD dollar factors.",
    ),
    Capability(
        "TRIANGULAR_CROSS_RATE",
        False,
        "M1",
        ("EURJPY", "GBPJPY", "AUDJPY"),
        "Cross rates were not acquired; synthesising them makes the triangular residual "
        "identically zero, so there is no observable inconsistency to trade.",
    ),
)

CAPABILITY_INDEX: dict[str, Capability] = {cap.key: cap for cap in _CAPABILITIES}


def is_supported(capability_key: str) -> bool:
    cap = CAPABILITY_INDEX.get(capability_key)
    return bool(cap and cap.supported)


def check_required(required: tuple[str, ...]) -> tuple[bool, list[str]]:
    """Return ``(ok, missing)`` for a tuple of required capability keys.

    ``missing`` lists required keys that are either unknown or explicitly unsupported.
    A strategy is admissible only when ``missing`` is empty.
    """

    missing: list[str] = []
    for key in required:
        if not is_supported(key):
            missing.append(key)
    return (not missing, missing)


def capability_matrix_payload() -> dict[str, Any]:
    """Machine-readable capability matrix for the gate artifact."""

    return {
        "artifact_id": "A0R4_DATA_CAPABILITY_MATRIX_V1",
        "canonical_granularity": CANONICAL_GRANULARITY,
        "supported_instruments": list(SUPPORTED_INSTRUMENTS),
        "development_years": list(DEVELOPMENT_YEARS),
        "holdout_years": list(HOLDOUT_YEARS),
        "never_uses_volume_field": True,
        "hard_rule": "M1 bar count != quote update count; tick semantics never faked from M1.",
        "capabilities": [cap.as_dict() for cap in _CAPABILITIES],
        "supported_capability_count": sum(1 for c in _CAPABILITIES if c.supported),
        "unsupported_capability_count": sum(1 for c in _CAPABILITIES if not c.supported),
    }
