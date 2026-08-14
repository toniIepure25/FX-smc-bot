"""Expanded V3 data-capability contract for the pre-2018 development universe.

V2 was constrained to three USD majors because only those were ever materialised. V3
prospectively expands the *capability envelope* to a liquidity-justified 13-pair universe,
but never confuses "capability declared" with "data acquired". Each instrument carries an
explicit acquisition status:

* ``EXPOSED_RECONSTRUCTABLE`` -- EURUSD/GBPUSD/USDJPY 2015-2017, already outcome-exposed in
  V2 and byte-reconstructable from the provider (secondary robustness data for V3);
* ``PLANNED_PENDING_ACQUISITION`` -- the ten added pairs, whose pre-2018 M1 bid/ask must be
  reconstructed before any family that needs them can be admitted.

A family whose required instruments are not yet acquired compiles to
``REJECTED_PRE_OUTCOME`` (unsupported data dependency), so the admitted set never claims
data it does not hold. Tick/quote-arrival and order-book capabilities remain UNSUPPORTED
and are never faked from M1 (``M1 bar count != quote update count``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash


class AcquisitionStatus(str, Enum):
    EXPOSED_RECONSTRUCTABLE = "exposed_reconstructable"
    PLANNED_PENDING_ACQUISITION = "planned_pending_acquisition"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    base: str
    quote: str
    role: str  # "usd_major" | "cross"
    liquidity_tier: int  # 1 = deepest
    acquisition_status: AcquisitionStatus
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "base": self.base,
            "quote": self.quote,
            "role": self.role,
            "liquidity_tier": self.liquidity_tier,
            "acquisition_status": self.acquisition_status.value,
            "rationale": self.rationale,
        }


CANONICAL_GRANULARITY = "M1_BIDASK_OHLC"
DEVELOPMENT_YEARS: tuple[int, ...] = (2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017)
SEALED_HOLDOUT_YEARS: tuple[int, ...] = (2018, 2019)

# V2-exposed majors: reconstructable, usable as secondary robustness/engineering data.
_EXPOSED = AcquisitionStatus.EXPOSED_RECONSTRUCTABLE
_PLANNED = AcquisitionStatus.PLANNED_PENDING_ACQUISITION

INSTRUMENTS: tuple[Instrument, ...] = (
    # --- USD majors ---
    Instrument("EURUSD", "EUR", "USD", "usd_major", 1, _EXPOSED,
               "Deepest FX pair; V2-exposed. Anchors the USD/EUR factor."),
    Instrument("GBPUSD", "GBP", "USD", "usd_major", 1, _EXPOSED,
               "Deep major; V2-exposed. GBP leg of the USD factor."),
    Instrument("USDJPY", "USD", "JPY", "usd_major", 1, _EXPOSED,
               "Deep major; V2-exposed. USD/JPY factor anchor and risk proxy."),
    Instrument("AUDUSD", "AUD", "USD", "usd_major", 2, _PLANNED,
               "Commodity/risk-on major; adds AUD leg for currency-factor identification."),
    Instrument("NZDUSD", "NZD", "USD", "usd_major", 2, _PLANNED,
               "Correlated risk-on major; NZD leg and AUDNZD-style relative structure."),
    Instrument("USDCAD", "USD", "CAD", "usd_major", 2, _PLANNED,
               "Oil-sensitive major; CAD leg of the USD factor."),
    Instrument("USDCHF", "USD", "CHF", "usd_major", 2, _PLANNED,
               "Safe-haven major; CHF leg, strong EURCHF/USDCHF triangular structure."),
    # --- crosses (justified by cross-sectional / triangular structure, not quantity) ---
    Instrument("EURJPY", "EUR", "JPY", "cross", 2, _PLANNED,
               "Risk-barometer cross; EUR-USD-JPY triangle with EURUSD/USDJPY."),
    Instrument("GBPJPY", "GBP", "JPY", "cross", 3, _PLANNED,
               "High-vol cross; GBP-USD-JPY triangle, momentum/vol structure."),
    Instrument("AUDJPY", "AUD", "JPY", "cross", 3, _PLANNED,
               "Canonical risk-on/off carry cross; AUD-USD-JPY triangle."),
    Instrument("EURGBP", "EUR", "GBP", "cross", 2, _PLANNED,
               "European relative-value cross; EUR-USD-GBP triangle, mean-reverting."),
    Instrument("EURCHF", "EUR", "CHF", "cross", 3, _PLANNED,
               "Low-vol regime-sensitive cross; EUR-USD-CHF triangle (2015 SNB break noted)."),
    Instrument("GBPCHF", "GBP", "CHF", "cross", 3, _PLANNED,
               "Cross completing GBP/CHF structure; GBP-USD-CHF triangle."),
)

INSTRUMENT_INDEX: dict[str, Instrument] = {i.symbol: i for i in INSTRUMENTS}
CURRENCIES: tuple[str, ...] = tuple(
    sorted({i.base for i in INSTRUMENTS} | {i.quote for i in INSTRUMENTS})
)


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    supported: bool
    granularity: str
    required_fields: tuple[str, ...]
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.key,
            "supported": self.supported,
            "required_granularity": self.granularity,
            "required_fields": list(self.required_fields),
            "rationale": self.rationale,
        }


_CAPABILITIES: tuple[Capability, ...] = (
    Capability("M1_BIDASK_OHLC", True, "M1",
               ("bid_open", "bid_high", "bid_low", "bid_close",
                "ask_open", "ask_high", "ask_low", "ask_close"),
               "Dukascopy M1 bid/ask OHLC; the canonical acquired granularity."),
    Capability("MID_OHLC", True, "M1", ("mid_close",),
               "Deterministic (bid+ask)/2 mid; causal at bar close."),
    Capability("M1_SPREAD", True, "M1", ("ask_close", "bid_close"),
               "Per-bar quoted spread = ask_close - bid_close."),
    Capability("M1_RETURNS", True, "M1", ("mid_close",),
               "Log/percent returns of the derived mid; causal at bar close."),
    Capability("M1_REALIZED_VOL", True, "M1", ("mid_close",),
               "Rolling realized-vol proxy from M1 mid returns."),
    Capability("RANGE_ESTIMATORS_M1", True, "M1", ("mid_high", "mid_low", "mid_close"),
               "Parkinson/Garman-Klass/Rogers-Satchell/ATR from OHLC; exact definitions."),
    Capability("SESSION_TIME_OF_DAY", True, "M1", ("timestamp",),
               "America/New_York wall-clock from UTC bar timestamp (DST-correct)."),
    Capability("CALENDAR_CELLS", True, "M1", ("timestamp",),
               "Day-of-week, week-of-month, month/quarter-end flags from timestamp."),
    Capability("MULTI_TF_DERIVED", True, "M5/M15/H1", ("mid_close",),
               "Deterministic higher-TF bars resampled from canonical M1; label-preserving."),
    Capability("CROSS_PAIR_SYNC", True, "M1", ("timestamp", "mid_close"),
               "All acquired pairs share the M1 UTC grid; synchronized causal joins."),
    Capability("CURRENCY_FACTOR_PANEL", True, "M1", ("multi_currency_panel",),
               "With >=7 pairs spanning USD/EUR/GBP/JPY/AUD/NZD/CAD/CHF, dollar and "
               "single-currency factors are identifiable (pending acquisition)."),
    Capability("TRIANGULAR_RESIDUAL", True, "M1", ("EURUSD", "USDJPY", "EURJPY"),
               "Genuine triangle residuals exist only when all three legs are acquired "
               "independently; never synthesised (that forces the residual to zero)."),
    # --- explicitly UNSUPPORTED (never faked) ---
    Capability("TICK_QUOTE_ARRIVAL_RATE", False, "TICK", ("quote_arrival_count",),
               "M1 volume is a tick-volume proxy, not a quote count; unsupported unless "
               "true tick data are separately acquired for a named instrument subset."),
    Capability("TICK_LEVEL_MICROSTRUCTURE", False, "TICK", ("tick_price", "tick_time"),
               "Sub-M1 tick prices/times not in the M1 dataset; faking them is forbidden."),
    Capability("ORDER_BOOK_DEPTH", False, "L2", ("bid_sizes", "ask_sizes"),
               "No depth in Dukascopy M1/tick; unsupported."),
    Capability("OVERNIGHT_FINANCING_RATES", False, "DAILY", ("swap_long", "swap_short"),
               "Historically-realistic broker swap/financing with defensible provenance is "
               "NOT reconstructable from price data; multi-day P&L cannot be net-executable "
               "and such strategies are PRICE_ALPHA_RESEARCH_ONLY_NOT_FULLY_EXECUTABLE."),
)

CAPABILITY_INDEX: dict[str, Capability] = {c.key: c for c in _CAPABILITIES}


def is_supported(key: str) -> bool:
    cap = CAPABILITY_INDEX.get(key)
    return bool(cap and cap.supported)


def check_required(required: tuple[str, ...]) -> tuple[bool, list[str]]:
    """Return ``(ok, missing)`` where ``missing`` lists unknown/unsupported keys."""

    missing = [k for k in required if not is_supported(k)]
    return (not missing, missing)


def instruments_acquired() -> tuple[str, ...]:
    """Instruments whose pre-2018 data is currently reconstructable/available."""

    return tuple(
        i.symbol for i in INSTRUMENTS
        if i.acquisition_status is AcquisitionStatus.EXPOSED_RECONSTRUCTABLE
    )


def instruments_planned() -> tuple[str, ...]:
    return tuple(
        i.symbol for i in INSTRUMENTS
        if i.acquisition_status is AcquisitionStatus.PLANNED_PENDING_ACQUISITION
    )


def capability_matrix_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_DATA_CAPABILITY_MATRIX_V1",
        "canonical_granularity": CANONICAL_GRANULARITY,
        "development_years": list(DEVELOPMENT_YEARS),
        "sealed_holdout_years": list(SEALED_HOLDOUT_YEARS),
        "currencies": list(CURRENCIES),
        "instrument_count": len(INSTRUMENTS),
        "instruments": [i.as_dict() for i in INSTRUMENTS],
        "instruments_acquired": list(instruments_acquired()),
        "instruments_planned": list(instruments_planned()),
        "never_uses_volume_as_alpha_feature": True,
        "native_volume_use": {
            "as_alpha_feature": "FORBIDDEN",
            "as_quote_presence_provenance": "PERMITTED; certified rule volume>0 <=> observed "
                                            "minute (1680/1680 vs tick reference).",
            "enables_tick_arrival_rate_capability": False,
        },
        "hard_rule": "M1 bar count != quote update count; tick semantics never faked from M1; "
                     "native volume is quote-presence provenance only, never an alpha feature.",
        "capabilities": [c.as_dict() for c in _CAPABILITIES],
        "supported_capability_count": sum(1 for c in _CAPABILITIES if c.supported),
        "unsupported_capability_count": sum(1 for c in _CAPABILITIES if not c.supported),
    }


def capability_hash() -> str:
    return canonical_hash(capability_matrix_payload())
