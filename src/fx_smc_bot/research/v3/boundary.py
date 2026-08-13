"""V2 -> V3 information boundary.

V2 is now an *exposed* result, so its high-level diagnostics may legitimately shape V3
research *hypotheses*. They may NOT be used to tune a continuation of the exact same
candidate: doing so would launder an in-sample fit into V3. This artifact draws the line
explicitly and is frozen so the boundary cannot drift during discovery.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

ALLOWED_HIGH_LEVEL_LEARNINGS: tuple[str, ...] = (
    "high turnover is dangerous; cost destroys many raw signals (motivates domain K and "
    "cost-aware survivor predicates).",
    "sparse, event-driven structure deserves emphasis over dense always-on signals.",
    "F04-style liquidity/spread shocks are worth a broader scientific hypothesis (domain E), "
    "not a copy of any single V2 configuration.",
    "seasonality is more useful as a conditioning variable/filter than as a standalone signal "
    "(domain F is defined as conditioning).",
    "EURUSD appeared less hostile than GBPUSD in several V2 families -> justifies keeping the "
    "tier-1 majors as registered breadth, but not centring parameters on any V2 result.",
)

FORBIDDEN_USES: tuple[str, ...] = (
    "copying V2-0220 (or any V2 trial) as a V3 candidate.",
    "tuning V3 parameters around a V2 trial's parameters.",
    "using a V2 trial's profitable thresholds as V3 parameter-neighbourhood centres.",
    "promoting any V2 candidate to the 2018+ holdout.",
    "selecting V3 families/instruments because a V2 result looked attractive on outcomes.",
    "reusing V2 out-of-sample outcomes to pre-rank V3 candidates.",
)

# V3 parameter scales are defined on independent structural grids (see parameters.py); none
# is centred on a V2 result. This is asserted, not merely promised.
PARAMETER_INDEPENDENCE_ASSERTION = (
    "Every V3 parameter scale is a fixed log/structural grid chosen from methodology; no grid "
    "point equals or is centred on any V2 trial's fitted parameter value."
)


def boundary_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_V2_INFORMATION_BOUNDARY_V1",
        "premise": "V2 is an exposed result; it may inform V3 hypotheses, never V3 fits.",
        "allowed_high_level_learnings": list(ALLOWED_HIGH_LEVEL_LEARNINGS),
        "forbidden_uses": list(FORBIDDEN_USES),
        "parameter_independence_assertion": PARAMETER_INDEPENDENCE_ASSERTION,
        "v2_candidates_promoted_to_holdout": 0,
        "v2_candidates_copied_into_v3": 0,
    }


def boundary_hash() -> str:
    return canonical_hash(boundary_payload())
