"""Holdout access control for dataset splits.

Enforces that strategy/event/alpha code cannot access holdout-period data
during development. Data-quality inspection is always permitted; alpha-related
inspection is prohibited until explicitly unlocked.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

SPLIT_BOUNDARIES = {
    "development": ("2015-01-01", "2019-12-31"),
    "validation": ("2020-01-01", "2022-12-31"),
    "holdout": ("2023-01-01", "2025-12-31"),
}

_HOLDOUT_START_NS = np.datetime64("2023-01-01", "ns")
_HOLDOUT_END_NS = np.datetime64("2025-12-31T23:59:59.999999999", "ns")


class AccessPurpose(str, Enum):
    DATA_QUALITY = "data_quality"
    ALPHA_RESEARCH = "alpha_research"
    EVENT_DETECTION = "event_detection"
    STRATEGY_BACKTEST = "strategy_backtest"
    CAMPAIGN = "campaign"


_HOLDOUT_LOCKED = True

_PERMITTED_QUALITY_PURPOSES = {
    AccessPurpose.DATA_QUALITY,
}


@dataclass(frozen=True, slots=True)
class HoldoutViolation:
    purpose: AccessPurpose
    requested_start: str
    requested_end: str
    message: str


def is_holdout_locked() -> bool:
    return _HOLDOUT_LOCKED


def unlock_holdout() -> None:
    global _HOLDOUT_LOCKED
    _HOLDOUT_LOCKED = False
    logger.warning("HOLDOUT UNLOCKED — alpha inspection now permitted")


def lock_holdout() -> None:
    global _HOLDOUT_LOCKED
    _HOLDOUT_LOCKED = True
    logger.info("Holdout locked")


def check_holdout_access(
    start: str | np.datetime64,
    end: str | np.datetime64,
    purpose: AccessPurpose,
) -> HoldoutViolation | None:
    """Check whether accessing the given date range is permitted.

    Returns None if access is allowed, or a HoldoutViolation if blocked.
    """
    if isinstance(start, str):
        start_ns = np.datetime64(start, "ns")
    else:
        start_ns = start.astype("datetime64[ns]")

    if isinstance(end, str):
        end_ns = np.datetime64(end, "ns")
    else:
        end_ns = end.astype("datetime64[ns]")

    overlaps_holdout = start_ns <= _HOLDOUT_END_NS and end_ns >= _HOLDOUT_START_NS

    if not overlaps_holdout:
        return None

    if purpose in _PERMITTED_QUALITY_PURPOSES:
        return None

    if not _HOLDOUT_LOCKED:
        return None

    return HoldoutViolation(
        purpose=purpose,
        requested_start=str(start),
        requested_end=str(end),
        message=(
            f"Access DENIED: {purpose.value} cannot access holdout period "
            f"({SPLIT_BOUNDARIES['holdout'][0]} to {SPLIT_BOUNDARIES['holdout'][1]}) "
            f"while holdout is locked. Requested range: {start} to {end}"
        ),
    )


def guard_holdout(
    start: str | np.datetime64,
    end: str | np.datetime64,
    purpose: AccessPurpose,
) -> None:
    """Raise ValueError if holdout access is denied."""
    violation = check_holdout_access(start, end, purpose)
    if violation is not None:
        raise ValueError(violation.message)


def filter_to_split(
    timestamps: NDArray[np.datetime64],
    split: str,
) -> NDArray[np.bool_]:
    """Return a boolean mask selecting timestamps within the given split."""
    if split not in SPLIT_BOUNDARIES:
        raise ValueError(f"Unknown split: {split}. Valid: {list(SPLIT_BOUNDARIES)}")

    start_str, end_str = SPLIT_BOUNDARIES[split]
    start_ns = np.datetime64(start_str, "ns")
    end_ns = np.datetime64(end_str + "T23:59:59.999999999", "ns")

    return (timestamps >= start_ns) & (timestamps <= end_ns)


def get_split_for_timestamp(ts: np.datetime64) -> str | None:
    """Return which split a timestamp belongs to, or None."""
    ts_ns = ts.astype("datetime64[ns]")
    for split_name, (start_str, end_str) in SPLIT_BOUNDARIES.items():
        start_ns = np.datetime64(start_str, "ns")
        end_ns = np.datetime64(end_str + "T23:59:59.999999999", "ns")
        if start_ns <= ts_ns <= end_ns:
            return split_name
    return None
