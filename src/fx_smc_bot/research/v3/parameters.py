"""Structured parameter scales for V3.

V2's post-mortem flagged dense arbitrary grids as a source of hidden degrees of freedom.
V3 parameters are defined on economically/mathematically meaningful scales -- logarithmic
for lookbacks and thresholds, structural for session anchors -- each with an explicit
rationale, bounds, units, neighbourhood definition and active/inert semantics. A parameter
family is a *small* set of grid points on such a scale; robustness across a parameter's
neighbourhood (adjacent grid points) is a measurable survivor requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash


@dataclass(frozen=True, slots=True)
class ParameterScale:
    name: str
    units: str
    spacing: str  # "log2" | "log10" | "linear" | "structural"
    values: tuple[float, ...]
    lower_bound: float
    upper_bound: float
    neighborhood: str
    active_semantics: str
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "spacing": self.spacing,
            "values": list(self.values),
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "neighborhood": self.neighborhood,
            "active_semantics": self.active_semantics,
            "rationale": self.rationale,
        }


# Canonical, reusable scales referenced by family parameter families.
PARAMETER_SCALES: tuple[ParameterScale, ...] = (
    ParameterScale(
        "lookback_bars_intraday", "M1_bars", "log2",
        (15.0, 30.0, 60.0, 120.0, 240.0), 5.0, 480.0,
        "adjacent doubling steps",
        "longer lookback => slower feature; inert below min_observations",
        "Powers-of-two minutes span 15m..4h, the meaningful intraday memory scales.",
    ),
    ParameterScale(
        "lookback_days_multiday", "trading_days", "log2",
        (2.0, 5.0, 10.0, 20.0), 1.0, 40.0,
        "adjacent doubling steps",
        "sets trend/reversion memory for H2/H3; inert below one day",
        "Day-scale memory for intraweek/intramonth structure.",
    ),
    ParameterScale(
        "entry_threshold_sigma", "z_units", "linear",
        (0.5, 1.0, 1.5, 2.0, 2.5), 0.25, 3.0,
        "+/- one grid step",
        "higher threshold => sparser, higher-conviction entries",
        "Standardised-deviation entry bands; sparsity/turnover trade-off.",
    ),
    ParameterScale(
        "halflife_bars", "M1_bars", "log10",
        (30.0, 100.0, 300.0, 1000.0), 10.0, 3000.0,
        "adjacent decade-ish steps",
        "OU/EWMA memory; inert when series is non-mean-reverting",
        "Log-decade half-lives for mean-reversion / state-space smoothing.",
    ),
    ParameterScale(
        "cost_edge_multiple", "ratio", "linear",
        (1.0, 1.5, 2.0, 3.0), 1.0, 5.0,
        "+/- one grid step",
        "min ratio of expected edge to expected round-trip cost to trade",
        "Cost-aware gate: trade only when edge sufficiently exceeds cost+uncertainty.",
    ),
)

PARAMETER_SCALE_INDEX: dict[str, ParameterScale] = {p.name: p for p in PARAMETER_SCALES}


def scale_grid_size(name: str) -> int:
    return len(PARAMETER_SCALE_INDEX[name].values)


def parameters_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_PARAMETER_SCALES_V1",
        "principle": "meaningful log/structural spacing; no dense arbitrary grids",
        "scales": [p.as_dict() for p in PARAMETER_SCALES],
    }


def parameters_hash() -> str:
    return canonical_hash(parameters_payload())
