from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gate_f0rpe2er"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_failed_gate_is_preserved_without_reinterpretation() -> None:
    inherited = _load("failed_gate_inheritance.json")

    assert inherited["inheritance_status"] == "FAILED_GATE_PRESERVED_NOT_REVERSED"
    assert inherited["predecessor_decision"] == "BLOCKED_BY_PROSPECTIVE_INTEGRITY"
    assert inherited["sonia_2025_documentation_rows_exposed"] is True
    assert inherited["rows_persisted"] is False
    assert inherited["market_requests"] == inherited["rate_requests"] == 0
    assert inherited["candidate_outcomes"] == 0
    assert inherited["candidate_ranking"] is False


def test_failed_gate_hashes_still_match() -> None:
    inherited = _load("failed_gate_inheritance.json")
    hashes = inherited["failed_gate_sha256"]
    assert isinstance(hashes, dict)
    for relative_path, expected in hashes.items():
        actual = manifest_file_sha256(
            ROOT / relative_path,
            SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
        )
        assert actual == expected, relative_path
