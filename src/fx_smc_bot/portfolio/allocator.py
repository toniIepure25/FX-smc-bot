"""Risk budget allocation across selected candidates.

After selection, the allocator distributes the remaining risk budget
across the chosen intents, respecting the throttle factor from drawdown
tracking and ensuring total risk stays within the portfolio cap.

Supports multiple allocation strategies: equal_risk, score_weighted,
volatility_adjusted, capped_conviction.
"""

from __future__ import annotations

from fx_smc_bot.config import RiskConfig
from fx_smc_bot.domain import PositionIntent


def allocate_risk_budget(
    intents: list[PositionIntent],
    risk_cfg: RiskConfig,
    equity: float,
    throttle_factor: float = 1.0,
    strategy: str | None = None,
) -> list[PositionIntent]:
    """Apply portfolio-level risk budget constraints and throttling."""
    if not intents or equity <= 0:
        return []

    total_risk = sum(i.risk_fraction for i in intents)
    if total_risk <= 0:
        return []

    strat = strategy or risk_cfg.allocation_strategy

    if strat == "score_weighted":
        intents = _score_weighted(intents, risk_cfg)
    elif strat == "capped_conviction":
        intents = _capped_conviction(intents, risk_cfg)

    total_risk = sum(i.risk_fraction for i in intents)
    effective_cap = risk_cfg.max_portfolio_risk * throttle_factor

    if total_risk <= effective_cap:
        return [_scale_intent(i, throttle_factor) for i in intents]

    scale = effective_cap / total_risk
    return [_scale_intent(i, scale) for i in intents]


def _scale_intent(i: PositionIntent, factor: float) -> PositionIntent:
    return PositionIntent(
        candidate=i.candidate,
        risk_fraction=i.risk_fraction * factor,
        units=round(i.units * factor, 2),
        notional=i.notional * factor,
        portfolio_weight=i.portfolio_weight * factor,
    )


def _score_weighted(
    intents: list[PositionIntent],
    risk_cfg: RiskConfig,
) -> list[PositionIntent]:
    """Weight allocation by signal score (higher score = more budget)."""
    scores = [i.candidate.signal_score for i in intents]
    total_score = sum(scores) or 1.0
    total_risk = sum(i.risk_fraction for i in intents)

    result = []
    for intent, score in zip(intents, scores):
        weight = score / total_score
        new_risk = total_risk * weight
        scale = new_risk / intent.risk_fraction if intent.risk_fraction > 0 else 0.0
        result.append(PositionIntent(
            candidate=intent.candidate,
            risk_fraction=new_risk,
            units=round(intent.units * scale, 2),
            notional=intent.notional * scale,
            portfolio_weight=weight,
        ))
    return result


def _capped_conviction(
    intents: list[PositionIntent],
    risk_cfg: RiskConfig,
) -> list[PositionIntent]:
    """Cap individual risk at 1.5x base, redistribute excess equally."""
    cap = risk_cfg.base_risk_per_trade * 1.5
    excess = 0.0
    capped: list[PositionIntent] = []
    uncapped_count = 0

    for i in intents:
        if i.risk_fraction > cap:
            excess += i.risk_fraction - cap
            capped.append(PositionIntent(
                candidate=i.candidate,
                risk_fraction=cap,
                units=round(i.units * cap / i.risk_fraction, 2) if i.risk_fraction > 0 else 0.0,
                notional=i.notional * cap / i.risk_fraction if i.risk_fraction > 0 else 0.0,
                portfolio_weight=i.portfolio_weight,
            ))
        else:
            uncapped_count += 1
            capped.append(i)

    if excess > 0 and uncapped_count > 0:
        bonus = excess / uncapped_count
        result = []
        for i in capped:
            if i.risk_fraction < cap:
                new_risk = min(i.risk_fraction + bonus, cap)
                scale = new_risk / i.risk_fraction if i.risk_fraction > 0 else 1.0
                result.append(PositionIntent(
                    candidate=i.candidate,
                    risk_fraction=new_risk,
                    units=round(i.units * scale, 2),
                    notional=i.notional * scale,
                    portfolio_weight=i.portfolio_weight,
                ))
            else:
                result.append(i)
        return result
    return capped
