"""Gate C.3F-V validation safeguards."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fx_smc_bot.data.development_freeze import (
    validate_ready_development_freeze,
)
from scripts.run_gate_c3fv_validation import (
    contains_forbidden_performance_fields,
    terminal_status_class,
)


class TestEventSmokePerformanceProhibition:
    def test_detects_forbidden_performance_fields(self) -> None:
        assert contains_forbidden_performance_fields({"pnl": 1})
        assert contains_forbidden_performance_fields({
            "nested": [{"win_rate": 0.5}],
        })

    def test_allows_state_transition_funnel_fields(self) -> None:
        artifact = {
            "status": "NOT_RUN_BLOCKED_BY_TICK_AUDIT",
            "funnels": {
                "sweep_reversal": {
                    "breaches": 10,
                    "reclaims": 3,
                    "order_intents": 1,
                },
            },
        }
        assert not contains_forbidden_performance_fields(artifact)


class TestTerminalDayClassification:
    def test_complete_positive_rows_is_valid_data(self) -> None:
        day = SimpleNamespace(status="complete", rows=100, failure_category="")
        assert terminal_status_class(day) == "valid_data"

    def test_weekend_market_closed_is_distinct(self) -> None:
        day = SimpleNamespace(
            status="market_closed",
            rows=0,
            failure_category="MARKET_CLOSED_WEEKEND",
        )
        assert terminal_status_class(day) == "market_closed_weekend"

    def test_failed_day_is_not_silently_accepted(self) -> None:
        day = SimpleNamespace(
            status="failed",
            rows=0,
            failure_category="PARSER_ERROR",
        )
        assert terminal_status_class(day) == "terminal_failed"


class TestDevelopmentFreezeValidation:
    def test_rejects_non_ready_freeze(self, tmp_path: Path) -> None:
        path = tmp_path / "freeze.json"
        path.write_text(json.dumps({
            "status": "BLOCKED",
            "monthly_quality_manifest_hash": "a",
            "canonical_checksum_set_hash": "b",
            "selected_research_universe": ["EURUSD"],
        }))

        result = validate_ready_development_freeze(
            path,
            expected_manifest_hash="a",
            expected_canonical_checksum_set_hash="b",
            requested_pairs=["EURUSD"],
        )

        assert not result.passed
        assert "freeze status is not READY" in result.reasons

    def test_rejects_hash_mismatch_and_universe_escape(
        self, tmp_path: Path,
    ) -> None:
        path = tmp_path / "freeze.json"
        path.write_text(json.dumps({
            "status": "READY",
            "monthly_quality_manifest_hash": "a",
            "canonical_checksum_set_hash": "b",
            "selected_research_universe": ["EURUSD"],
        }))

        result = validate_ready_development_freeze(
            path,
            expected_manifest_hash="x",
            expected_canonical_checksum_set_hash="y",
            requested_pairs=["EURUSD", "USDJPY"],
        )

        assert not result.passed
        assert "monthly quality manifest hash mismatch" in result.reasons
        assert "canonical checksum set hash mismatch" in result.reasons
        assert any("USDJPY" in reason for reason in result.reasons)

    def test_accepts_exact_ready_freeze(self, tmp_path: Path) -> None:
        path = tmp_path / "freeze.json"
        path.write_text(json.dumps({
            "status": "READY",
            "monthly_quality_manifest_hash": "a",
            "canonical_checksum_set_hash": "b",
            "selected_research_universe": ["EURUSD", "USDJPY"],
        }))

        result = validate_ready_development_freeze(
            path,
            expected_manifest_hash="a",
            expected_canonical_checksum_set_hash="b",
            requested_pairs=["EURUSD"],
        )

        assert result.passed
        assert not result.reasons
