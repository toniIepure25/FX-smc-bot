"""Candidate builder: orchestrates all setup family detectors to produce
trade candidates from the current multi-timeframe context.

Detector selection is config-driven via AlphaConfig.enabled_families,
enabling systematic ablation studies.
"""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import AlphaConfig, RiskConfig, SessionConfig
from fx_smc_bot.domain import MultiTimeframeContext, TradeCandidate
from fx_smc_bot.alpha.setup_families import (
    BOSContinuationDetector,
    FVGRetraceDetector,
    SetupDetector,
    SweepReversalDetector,
)
from fx_smc_bot.alpha.filters import apply_filters


_DETECTOR_REGISTRY: dict[str, type] = {
    "sweep_reversal": SweepReversalDetector,
    "bos_continuation": BOSContinuationDetector,
    "fvg_retrace": FVGRetraceDetector,
}

_baseline_registered = False


def _ensure_baselines_registered() -> None:
    global _baseline_registered
    if _baseline_registered:
        return
    try:
        from fx_smc_bot.alpha.baselines.momentum import MomentumDetector
        from fx_smc_bot.alpha.baselines.session_breakout import SessionBreakoutDetector
        from fx_smc_bot.alpha.baselines.mean_reversion import MeanReversionDetector
        _DETECTOR_REGISTRY["momentum"] = MomentumDetector
        _DETECTOR_REGISTRY["session_breakout"] = SessionBreakoutDetector
        _DETECTOR_REGISTRY["mean_reversion"] = MeanReversionDetector
    except ImportError:
        pass
    _baseline_registered = True


def register_detector(name: str, cls: type) -> None:
    """Register a custom detector class for use in config-driven selection."""
    _DETECTOR_REGISTRY[name] = cls


def build_detectors(
    family_names: list[str] | None = None,
    scoring_weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
) -> list[SetupDetector]:
    """Build detector instances from family name strings."""
    _ensure_baselines_registered()
    if family_names is None:
        family_names = ["sweep_reversal", "bos_continuation", "fvg_retrace"]
    detectors: list[SetupDetector] = []
    for name in family_names:
        cls = _DETECTOR_REGISTRY.get(name)
        if cls is not None:
            try:
                detectors.append(cls(scoring_weights=scoring_weights))
            except TypeError:
                detectors.append(cls())
    return detectors


def generate_candidates(
    ctx: MultiTimeframeContext,
    current_price: float,
    current_time: datetime,
    detectors: list[SetupDetector] | None = None,
    risk_cfg: RiskConfig | None = None,
    session_cfg: SessionConfig | None = None,
    alpha_cfg: AlphaConfig | None = None,
    diagnostics: "DetectorDiagnostics | None" = None,
) -> list[TradeCandidate]:
    """Run all setup detectors and return filtered, scored candidates."""
    from fx_smc_bot.alpha.diagnostics import DetectorDiagnostics as _DD
    risk_cfg = risk_cfg or RiskConfig()
    alpha_cfg = alpha_cfg or AlphaConfig()

    if detectors is None:
        detectors = build_detectors(alpha_cfg.enabled_families, alpha_cfg.scoring_weights)

    raw_candidates: list[TradeCandidate] = []
    for det in detectors:
        family_name = _detector_family_name(det)
        if diagnostics is not None:
            diagnostics.record_scan(family_name)
        results = det.scan(ctx, current_price, current_time, session_cfg)
        raw_candidates.extend(results)
        if diagnostics is not None:
            for c in results:
                diagnostics.record_raw_signal(family_name, ctx.pair.value)

    filtered = apply_filters(raw_candidates, risk_cfg, alpha_cfg)
    if diagnostics is not None:
        for c in filtered:
            diagnostics.record_filter_pass(c.family.value if hasattr(c.family, 'value') else str(c.family))
        rejected = set(id(c) for c in raw_candidates) - set(id(c) for c in filtered)
        for c in raw_candidates:
            if id(c) in rejected:
                fam = c.family.value if hasattr(c.family, 'value') else str(c.family)
                if c.signal_score < (alpha_cfg.min_signal_score if alpha_cfg else 0.15):
                    diagnostics.record_rejection(fam, "score_too_low")
                elif c.reward_risk_ratio < (risk_cfg.min_reward_risk_ratio if risk_cfg else 1.5):
                    diagnostics.record_rejection(fam, "rr_too_low")
                elif c.risk_distance <= 0:
                    diagnostics.record_rejection(fam, "risk_distance_zero")

    filtered.sort(key=lambda c: c.signal_score, reverse=True)
    return filtered


def _detector_family_name(det: SetupDetector) -> str:
    cls_name = type(det).__name__
    _NAME_MAP = {
        "SweepReversalDetector": "sweep_reversal",
        "BOSContinuationDetector": "bos_continuation",
        "FVGRetraceDetector": "fvg_retrace",
        "MomentumDetector": "momentum",
        "SessionBreakoutDetector": "session_breakout",
        "MeanReversionDetector": "mean_reversion",
    }
    return _NAME_MAP.get(cls_name, cls_name.lower())
