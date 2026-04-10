"""Tests for the candidate approval pipeline."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.alpha.review import (
    CandidateApprovalPipeline,
    CandidateReview,
    ConfidenceBand,
    ReviewCollector,
    ReviewVerdict,
)
from fx_smc_bot.config import AlphaConfig, OperationalState, RiskConfig, Timeframe, TradingPair
from fx_smc_bot.domain import Direction, Position, SignalFamily, TradeCandidate


def _candidate(
    pair: TradingPair = TradingPair.EURUSD,
    score: float = 0.5,
    direction: Direction = Direction.LONG,
    hour: int = 10,
) -> TradeCandidate:
    return TradeCandidate(
        pair=pair, direction=direction,
        family=SignalFamily.SWEEP_REVERSAL,
        timestamp=datetime(2024, 1, 2, hour, 0),
        entry=1.1, stop_loss=1.097, take_profit=1.109,
        signal_score=score, structure_score=0.7, liquidity_score=0.8,
        execution_timeframe=Timeframe.M15, context_timeframe=Timeframe.H4,
    )


class TestCandidateApprovalPipeline:
    def test_accepts_valid_candidate(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.5)]
        reviews = pipeline.review_candidates(candidates, [])
        assert len(reviews) == 1
        assert reviews[0].verdict == ReviewVerdict.ACCEPTED

    def test_rejects_low_score(self) -> None:
        alpha_cfg = AlphaConfig(min_signal_score=0.5)
        pipeline = CandidateApprovalPipeline(alpha_cfg=alpha_cfg)
        candidates = [_candidate(score=0.1)]
        reviews = pipeline.review_candidates(candidates, [])
        assert reviews[0].verdict == ReviewVerdict.REJECTED
        assert any("score" in r.reason for r in reviews[0].checks if not r.passed)

    def test_rejects_when_locked(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.8)]
        reviews = pipeline.review_candidates(candidates, [], OperationalState.LOCKED)
        assert reviews[0].verdict == ReviewVerdict.REJECTED
        assert any("risk_state" in c.check_name for c in reviews[0].checks if not c.passed)

    def test_rejects_duplicate_pair_direction(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [
            _candidate(TradingPair.EURUSD, 0.8),
            _candidate(TradingPair.EURUSD, 0.7),
        ]
        reviews = pipeline.review_candidates(candidates, [])
        accepted = [r for r in reviews if r.verdict == ReviewVerdict.ACCEPTED]
        assert len(accepted) == 1

    def test_rejects_late_night_session(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.5, hour=23)]
        reviews = pipeline.review_candidates(candidates, [])
        assert reviews[0].verdict == ReviewVerdict.REJECTED

    def test_confidence_band_high_score(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.7)]
        reviews = pipeline.review_candidates(candidates, [])
        assert reviews[0].confidence == ConfidenceBand.HIGH

    def test_confidence_band_medium_score(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.3)]
        reviews = pipeline.review_candidates(candidates, [])
        assert reviews[0].confidence == ConfidenceBand.MEDIUM

    def test_to_dict_includes_all_fields(self) -> None:
        pipeline = CandidateApprovalPipeline()
        candidates = [_candidate(score=0.5)]
        reviews = pipeline.review_candidates(candidates, [])
        d = reviews[0].to_dict()
        assert "pair" in d
        assert "verdict" in d
        assert "checks" in d


class TestReviewCollector:
    def test_aggregates_reviews(self) -> None:
        collector = ReviewCollector()
        pipeline = CandidateApprovalPipeline()
        reviews1 = pipeline.review_candidates([_candidate(score=0.5)], [])
        reviews2 = pipeline.review_candidates([_candidate(score=0.01)], [])
        collector.add(reviews1)
        collector.add(reviews2)
        assert collector.total_reviewed == 2
        assert collector.total_accepted >= 1
        assert collector.total_rejected >= 1

    def test_rejection_summary_counts(self) -> None:
        collector = ReviewCollector()
        pipeline = CandidateApprovalPipeline(
            alpha_cfg=AlphaConfig(min_signal_score=0.9),
        )
        reviews = pipeline.review_candidates([_candidate(score=0.1), _candidate(score=0.2, pair=TradingPair.GBPUSD)], [])
        collector.add(reviews)
        summary = collector.rejection_summary()
        assert "score_threshold" in summary

    def test_to_metadata(self) -> None:
        collector = ReviewCollector()
        meta = collector.to_metadata()
        assert "candidates_reviewed" in meta
        assert "rejection_reasons" in meta
