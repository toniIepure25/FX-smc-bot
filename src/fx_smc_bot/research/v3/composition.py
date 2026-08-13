"""Multi-scale composition grammar for V3.

The single biggest source of hidden degrees of freedom is uncontrolled composition -- every
signal times every filter times every regime. V3 forbids that. Composition is a *closed
whitelist* of archetypes, each of which is an explicit hypothesis about how independent
sources of structure combine. A component plays exactly one typed role:

    SIGNAL  -> the directional edge
    REGIME  -> a frozen causal state that switches the signal on/off
    FILTER  -> a quality/eligibility condition
    GATE    -> a cost/liquidity gate on execution

An archetype is admissible only if every component family is itself admissible and the
combination has a stated hypothesis and a *bounded* candidate budget. There is no operator
that forms the cross-product of all families.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.families import FAMILY_INDEX
from fx_smc_bot.research.v3.horizons import HorizonClass


@dataclass(frozen=True, slots=True)
class Component:
    role: str  # SIGNAL | REGIME | FILTER | GATE
    family_id: str


@dataclass(frozen=True, slots=True)
class CompositionArchetype:
    archetype_id: str
    horizon: HorizonClass
    hypothesis: str
    components: tuple[Component, ...]
    candidate_budget: int  # frozen bounded count of parameter variants for this archetype

    def as_dict(self) -> dict[str, Any]:
        return {
            "archetype_id": self.archetype_id,
            "horizon": self.horizon.value,
            "hypothesis": self.hypothesis,
            "components": [{"role": c.role, "family_id": c.family_id} for c in self.components],
            "candidate_budget": self.candidate_budget,
        }


H0 = HorizonClass.H0_MICRO_INTRADAY
H1 = HorizonClass.H1_SESSION_DAILY
H2 = HorizonClass.H2_INTRAWEEK

ARCHETYPES: tuple[CompositionArchetype, ...] = (
    CompositionArchetype(
        "M_TREND_PULLBACK_VOLREGIME_SPREADGATE", H1,
        "Longer-horizon trend + shorter-horizon pullback entry, active only in a moderate "
        "volatility regime and executed only through a compressed-spread gate.",
        (
            Component("SIGNAL", "V3_B_TREND_PULLBACK_ENTRY"),
            Component("REGIME", "V3_J_VOL_REGIME_CONDITION"),
            Component("GATE", "V3_E_SPREAD_STATE_GATED_REVERSAL"),
        ),
        candidate_budget=16,
    ),
    CompositionArchetype(
        "M_COMPRESSION_BREAKOUT_REGIME", H0,
        "Volatility compression + directional breakout, admitted only when a frozen regime "
        "says the market is in a low-vol pre-expansion state.",
        (
            Component("SIGNAL", "V3_A_DONCHIAN_BREAKOUT_POST_COMPRESSION"),
            Component("FILTER", "V3_D_COMPRESSION_EXPANSION_BREAK"),
            Component("REGIME", "V3_J_VOL_REGIME_CONDITION"),
        ),
        candidate_budget=16,
    ),
    CompositionArchetype(
        "M_LIQSHOCK_SESSION_REVERSION_COSTGATE", H0,
        "A liquidity/spread shock near a session open triggers a mean-reversion, taken only "
        "when the cost gate says expected edge exceeds cost.",
        (
            Component("SIGNAL", "V3_C_ZSCORE_OVERSHOOT_REVERSION"),
            Component("FILTER", "V3_F_SESSION_OPEN_CONDITIONED_MOMENTUM"),
            Component("GATE", "V3_K_COST_GATED_SPARSE_ENTRY"),
        ),
        candidate_budget=16,
    ),
    CompositionArchetype(
        "M_FACTOR_RESIDUAL_STATEFILTER_VOLNORM", H1,
        "USD-factor residual reversion, cleaned by a causal state-space filter and "
        "volatility-normalised, on a beta-neutral basis.",
        (
            Component("SIGNAL", "V3_G_USD_FACTOR_RESIDUAL_REVERSION"),
            Component("FILTER", "V3_I_KALMAN_STATE_TREND"),
            Component("REGIME", "V3_J_VOL_REGIME_CONDITION"),
        ),
        candidate_budget=12,
    ),
    CompositionArchetype(
        "M_TRIANGLE_COINTEGRATION_VOLNORM", H1,
        "Triangular no-arbitrage residual reversion combined with a cointegration-state "
        "eligibility filter and volatility normalisation.",
        (
            Component("SIGNAL", "V3_H_TRIANGULAR_RESIDUAL_REVERSION"),
            Component("FILTER", "V3_H_COINTEGRATION_KALMAN_HEDGE"),
            Component("REGIME", "V3_J_VOL_REGIME_CONDITION"),
        ),
        candidate_budget=12,
    ),
    CompositionArchetype(
        "M_XSMOM_CHANGEPOINT_COSTGATE", H2,
        "Cross-sectional momentum entered on a fresh causal change-point, cost-gated; "
        "price-alpha-only at H2 (financing unsupported).",
        (
            Component("SIGNAL", "V3_G_CROSS_SECTIONAL_MOMENTUM"),
            Component("FILTER", "V3_I_CHANGEPOINT_REGIME_SHIFT"),
            Component("GATE", "V3_K_COST_GATED_SPARSE_ENTRY"),
        ),
        candidate_budget=12,
    ),
)

ARCHETYPE_INDEX: dict[str, CompositionArchetype] = {a.archetype_id: a for a in ARCHETYPES}


def validate_archetypes() -> None:
    """Every component must reference a registered family; roles must be legal."""

    legal_roles = {"SIGNAL", "REGIME", "FILTER", "GATE"}
    for arch in ARCHETYPES:
        signal_count = 0
        for comp in arch.components:
            if comp.role not in legal_roles:
                raise ValueError(f"{arch.archetype_id}: illegal role {comp.role}")
            if comp.family_id not in FAMILY_INDEX:
                raise ValueError(f"{arch.archetype_id}: unknown family {comp.family_id}")
            if comp.role == "SIGNAL":
                signal_count += 1
        if signal_count != 1:
            raise ValueError(f"{arch.archetype_id}: must have exactly one SIGNAL component")


def total_composition_candidates() -> int:
    return sum(a.candidate_budget for a in ARCHETYPES)


def composition_grammar_payload() -> dict[str, Any]:
    validate_archetypes()
    return {
        "artifact_id": "V3_COMPOSITION_GRAMMAR_V1",
        "principle": "closed whitelist of archetypes with explicit hypotheses; no "
                     "signal-x-filter-x-regime cross-product operator",
        "roles": ["SIGNAL", "REGIME", "FILTER", "GATE"],
        "archetype_count": len(ARCHETYPES),
        "total_composition_candidates": total_composition_candidates(),
        "archetypes": [a.as_dict() for a in ARCHETYPES],
    }


def composition_hash() -> str:
    return canonical_hash(composition_grammar_payload())
