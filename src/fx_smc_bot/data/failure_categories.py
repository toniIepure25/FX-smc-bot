"""Explicit failure categories for data acquisition.

Each failure is classified into a normalized category that determines
retry eligibility. Weekend/holiday emptiness is NOT a failure.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from fx_smc_bot.data.market_calendar import ANNUAL_HOLIDAYS


class FailureCategory(str, Enum):
    MARKET_CLOSED_WEEKEND = "MARKET_CLOSED_WEEKEND"
    MARKET_CLOSED_HOLIDAY = "MARKET_CLOSED_HOLIDAY"
    NO_PROVIDER_DATA = "NO_PROVIDER_DATA"
    TRANSIENT_NETWORK_ERROR = "TRANSIENT_NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    NODE_PROCESS_ERROR = "NODE_PROCESS_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    CHECKSUM_FAILURE = "CHECKSUM_FAILURE"
    PARTIAL_OUTPUT = "PARTIAL_OUTPUT"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


RETRYABLE_CATEGORIES = {
    FailureCategory.TRANSIENT_NETWORK_ERROR,
    FailureCategory.RATE_LIMITED,
    FailureCategory.TIMEOUT,
    FailureCategory.PARTIAL_OUTPUT,
}

NON_RETRYABLE_CATEGORIES = {
    FailureCategory.MARKET_CLOSED_WEEKEND,
    FailureCategory.MARKET_CLOSED_HOLIDAY,
    FailureCategory.NO_PROVIDER_DATA,
    FailureCategory.NODE_PROCESS_ERROR,
    FailureCategory.PARSER_ERROR,
    FailureCategory.CHECKSUM_FAILURE,
    FailureCategory.UNKNOWN_ERROR,
}


def is_weekend(year: int, month: int, day: int) -> bool:
    d = date(year, month, day)
    return d.weekday() >= 5


def is_holiday(month: int, day: int) -> bool:
    return (month, day) in ANNUAL_HOLIDAYS


def classify_failure(
    error_str: str,
    year: int,
    month: int,
    day: int,
    rows_returned: int = 0,
) -> FailureCategory:
    """Classify an acquisition failure into a normalized category."""
    if rows_returned == 0 and not error_str:
        if is_weekend(year, month, day):
            return FailureCategory.MARKET_CLOSED_WEEKEND
        if is_holiday(month, day):
            return FailureCategory.MARKET_CLOSED_HOLIDAY
        return FailureCategory.NO_PROVIDER_DATA

    err = error_str.lower()

    if "timeout" in err:
        return FailureCategory.TIMEOUT
    if "fetch failed" in err or "econnreset" in err or "enotfound" in err:
        return FailureCategory.TRANSIENT_NETWORK_ERROR
    if "rate limit" in err or "429" in err or "too many" in err:
        return FailureCategory.RATE_LIMITED
    if "json" in err and ("parse" in err or "syntax" in err):
        return FailureCategory.PARSER_ERROR
    if "checksum" in err or "corrupt" in err:
        return FailureCategory.CHECKSUM_FAILURE
    if "partial" in err or "incomplete" in err:
        return FailureCategory.PARTIAL_OUTPUT
    if "exit code" in err or "spawn" in err or "node" in err:
        return FailureCategory.NODE_PROCESS_ERROR

    return FailureCategory.UNKNOWN_ERROR


def is_retryable(category: FailureCategory) -> bool:
    return category in RETRYABLE_CATEGORIES
