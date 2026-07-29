from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.gate_c6rcipda import (
    SAFE_CLASSIFICATIONS,
    classify_committed_path,
    classify_content,
    corrected_prohibited_data_audit,
)

REPO = Path(__file__).resolve().parents[2]


def test_all_original_false_positive_paths_are_safe() -> None:
    original = json.loads(
        (REPO / "results/gate_c6rci/prohibited_data_audit.json").read_text(encoding="utf-8")
    )

    records = [classify_committed_path(REPO / path) for path in original["prohibited_paths"]]

    assert {record.classification for record in records} <= SAFE_CLASSIFICATIONS
    assert not [record for record in records if record.is_prohibited]
    assert not [record for record in records if record.is_ambiguous]


def test_corrected_audit_separates_safe_paths_from_payload_violations() -> None:
    original = json.loads(
        (REPO / "results/gate_c6rci/prohibited_data_audit.json").read_text(encoding="utf-8")
    )

    audit = corrected_prohibited_data_audit(REPO, original["prohibited_paths"])

    assert audit["status"] == "PASS"
    assert audit["prohibited_payload_paths"] == []
    assert audit["ambiguous_paths"] == []
    assert len(audit["reviewed_safe_control_paths"]) == len(original["prohibited_paths"])


def test_safe_holdout_policy_markdown_is_allowed() -> None:
    result = classify_content(
        Path("docs/research/GATE_C3_SPLIT_AND_HOLDOUT_POLICY.md"),
        b"# Holdout Policy\n\nThe holdout remains closed.\n",
    )

    assert result.classification == "POLICY_DOCUMENTATION"
    assert not result.is_prohibited


def test_compact_holdout_integrity_json_is_allowed() -> None:
    payload = {
        "holdout_market_data_loaded": False,
        "holdout_events_detected": False,
        "status": "PASS",
        "artifact_hash": "abc123",
    }

    result = classify_content(
        Path("results/gate_c6/holdout_integrity.json"),
        json.dumps(payload).encode("utf-8"),
    )

    assert result.classification == "INTEGRITY_METADATA"
    assert not result.is_prohibited


def test_access_control_code_and_tests_are_allowed() -> None:
    source_result = classify_content(
        Path("src/fx_smc_bot/data/holdout_access.py"),
        b"def assert_holdout_closed():\n    raise RuntimeError('closed')\n",
    )
    test_result = classify_content(
        Path("tests/test_data/test_holdout_access.py"),
        b"def test_holdout_rejected():\n    assert True\n",
    )

    assert source_result.classification == "ACCESS_CONTROL_CODE"
    assert test_result.classification == "ACCESS_CONTROL_TEST"


def test_compact_pre_holdout_metadata_is_allowed() -> None:
    freeze = classify_content(
        Path("results/pre_holdout/research_freeze.json"),
        b'{"status": "FROZEN", "hashes": {"config": "abc"}, "rows": 0}',
    )
    quality = classify_content(
        Path("results/pre_holdout/data_quality/data_quality.json"),
        b'{"status": "PASS", "checks": {"missing": 0}, "summary": {"rows": 100}}',
    )

    assert freeze.classification == "FREEZE_OR_PROVENANCE_METADATA"
    assert quality.classification == "DATA_QUALITY_SUMMARY"
    assert not freeze.is_prohibited
    assert not quality.is_prohibited


def test_decision_memo_is_allowed() -> None:
    result = classify_content(
        Path("docs/research/PRE_HOLDOUT_DECISION_MEMO.md"),
        b"# Decision Memo\n\nNo holdout data was opened.\n",
    )

    assert result.classification == "DECISION_DOCUMENTATION"
    assert not result.is_prohibited


def test_documented_placeholder_credentials_are_allowed() -> None:
    result = classify_content(
        Path("docs/research/GATE_C2_DATA_ACQUISITION_GUIDE.md"),
        b'export OANDA_API_TOKEN="your-token-here"\n',
    )

    assert result.classification == "DECISION_DOCUMENTATION"
    assert not result.is_prohibited


def test_aggregate_audit_json_with_path_lists_is_allowed() -> None:
    payload = {
        "changed_paths": [f"docs/research/{index}.md" for index in range(30)],
        "status": "FAIL",
        "findings": [],
    }

    result = classify_content(
        Path("results/gate_c6rci/prohibited_data_audit.json"),
        json.dumps(payload).encode("utf-8"),
    )

    assert result.classification == "RESEARCH_RESULT_SUMMARY"
    assert not result.is_prohibited
    assert not result.is_ambiguous


def test_script_documentation_string_is_allowed() -> None:
    source = 'NOTE = """' + ("Acceptance research methods.\n" * 80) + '"""\n'
    result = classify_content(Path("scripts/run_gate_c6.py"), source.encode("utf-8"))

    assert result.classification == "ACCESS_CONTROL_CODE"
    assert not result.is_ambiguous


def test_raw_tick_and_canonical_payloads_are_rejected() -> None:
    assert classify_content(Path("data/raw/EURUSD/sample.bi5"), b"\x00\x01").classification == (
        "RAW_MARKET_DATA"
    )
    canonical = classify_content(Path("data/canonical/USDJPY/events.parquet"), b"PAR1")

    assert canonical.classification == ("CANONICAL_MARKET_DATA")


def test_row_level_json_and_jsonl_payloads_are_rejected() -> None:
    ohlc_rows = {
        "rows": [
            {
                "timestamp": "2020-01-01T00:00:00Z",
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
            }
        ]
    }
    event_line = b'{"event_id": 1, "timestamp": "t", "outcome": 2.0, "markout": 1.5}\n'

    ohlc_result = classify_content(Path("results/x/ohlc.json"), json.dumps(ohlc_rows).encode())

    assert ohlc_result.classification == ("ROW_LEVEL_EVENT_DATA")
    assert classify_content(Path("results/x/events.jsonl"), event_line).classification == (
        "ROW_LEVEL_EVENT_DATA"
    )


def test_row_level_control_table_and_holdout_outcomes_are_rejected() -> None:
    control_csv = b"control_id,timestamp,event_id,markout\n1,t,2,3.0\n"
    holdout_outcome = {"holdout_results": [{"timestamp": "t", "outcome": 1.0, "markout": 2.0}]}

    assert classify_content(Path("results/x/control_table.csv"), control_csv).classification == (
        "ROW_LEVEL_CONTROL_DATA"
    )
    assert (
        classify_content(
            Path("results/holdout/outcomes.json"),
            json.dumps(holdout_outcome).encode(),
        ).classification
        == "HOLDOUT_PAYLOAD"
    )


def test_credentials_large_binary_and_ambiguous_json_fail_closed() -> None:
    credential = b"OANDA_API_KEY=secret\n"
    large_binary = b"\x00" * 2_000_001
    ambiguous_json = {"vectors": [[1.0, 2.0, 3.0] for _ in range(50)]}

    assert classify_content(Path(".env"), credential).classification == "CREDENTIAL_OR_SECRET"
    assert classify_content(Path("results/blob.bin"), large_binary).classification == (
        "UNEXPLAINED_BINARY"
    )
    ambiguous = classify_content(
        Path("results/ambiguous.json"),
        json.dumps(ambiguous_json).encode(),
    )

    assert ambiguous.classification == ("AMBIGUOUS")
