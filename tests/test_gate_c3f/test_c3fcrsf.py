from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fx_smc_bot.data.development_freeze import (
    freeze_scope_hash,
    validate_pair_scoped_development_freeze,
)
from scripts.run_gate_c3fcrsf import classify_gap_counts, contains_forbidden_field


def test_gap_classification_distinguishes_raw_side_causes() -> None:
    t0 = pd.Timestamp("2019-01-01T00:00:00Z")
    t1 = pd.Timestamp("2019-01-01T00:01:00Z")
    t2 = pd.Timestamp("2019-01-01T00:02:00Z")
    t3 = pd.Timestamp("2019-01-01T00:03:00Z")

    counts = classify_gap_counts(
        tick_ts={t0, t1, t2, t3},
        canonical_ts=set(),
        raw_bid_ts={t0, t1},
        raw_ask_ts={t0, t2},
    )

    assert counts["CANONICAL_BUILD_OMISSION"] == 1
    assert counts["RAW_ASK_MISSING"] == 1
    assert counts["RAW_BID_MISSING"] == 1
    assert counts["RAW_BID_ASK_ALIGNMENT_GAP"] == 1


def test_pair_scoped_freeze_allows_usdjpy_only(tmp_path: Path) -> None:
    freeze = {
        "status": "READY",
        "scope": "PAIR_SCOPED",
        "selected_research_universe": ["USDJPY"],
        "development_audit_hash": "audit",
        "development_certification_hash": "cert",
        "included_canonical_checksums": {"USDJPY": "checksum"},
    }
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(freeze))

    result = validate_pair_scoped_development_freeze(
        path,
        ["USDJPY"],
        expected_audit_hash="audit",
        expected_certification_hash="cert",
        expected_pair_checksums={"USDJPY": "checksum"},
    )

    assert result.passed is True
    assert result.reasons == []


def test_pair_scoped_freeze_rejects_excluded_pair(tmp_path: Path) -> None:
    freeze = {
        "status": "READY",
        "scope": "PAIR_SCOPED",
        "selected_research_universe": ["USDJPY"],
        "development_audit_hash": "audit",
        "development_certification_hash": "cert",
        "included_canonical_checksums": {"USDJPY": "checksum"},
    }
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(freeze))

    result = validate_pair_scoped_development_freeze(
        path,
        ["EURUSD"],
        expected_audit_hash="audit",
        expected_certification_hash="cert",
        expected_pair_checksums={"EURUSD": "checksum"},
    )

    assert result.passed is False
    assert "requested pairs outside research universe" in result.reasons[0]


def test_freeze_scope_hash_changes_when_universe_changes() -> None:
    base = {
        "scope": "PAIR_SCOPED",
        "selected_research_universe": ["USDJPY"],
        "development_audit_hash": "audit",
        "development_certification_hash": "cert",
        "included_canonical_checksums": {"USDJPY": "checksum"},
    }
    expanded = {
        **base,
        "selected_research_universe": ["EURUSD", "USDJPY"],
        "included_canonical_checksums": {"EURUSD": "other", "USDJPY": "checksum"},
    }

    assert freeze_scope_hash(base) != freeze_scope_hash(expanded)


def test_event_artifact_forbidden_metric_detection() -> None:
    allowed = {
        "families": {
            "Sweep Reversal": {
                "2019-01": {
                    "bars_processed": 100,
                    "by_direction": {"long": 50, "short": 50},
                }
            }
        }
    }
    forbidden = {"families": {"x": {"sharpe": 1.0}}}

    assert contains_forbidden_field(allowed) is False
    assert contains_forbidden_field(forbidden) is True
