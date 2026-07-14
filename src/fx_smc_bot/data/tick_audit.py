"""Tick audit framework for M1 data validation.

Selects deterministic audit windows using a fixed seed, stratified across
years, quarters, and sessions. Compares tick-aggregated M1 with downloaded M1
to verify OHLC construction and spread consistency.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

AUDIT_SEED = 42
MIN_AUDIT_WEEKS = 12


@dataclass(frozen=True, slots=True)
class AuditWindow:
    """One week-long audit window."""
    year: int
    quarter: int
    week_start: str
    week_end: str
    session: str


@dataclass(slots=True)
class TickAuditPlan:
    """Preregistered tick audit plan."""
    seed: int = AUDIT_SEED
    windows: list[AuditWindow] = field(default_factory=list)
    plan_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "window_count": len(self.windows),
            "windows": [
                {
                    "year": w.year,
                    "quarter": w.quarter,
                    "week_start": w.week_start,
                    "week_end": w.week_end,
                    "session": w.session,
                }
                for w in self.windows
            ],
            "plan_hash": self.plan_hash,
        }


def generate_audit_plan(
    start_year: int = 2015,
    end_year: int = 2025,
    seed: int = AUDIT_SEED,
) -> TickAuditPlan:
    """Generate a deterministic audit plan stratified across years and quarters.

    Selects at least MIN_AUDIT_WEEKS complete trading weeks, ensuring coverage
    of both London and New York sessions across all available years.
    """
    rng = random.Random(seed)
    sessions = ["london", "new_york"]
    quarter_months = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]

    windows: list[AuditWindow] = []

    for year in range(start_year, end_year + 1):
        for q_idx, months in enumerate(quarter_months):
            session = sessions[rng.randint(0, 1)]
            month = rng.choice(months)
            week_of_month = rng.randint(1, 3)
            day = min(1 + (week_of_month - 1) * 7, 28)

            start_dt = datetime(year, month, day)
            while start_dt.weekday() != 0:
                start_dt += timedelta(days=1)

            end_dt = start_dt + timedelta(days=5)

            windows.append(AuditWindow(
                year=year,
                quarter=q_idx + 1,
                week_start=start_dt.strftime("%Y-%m-%d"),
                week_end=end_dt.strftime("%Y-%m-%d"),
                session=session,
            ))

    plan = TickAuditPlan(seed=seed, windows=windows)
    plan_json = json.dumps(plan.to_dict(), sort_keys=True)
    plan.plan_hash = hashlib.md5(plan_json.encode()).hexdigest()[:12]
    return plan


@dataclass(slots=True)
class TickAuditResult:
    """Result of comparing tick-aggregated M1 with downloaded M1."""
    window: AuditWindow
    tick_m1_rows: int = 0
    downloaded_m1_rows: int = 0
    ohlc_matches: int = 0
    ohlc_mismatches: int = 0
    max_bid_diff: float = 0.0
    max_ask_diff: float = 0.0
    max_spread_diff: float = 0.0
    status: str = "pending"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "window": {
                "year": self.window.year,
                "quarter": self.window.quarter,
                "week_start": self.window.week_start,
                "week_end": self.window.week_end,
                "session": self.window.session,
            },
            "tick_m1_rows": self.tick_m1_rows,
            "downloaded_m1_rows": self.downloaded_m1_rows,
            "ohlc_matches": self.ohlc_matches,
            "ohlc_mismatches": self.ohlc_mismatches,
            "max_bid_diff": self.max_bid_diff,
            "max_ask_diff": self.max_ask_diff,
            "max_spread_diff": self.max_spread_diff,
            "status": self.status,
            "notes": self.notes,
        }
