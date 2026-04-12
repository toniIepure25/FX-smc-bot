"""Tests for paper-candidate review workflow."""

from __future__ import annotations

import pytest

from fx_smc_bot.research.paper_review import (
    DailyReviewSummary,
    PaperReviewChecklist,
    PaperStageRecommendation,
    PaperStageStatus,
    WeeklyReviewSummary,
    build_daily_summaries,
    build_weekly_summary,
    evaluate_paper_stage,
    format_paper_review,
)


class TestPaperReviewChecklist:
    def test_all_pass(self) -> None:
        cl = PaperReviewChecklist(
            trade_volume_adequate=True, no_system_errors=True,
            discrepancy_within_threshold=True, no_behavioral_drift=True,
            drawdown_within_limits=True, no_blocking_incidents=True,
        )
        assert cl.all_pass
        assert cl.n_failures == 0

    def test_one_failure(self) -> None:
        cl = PaperReviewChecklist(trade_volume_adequate=False)
        assert not cl.all_pass
        assert cl.n_failures == 1

    def test_to_dict(self) -> None:
        cl = PaperReviewChecklist()
        d = cl.to_dict()
        assert "all_pass" in d
        assert "n_failures" in d


class TestBuildDailySummaries:
    def test_groups_by_date(self) -> None:
        events = [
            {"timestamp": "2024-01-01T10:00:00", "event_type": "signal"},
            {"timestamp": "2024-01-01T14:00:00", "event_type": "fill"},
            {"timestamp": "2024-01-02T10:00:00", "event_type": "signal"},
        ]
        summaries = build_daily_summaries(events)
        assert len(summaries) == 2
        assert summaries[0].date == "2024-01-01"
        assert summaries[0].signals_generated == 1
        assert summaries[0].trades_opened == 1

    def test_empty_events(self) -> None:
        assert build_daily_summaries([]) == []


class TestBuildWeeklySummary:
    def test_aggregates_trades(self) -> None:
        days = [
            DailyReviewSummary(date="2024-01-01", trades_opened=3, daily_pnl=100.0),
            DailyReviewSummary(date="2024-01-02", trades_opened=2, daily_pnl=-50.0),
        ]
        ws = build_weekly_summary(days, "W1")
        assert ws.total_trades == 5
        assert ws.weekly_pnl == 50.0
        assert ws.week == "W1"

    def test_drift_detection(self) -> None:
        days = [
            DailyReviewSummary(date=f"2024-01-0{i+1}", daily_pnl=100.0)
            for i in range(3)
        ] + [
            DailyReviewSummary(date=f"2024-01-0{i+4}", daily_pnl=-200.0)
            for i in range(3)
        ]
        ws = build_weekly_summary(days, "W1")
        assert ws.drift_detected is True

    def test_no_drift_stable(self) -> None:
        days = [
            DailyReviewSummary(date=f"2024-01-0{i+1}", daily_pnl=50.0)
            for i in range(4)
        ]
        ws = build_weekly_summary(days, "W1")
        assert ws.drift_detected is False


class TestEvaluatePaperStage:
    def test_pass_all_checks(self) -> None:
        weeks = [
            WeeklyReviewSummary(week="W1", total_trades=15, max_drawdown_pct=0.02),
            WeeklyReviewSummary(week="W2", total_trades=12, max_drawdown_pct=0.03),
        ]
        rec = evaluate_paper_stage("test", weeks, reconciliation_pnl_diff_pct=2.0)
        assert rec.status == PaperStageStatus.PASS
        assert rec.checklist.all_pass

    def test_in_progress_too_few_weeks(self) -> None:
        weeks = [WeeklyReviewSummary(week="W1", total_trades=30)]
        rec = evaluate_paper_stage("test", weeks)
        assert rec.status == PaperStageStatus.IN_PROGRESS

    def test_fail_system_errors(self) -> None:
        weeks = [
            WeeklyReviewSummary(week="W1", total_trades=15, incidents=["CRITICAL ERROR in broker"]),
            WeeklyReviewSummary(week="W2", total_trades=15),
        ]
        rec = evaluate_paper_stage("test", weeks)
        assert rec.status == PaperStageStatus.FAIL
        assert not rec.checklist.no_system_errors

    def test_conditional_minor_issues(self) -> None:
        weeks = [
            WeeklyReviewSummary(week="W1", total_trades=5, max_drawdown_pct=0.01),
            WeeklyReviewSummary(week="W2", total_trades=5, max_drawdown_pct=0.01),
        ]
        rec = evaluate_paper_stage("test", weeks, min_trades=20)
        assert rec.status == PaperStageStatus.CONDITIONAL


class TestFormatPaperReview:
    def test_produces_markdown(self) -> None:
        rec = PaperStageRecommendation(
            status=PaperStageStatus.PASS,
            candidate_label="test",
            recommendation="Paper stage PASS",
            weekly_summaries=[WeeklyReviewSummary(week="W1", total_trades=20)],
        )
        md = format_paper_review(rec)
        assert "Paper Trading Review" in md
        assert "PASS" in md
        assert "test" in md

    def test_includes_blocking_issues(self) -> None:
        rec = PaperStageRecommendation(
            status=PaperStageStatus.FAIL,
            candidate_label="test",
            blocking_issues=["High discrepancy", "System error"],
        )
        md = format_paper_review(rec)
        assert "Blocking Issues" in md
        assert "High discrepancy" in md
