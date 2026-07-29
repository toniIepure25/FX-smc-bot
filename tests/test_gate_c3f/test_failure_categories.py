"""Tests for explicit failure categories and retry logic."""
from __future__ import annotations

import pytest

from fx_smc_bot.data.failure_categories import (
    FailureCategory,
    classify_failure,
    is_retryable,
)


class TestFailureClassification:
    def test_weekend_is_market_closed(self) -> None:
        cat = classify_failure("", 2019, 1, 5, 0)  # Saturday
        assert cat == FailureCategory.MARKET_CLOSED_WEEKEND

    def test_sunday_is_market_closed(self) -> None:
        cat = classify_failure("", 2019, 1, 6, 0)
        assert cat == FailureCategory.MARKET_CLOSED_WEEKEND

    def test_holiday_is_market_closed(self) -> None:
        cat = classify_failure("", 2019, 12, 25, 0)
        assert cat == FailureCategory.MARKET_CLOSED_HOLIDAY

    def test_fetch_failed_is_transient(self) -> None:
        cat = classify_failure("fetch failed", 2019, 1, 7, 0)
        assert cat == FailureCategory.TRANSIENT_NETWORK_ERROR

    def test_timeout_classified(self) -> None:
        cat = classify_failure("timeout expired", 2019, 1, 7, 0)
        assert cat == FailureCategory.TIMEOUT

    def test_rate_limit_classified(self) -> None:
        cat = classify_failure("429 too many requests", 2019, 1, 7, 0)
        assert cat == FailureCategory.RATE_LIMITED

    def test_no_data_weekday(self) -> None:
        cat = classify_failure("", 2019, 1, 7, 0)  # Monday
        assert cat == FailureCategory.NO_PROVIDER_DATA

    def test_json_parse_error(self) -> None:
        cat = classify_failure("JSON parse syntax error", 2019, 1, 7, 0)
        assert cat == FailureCategory.PARSER_ERROR

    def test_node_exit_code(self) -> None:
        cat = classify_failure("exit code 1", 2019, 1, 7, 0)
        assert cat == FailureCategory.NODE_PROCESS_ERROR


class TestRetryability:
    def test_transient_is_retryable(self) -> None:
        assert is_retryable(FailureCategory.TRANSIENT_NETWORK_ERROR)

    def test_timeout_is_retryable(self) -> None:
        assert is_retryable(FailureCategory.TIMEOUT)

    def test_rate_limited_is_retryable(self) -> None:
        assert is_retryable(FailureCategory.RATE_LIMITED)

    def test_weekend_not_retryable(self) -> None:
        assert not is_retryable(FailureCategory.MARKET_CLOSED_WEEKEND)

    def test_holiday_not_retryable(self) -> None:
        assert not is_retryable(FailureCategory.MARKET_CLOSED_HOLIDAY)

    def test_parser_error_not_retryable(self) -> None:
        assert not is_retryable(FailureCategory.PARSER_ERROR)

    def test_all_categories_classified(self) -> None:
        """Every category is either retryable or non-retryable."""
        from fx_smc_bot.data.failure_categories import (
            NON_RETRYABLE_CATEGORIES,
            RETRYABLE_CATEGORIES,
        )
        for cat in FailureCategory:
            assert cat in RETRYABLE_CATEGORIES or cat in NON_RETRYABLE_CATEGORIES, (
                f"{cat} not classified"
            )
