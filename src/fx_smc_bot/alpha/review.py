"""Candidate approval pipeline: structured accept/reject reasoning.

Every trade candidate passes through a sequence of review checks.
Each check produces a ReviewCheck with a pass/fail verdict and reason.
The result is a CandidateReview object that explains exactly why a
candidate was accepted, rejected, or downsized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from fx_smc_bot.config import AlphaConfig, OperationalState, RiskConfig
from fx_smc_bot.domain import Direction, Position, PositionIntent, TradeCandidate


class ReviewVerdict(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DOWNSIZED = "downsized"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True, frozen=True)
class ReviewCheck:
    check_name: str
    passed: bool
    reason: str


@dataclass(slots=True)
class CandidateReview:
    candidate: TradeCandidate
    verdict: ReviewVerdict
    checks: list[ReviewCheck] = field(default_factory=list)
    confidence: ConfidenceBand = ConfidenceBand.MEDIUM
    constraint_reasons: list[str] = field(default_factory=list)
    timestamp: datetime | None = None

    @property
    def rejection_reasons(self) -> list[str]:
        return [c.reason for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "pair": self.candidate.pair.value,
            "direction": self.candidate.direction.value,
            "family": self.candidate.family.value,
            "score": round(self.candidate.signal_score, 3),
            "verdict": self.verdict.value,
            "confidence": self.confidence.value,
            "checks": [{"name": c.check_name, "passed": c.passed, "reason": c.reason} for c in self.checks],
            "constraint_reasons": self.constraint_reasons,
        }


class CandidateApprovalPipeline:
    """Configurable pipeline that reviews each candidate before selection."""

    def __init__(
        self,
        risk_cfg: RiskConfig | None = None,
        alpha_cfg: AlphaConfig | None = None,
    ) -> None:
        self._risk_cfg = risk_cfg or RiskConfig()
        self._alpha_cfg = alpha_cfg or AlphaConfig()

    def review_candidates(
        self,
        candidates: list[TradeCandidate],
        open_positions: list[Position],
        operational_state: OperationalState = OperationalState.ACTIVE,
        current_regime: str | None = None,
    ) -> list[CandidateReview]:
        reviews: list[CandidateReview] = []
        seen_pairs: set[str] = set()

        for c in candidates:
            checks: list[ReviewCheck] = []

            checks.append(self._check_structural_validity(c))
            checks.append(self._check_score_threshold(c))
            checks.append(self._check_risk_state(operational_state))
            checks.append(self._check_regime_compatibility(c, current_regime))
            checks.append(self._check_duplicate_suppression(c, open_positions, seen_pairs))
            checks.append(self._check_session_suitability(c))

            all_passed = all(ch.passed for ch in checks)
            verdict = ReviewVerdict.ACCEPTED if all_passed else ReviewVerdict.REJECTED
            confidence = self._compute_confidence(c, checks)

            review = CandidateReview(
                candidate=c,
                verdict=verdict,
                checks=checks,
                confidence=confidence,
                timestamp=c.timestamp,
            )
            reviews.append(review)

            if all_passed:
                seen_pairs.add(f"{c.pair.value}_{c.direction.value}")

        return reviews

    def _check_structural_validity(self, c: TradeCandidate) -> ReviewCheck:
        if c.risk_distance <= 0:
            return ReviewCheck("structural_validity", False, "risk_distance <= 0 (SL at or beyond entry)")
        if c.reward_risk_ratio < self._risk_cfg.min_reward_risk_ratio:
            return ReviewCheck("structural_validity", False,
                               f"RR {c.reward_risk_ratio:.2f} < min {self._risk_cfg.min_reward_risk_ratio}")
        return ReviewCheck("structural_validity", True, "valid entry/SL/TP structure")

    def _check_score_threshold(self, c: TradeCandidate) -> ReviewCheck:
        if c.signal_score < self._alpha_cfg.min_signal_score:
            return ReviewCheck("score_threshold", False,
                               f"score {c.signal_score:.3f} < min {self._alpha_cfg.min_signal_score}")
        return ReviewCheck("score_threshold", True, f"score {c.signal_score:.3f} passes threshold")

    def _check_risk_state(self, state: OperationalState) -> ReviewCheck:
        if state in (OperationalState.LOCKED, OperationalState.STOPPED):
            return ReviewCheck("risk_state", False, f"trading {state.value}: no new trades")
        if state == OperationalState.THROTTLED:
            return ReviewCheck("risk_state", True, "throttled: sizing will be reduced")
        return ReviewCheck("risk_state", True, "risk state active")

    def _check_regime_compatibility(self, c: TradeCandidate, regime: str | None) -> ReviewCheck:
        if regime is None:
            return ReviewCheck("regime_compatibility", True, "no regime data available")
        if regime == "high_vol" and c.signal_score < 0.3:
            return ReviewCheck("regime_compatibility", False,
                               f"low-score setup ({c.signal_score:.2f}) in high-vol regime")
        return ReviewCheck("regime_compatibility", True, f"compatible with {regime} regime")

    def _check_duplicate_suppression(
        self,
        c: TradeCandidate,
        open_positions: list[Position],
        seen_pairs: set[str],
    ) -> ReviewCheck:
        key = f"{c.pair.value}_{c.direction.value}"
        if key in seen_pairs:
            return ReviewCheck("duplicate_suppression", False,
                               f"duplicate {c.pair.value} {c.direction.value} already queued this bar")

        same_dir_open = sum(
            1 for p in open_positions
            if p.is_open and p.pair == c.pair and p.direction == c.direction
        )
        if same_dir_open >= self._risk_cfg.max_per_pair_positions:
            return ReviewCheck("duplicate_suppression", False,
                               f"already {same_dir_open} open {c.direction.value} on {c.pair.value}")

        return ReviewCheck("duplicate_suppression", True, "no conflicting open positions")

    def _check_session_suitability(self, c: TradeCandidate) -> ReviewCheck:
        hour = c.timestamp.hour if c.timestamp else 12
        if 22 <= hour or hour < 1:
            return ReviewCheck("session_suitability", False, "outside major sessions (late night)")
        return ReviewCheck("session_suitability", True, "within active session hours")

    def _compute_confidence(self, c: TradeCandidate, checks: list[ReviewCheck]) -> ConfidenceBand:
        if not all(ch.passed for ch in checks):
            return ConfidenceBand.LOW
        if c.signal_score >= 0.5:
            return ConfidenceBand.HIGH
        if c.signal_score >= 0.25:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW


@dataclass(slots=True)
class ReviewCollector:
    """Accumulates candidate reviews across the entire backtest run."""

    _reviews: list[CandidateReview] = field(default_factory=list)

    def add(self, reviews: list[CandidateReview]) -> None:
        self._reviews.extend(reviews)

    @property
    def total_reviewed(self) -> int:
        return len(self._reviews)

    @property
    def total_accepted(self) -> int:
        return sum(1 for r in self._reviews if r.verdict == ReviewVerdict.ACCEPTED)

    @property
    def total_rejected(self) -> int:
        return sum(1 for r in self._reviews if r.verdict == ReviewVerdict.REJECTED)

    def rejection_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._reviews:
            for ch in r.checks:
                if not ch.passed:
                    counts[ch.check_name] = counts.get(ch.check_name, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def to_metadata(self) -> dict:
        return {
            "candidates_reviewed": self.total_reviewed,
            "candidates_accepted": self.total_accepted,
            "candidates_rejected": self.total_rejected,
            "rejection_reasons": self.rejection_summary(),
        }
