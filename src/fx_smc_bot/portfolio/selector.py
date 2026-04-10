"""Candidate selection under portfolio constraints.

Ranks candidates by score, then iteratively selects the best that pass
all risk constraints, resolving conflicts (e.g., opposing USD exposure).
Captures structured rejection reasons in CandidateReview objects.
"""

from __future__ import annotations

from fx_smc_bot.alpha.review import CandidateReview, ReviewCheck, ReviewVerdict, ConfidenceBand
from fx_smc_bot.config import RiskConfig
from fx_smc_bot.domain import Position, PositionIntent, TradeCandidate
from fx_smc_bot.risk.constraints import check_all_constraints
from fx_smc_bot.risk.sizing import SizingStrategy, StopBasedSizer


def select_candidates(
    candidates: list[TradeCandidate],
    open_positions: list[Position],
    equity: float,
    risk_cfg: RiskConfig,
    sizer: SizingStrategy | None = None,
    current_atr: float | None = None,
    median_atr: float | None = None,
    reviews: list[CandidateReview] | None = None,
) -> list[PositionIntent]:
    """Select and size the best candidates that pass all constraints.

    Candidates are assumed to be pre-sorted by signal_score descending.
    If `reviews` list is provided, appends a CandidateReview for each
    candidate processed (both accepted and rejected).
    """
    sizer = sizer or StopBasedSizer()
    selected: list[PositionIntent] = []
    simulated_positions = list(open_positions)

    for candidate in candidates:
        units, risk_frac = sizer.compute(
            candidate, equity, risk_cfg, current_atr, median_atr,
        )
        if units <= 0:
            if reviews is not None:
                reviews.append(CandidateReview(
                    candidate=candidate,
                    verdict=ReviewVerdict.REJECTED,
                    checks=[ReviewCheck("sizing", False, "sizer returned 0 units")],
                    confidence=ConfidenceBand.LOW,
                    timestamp=candidate.timestamp,
                ))
            continue

        notional = units * candidate.entry
        weight = notional / equity if equity > 0 else 0.0

        intent = PositionIntent(
            candidate=candidate,
            risk_fraction=risk_frac,
            units=units,
            notional=notional,
            portfolio_weight=weight,
        )

        passed, reasons = check_all_constraints(
            intent, simulated_positions, risk_cfg, equity,
        )
        if not passed:
            if reviews is not None:
                checks = [ReviewCheck(f"constraint:{r.split()[0]}", False, r) for r in reasons]
                reviews.append(CandidateReview(
                    candidate=candidate,
                    verdict=ReviewVerdict.REJECTED,
                    checks=checks,
                    constraint_reasons=reasons,
                    confidence=ConfidenceBand.LOW,
                    timestamp=candidate.timestamp,
                ))
            continue

        selected.append(intent)

        if reviews is not None:
            reviews.append(CandidateReview(
                candidate=candidate,
                verdict=ReviewVerdict.ACCEPTED,
                checks=[ReviewCheck("constraints", True, "all constraints passed")],
                confidence=ConfidenceBand.HIGH if candidate.signal_score >= 0.5 else ConfidenceBand.MEDIUM,
                timestamp=candidate.timestamp,
            ))

        simulated_positions.append(Position(
            pair=candidate.pair,
            direction=candidate.direction,
            entry_price=candidate.entry,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            units=units,
        ))

    return selected
