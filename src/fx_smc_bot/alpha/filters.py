"""Candidate filters: reject low-quality or invalid trade candidates."""

from __future__ import annotations

from fx_smc_bot.config import AlphaConfig, RiskConfig
from fx_smc_bot.domain import TradeCandidate


def apply_filters(
    candidates: list[TradeCandidate],
    risk_cfg: RiskConfig,
    alpha_cfg: AlphaConfig | None = None,
) -> list[TradeCandidate]:
    """Apply all filters sequentially, returning only passing candidates."""
    min_score = alpha_cfg.min_signal_score if alpha_cfg else 0.15
    result: list[TradeCandidate] = []
    for c in candidates:
        if not _passes_minimum_rr(c, risk_cfg):
            continue
        if not _passes_risk_distance(c):
            continue
        if c.signal_score < min_score:
            continue
        result.append(c)
    return result


def _passes_minimum_rr(c: TradeCandidate, cfg: RiskConfig) -> bool:
    return c.reward_risk_ratio >= cfg.min_reward_risk_ratio


def _passes_risk_distance(c: TradeCandidate) -> bool:
    return c.risk_distance > 0
