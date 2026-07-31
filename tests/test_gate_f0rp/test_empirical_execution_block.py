from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results" / "gate_f0rp"
BLOCK = "F0RP_RATE_PROVENANCE_RECONCILED_EMPIRICAL_EXECUTION_BLOCKED"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_empirical_execution_block_is_fail_closed_and_post_amendment() -> None:
    block = _load("empirical_execution_block.json")
    assert block["status"] == BLOCK
    assert block["amendment_pre_data_access_sha"] == (
        "62ee708891b8ee056bf8052f74eece2cb71bba49"
    )
    assert block["rate_provenance_reconciled"] is True
    assert block["market_provider_requests_sent"] == 0
    assert block["rate_provider_requests_sent"] == 0
    assert block["market_observations_accessed"] is False
    assert block["rate_observations_accessed"] is False


def test_all_six_candidates_are_declared_but_have_no_fabricated_metrics() -> None:
    artifact = _load("development_candidate_results.json")
    candidates = artifact["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 6
    assert all(candidate["status"] == "NOT_RUN" for candidate in candidates)
    assert all(candidate["metrics"] is None for candidate in candidates)
    assert artifact["candidate_ranking_performed"] is False


def test_empirical_audits_are_not_misrepresented_as_passes() -> None:
    for name in (
        "development_market_certification.json",
        "development_rate_certification.json",
        "execution_certification.json",
        "portfolio_accounting_audit.json",
        "lookahead_audit.json",
        "determinism_audit.json",
    ):
        artifact = _load(name)
        assert str(artifact["status"]).startswith("NOT_RUN")
