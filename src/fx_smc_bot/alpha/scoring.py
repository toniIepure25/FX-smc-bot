"""Multi-factor signal scoring.

Each trade candidate receives three sub-scores that combine into the
overall signal_score:

  - **structure_score**: confluence of HTF/LTF alignment, displacement quality,
    recent BOS/CHoCH strength.
  - **liquidity_score**: quality of the liquidity sweep (if any), proximity
    to key levels.
  - **session_score**: bonus for trades in high-volume sessions (London, overlap).

Scores are normalised to [0, 1].
"""

from __future__ import annotations

from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    MultiTimeframeContext,
    OrderBlock,
    SessionName,
    StructureBreak,
    StructureRegime,
)


def score_htf_alignment(
    htf_bias: Direction | None,
    candidate_direction: Direction,
) -> float:
    """1.0 if candidate aligns with HTF bias, 0.3 if no bias, 0.0 if counter-trend."""
    if htf_bias is None:
        return 0.3
    return 1.0 if htf_bias == candidate_direction else 0.0


def score_displacement_quality(atr_multiple: float) -> float:
    """Higher ATR multiple => stronger displacement. Capped at 1.0."""
    return min(atr_multiple / 3.0, 1.0)


def score_fvg_quality(fvg: FVGZone) -> float:
    """Larger, unfilled FVGs score higher."""
    size_score = min(fvg.size_atr / 2.0, 1.0)
    fill_penalty = fvg.filled_pct
    return max(size_score * (1.0 - fill_penalty), 0.0)


def score_ob_quality(ob: OrderBlock) -> float:
    """Confirmed, unmitigated OBs score higher."""
    base = 0.7 if ob.confirmed else 0.3
    mit_penalty = ob.mitigated_pct * 0.5
    return max(base - mit_penalty, 0.0)


def score_liquidity_sweep(level: LiquidityLevel | None) -> float:
    """Swept levels score 1.0 proportional to touch count quality."""
    if level is None or not level.swept:
        return 0.0
    return min(level.touch_count / 4.0, 1.0)


def score_session_timing(session: SessionName | None) -> float:
    """London and overlap sessions are preferred; Asian/NY are weaker."""
    weights = {
        SessionName.LONDON_NY_OVERLAP: 1.0,
        SessionName.LONDON: 0.9,
        SessionName.NEW_YORK: 0.6,
        SessionName.ASIAN: 0.3,
    }
    return weights.get(session, 0.2) if session else 0.2


def composite_score(
    structure_score: float,
    liquidity_score: float,
    session_score: float,
    weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
) -> float:
    """Weighted combination of sub-scores."""
    w_s, w_l, w_sess = weights
    total_w = w_s + w_l + w_sess
    return (w_s * structure_score + w_l * liquidity_score + w_sess * session_score) / total_w
