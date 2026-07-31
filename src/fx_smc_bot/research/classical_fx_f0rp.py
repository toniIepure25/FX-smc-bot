"""Outcome-blind Gate F0-RP amendment overlay.

The original Gate F0 constants remain untouched. This module defines only the
prospective Route B universe that may be used after the amendment commit.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date
from typing import Final

from fx_smc_bot.research.classical_factor_safe_io import (
    FROZEN_CURRENCIES,
    FROZEN_INSTRUMENTS,
    MarketPartition,
    RatePartition,
)

AMENDMENT_ID: Final = "F0_RATE_PROVENANCE_AMENDMENT_V1"
NZD_RATE_REMEDIATION_ROUTE: Final = "OUTCOME_BLIND_NZD_EXCLUSION"
NZD_STATUS: Final = "EXCLUDED_BY_OUTCOME_BLIND_RATE_PROVENANCE_AMENDMENT"
NZDUSD_STATUS: Final = "EXCLUDED_FROM_PRIMARY_INSTRUMENT_UNIVERSE"

AMENDED_INSTRUMENT_ORDER: Final = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
AMENDED_CURRENCY_ORDER: Final = ("USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF")
AMENDED_INSTRUMENTS: Final = frozenset(AMENDED_INSTRUMENT_ORDER)
AMENDED_CURRENCIES: Final = frozenset(AMENDED_CURRENCY_ORDER)

DEVELOPMENT_START: Final = date(2010, 1, 1)
DEVELOPMENT_END: Final = date(2016, 12, 31)
DEVELOPMENT_YEARS: Final = tuple(range(2010, 2017))
MARKET_SIDES: Final = ("bid", "ask")
EXPECTED_DEVELOPMENT_MARKET_PARTITIONS: Final = 1_512
EXPECTED_DEVELOPMENT_PAIR_MONTHS: Final = 756
EXPECTED_DEVELOPMENT_RATE_PARTITIONS: Final = 49

AMENDED_RATE_SERIES: Final = {
    "USD": "EFFR",
    "EUR": "EONIA_TO_ESTR",
    "GBP": "IUDSOIA",
    "AUD": "RBA_CASH_RATE",
    "JPY": "FM01'STRDCLUCON",
    "CAD": "V39079",
    "CHF": "SRFXON3",
}

RATE_PROVIDER_IMPLEMENTATIONS_AVAILABLE: Final = False
EMPIRICAL_ORCHESTRATION_AVAILABLE: Final = False


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def development_market_partitions() -> tuple[MarketPartition, ...]:
    """Return the exact amended nine-instrument development plan."""
    partitions = tuple(
        MarketPartition(
            instrument=instrument,
            side=side,
            start=date(year, month, 1),
            end=_month_end(year, month),
        )
        for instrument in AMENDED_INSTRUMENT_ORDER
        for side in MARKET_SIDES
        for year in DEVELOPMENT_YEARS
        for month in range(1, 13)
    )
    if len(partitions) != EXPECTED_DEVELOPMENT_MARKET_PARTITIONS:
        raise RuntimeError("Gate F0-RP amended market partition count changed")
    if len(set(partitions)) != len(partitions):
        raise RuntimeError("Gate F0-RP amended market partitions are not unique")
    return partitions


def development_rate_partitions() -> tuple[RatePartition, ...]:
    """Return seven official-series annual partitions with no NZD request."""
    partitions = tuple(
        RatePartition(currency, date(year, 1, 1), date(year, 12, 31))
        for currency in AMENDED_CURRENCY_ORDER
        for year in DEVELOPMENT_YEARS
    )
    if len(partitions) != EXPECTED_DEVELOPMENT_RATE_PARTITIONS:
        raise RuntimeError("Gate F0-RP amended rate partition count changed")
    if len(set(partitions)) != len(partitions):
        raise RuntimeError("Gate F0-RP amended rate partitions are not unique")
    return partitions


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def amendment_overlay() -> dict[str, object]:
    """Expose the scientific delta without touching the original F0 freeze."""
    overlay: dict[str, object] = {
        "amendment_id": AMENDMENT_ID,
        "nzd_rate_remediation_route": NZD_RATE_REMEDIATION_ROUTE,
        "nzd_status": NZD_STATUS,
        "nzdusd_status": NZDUSD_STATUS,
        "instruments": list(AMENDED_INSTRUMENT_ORDER),
        "currencies": list(AMENDED_CURRENCY_ORDER),
        "rate_series": dict(AMENDED_RATE_SERIES),
        "factor_family_changed": False,
        "factor_risk_weights_changed": False,
        "portfolio_rules_changed": False,
        "selection_thresholds_changed": False,
        "temporal_partitions_changed": False,
    }
    overlay["overlay_sha256"] = canonical_sha256(overlay)
    return overlay


def development_market_plan() -> dict[str, object]:
    """Build a compact deterministic market plan without crossing an I/O boundary."""
    partitions = development_market_partitions()
    records = [
        {
            "partition_id": partition.partition_id,
            "instrument": partition.instrument,
            "side": partition.side,
            "start": partition.start.isoformat(),
            "end": partition.end.isoformat(),
        }
        for partition in partitions
    ]
    return {
        "stage": "F0RP_DEVELOPMENT_MARKET_PLAN",
        "interval": {
            "start": DEVELOPMENT_START.isoformat(),
            "end": DEVELOPMENT_END.isoformat(),
        },
        "instruments": list(AMENDED_INSTRUMENT_ORDER),
        "partition_count": len(records),
        "pair_month_count": EXPECTED_DEVELOPMENT_PAIR_MONTHS,
        "partition_plan_sha256": canonical_sha256(records),
        "provider_requests_sent": 0,
        "market_observations_accessed": False,
        "status": "FROZEN_DRY_RUN_PLAN",
    }


def development_rate_plan() -> dict[str, object]:
    """Build a compact deterministic rate plan without provider access."""
    partitions = development_rate_partitions()
    records = [
        {
            "partition_id": partition.partition_id,
            "currency": partition.currency,
            "series_identifier": AMENDED_RATE_SERIES[partition.currency],
            "start": partition.start.isoformat(),
            "end": partition.end.isoformat(),
        }
        for partition in partitions
    ]
    return {
        "stage": "F0RP_DEVELOPMENT_RATE_PLAN",
        "interval": {
            "start": DEVELOPMENT_START.isoformat(),
            "end": DEVELOPMENT_END.isoformat(),
        },
        "currencies": list(AMENDED_CURRENCY_ORDER),
        "partition_count": len(records),
        "partition_plan_sha256": canonical_sha256(records),
        "provider_requests_sent": 0,
        "rate_observations_accessed": False,
        "status": "FROZEN_DRY_RUN_PLAN",
    }


def execution_readiness() -> dict[str, object]:
    """Report the earliest honest execution boundary without probing providers."""
    return {
        "amendment_id": AMENDMENT_ID,
        "nzd_rate_remediation_route": NZD_RATE_REMEDIATION_ROUTE,
        "official_rate_provider_adapters_implemented": RATE_PROVIDER_IMPLEMENTATIONS_AVAILABLE,
        "end_to_end_empirical_orchestration_implemented": EMPIRICAL_ORCHESTRATION_AVAILABLE,
        "provider_requests_sent": 0,
        "market_observations_accessed": False,
        "rate_observations_accessed": False,
        "development_outcomes_generated": False,
        "status": "F0RP_RATE_PROVENANCE_RECONCILED_EMPIRICAL_EXECUTION_BLOCKED",
    }


if not AMENDED_INSTRUMENTS < FROZEN_INSTRUMENTS:
    raise RuntimeError("Gate F0-RP instrument amendment must be a strict F0 subset")
if not AMENDED_CURRENCIES < FROZEN_CURRENCIES:
    raise RuntimeError("Gate F0-RP currency amendment must be a strict F0 subset")
if "NZDUSD" in AMENDED_INSTRUMENTS or "NZD" in AMENDED_CURRENCIES:
    raise RuntimeError("Gate F0-RP Route B must exclude NZD and NZDUSD")
