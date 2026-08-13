"""Frozen V3 horizon-class contract.

V3 is explicitly a multi-horizon program. Every strategy family declares exactly one
horizon class, and the horizon class -- not the family -- fixes the holding-time envelope,
whether overnight financing applies, which cost model is used and the *scale* of the
survivor trade-count requirement. This prevents the class of error the mandate warns
about: evaluating a multi-day strategy under intraday cost/financing assumptions.

Holding bounds are expressed in M1 bars of *market time* (not wall-clock) so they compose
with the M1-native kernel. One 24h FX day approximates 1440 M1 bars; a 5-day trading week
approximates 7200 M1 bars. Bounds are structural (session/day/week/month scales), not tuned
to any observed outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

_BARS_PER_HOUR = 60
_BARS_PER_DAY = 1440  # 24h of M1 bars (FX trades ~24x5)


class HorizonClass(str, Enum):
    H0_MICRO_INTRADAY = "H0_micro_intraday"
    H1_SESSION_DAILY = "H1_session_daily"
    H2_INTRAWEEK = "H2_intraweek"
    H3_INTRAMONTH = "H3_intramonth"


@dataclass(frozen=True, slots=True)
class HorizonSpec:
    horizon: HorizonClass
    description: str
    min_holding_bars: int
    max_holding_bars: int
    crosses_session_boundary: bool
    requires_overnight_financing: bool
    cost_model: str
    # Survivor trade-count floors scale with horizon: a 20-day strategy cannot be held to
    # the same trade-count bar as a 30-minute strategy. Frozen pre-outcome.
    min_survivor_trades: int

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "horizon": self.horizon.value,
            "description": self.description,
            "min_holding_bars": self.min_holding_bars,
            "max_holding_bars": self.max_holding_bars,
            "min_holding_hours": round(self.min_holding_bars / _BARS_PER_HOUR, 3),
            "max_holding_hours": round(self.max_holding_bars / _BARS_PER_HOUR, 3),
            "crosses_session_boundary": self.crosses_session_boundary,
            "requires_overnight_financing": self.requires_overnight_financing,
            "cost_model": self.cost_model,
            "min_survivor_trades": self.min_survivor_trades,
        }
        return data


HORIZONS: tuple[HorizonSpec, ...] = (
    HorizonSpec(
        HorizonClass.H0_MICRO_INTRADAY,
        "Minutes to a few hours; entered and exited well within one session.",
        min_holding_bars=1,
        max_holding_bars=3 * _BARS_PER_HOUR,
        crosses_session_boundary=False,
        requires_overnight_financing=False,
        cost_model="intraday_spread_commission_slippage",
        min_survivor_trades=250,
    ),
    HorizonSpec(
        HorizonClass.H1_SESSION_DAILY,
        "Hours to same-day close; mandatory flat before NY rollover.",
        min_holding_bars=_BARS_PER_HOUR,
        max_holding_bars=_BARS_PER_DAY,
        crosses_session_boundary=False,
        requires_overnight_financing=False,
        cost_model="intraday_spread_commission_slippage",
        min_survivor_trades=120,
    ),
    HorizonSpec(
        HorizonClass.H2_INTRAWEEK,
        "~1-5 trading days; positions held across daily rollovers and possibly a weekend.",
        min_holding_bars=_BARS_PER_DAY,
        max_holding_bars=5 * _BARS_PER_DAY,
        crosses_session_boundary=True,
        requires_overnight_financing=True,
        cost_model="multiday_spread_commission_slippage_financing_gap",
        min_survivor_trades=60,
    ),
    HorizonSpec(
        HorizonClass.H3_INTRAMONTH,
        "~5-20 trading days; multiple rollovers, weekends and possible holiday gaps.",
        min_holding_bars=5 * _BARS_PER_DAY,
        max_holding_bars=20 * _BARS_PER_DAY,
        crosses_session_boundary=True,
        requires_overnight_financing=True,
        cost_model="multiday_spread_commission_slippage_financing_gap",
        min_survivor_trades=30,
    ),
)

HORIZON_INDEX: dict[HorizonClass, HorizonSpec] = {h.horizon: h for h in HORIZONS}


def requires_financing(horizon: HorizonClass) -> bool:
    return HORIZON_INDEX[horizon].requires_overnight_financing


def horizons_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_HORIZON_CONTRACT_V1",
        "bars_per_hour": _BARS_PER_HOUR,
        "bars_per_day": _BARS_PER_DAY,
        "holding_time_basis": "M1_market_time_bars",
        "horizons": [h.as_dict() for h in HORIZONS],
    }


def horizons_hash() -> str:
    return canonical_hash(horizons_payload())
