from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_smc_bot.research import classical_fx_f0rp as f0rp

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results" / "gate_f0rp"


def _load(name: str) -> dict[str, object]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_compact_plans_are_deterministic_and_exclude_nzd() -> None:
    market = f0rp.development_market_plan()
    rates = f0rp.development_rate_plan()

    assert market == f0rp.development_market_plan()
    assert rates == f0rp.development_rate_plan()
    assert market["partition_count"] == 1_512
    assert market["pair_month_count"] == 756
    assert rates["partition_count"] == 49
    assert "NZDUSD" not in market["instruments"]
    assert "NZD" not in rates["currencies"]
    assert market["provider_requests_sent"] == 0
    assert rates["provider_requests_sent"] == 0


def test_execution_readiness_fails_closed_before_provider_access() -> None:
    readiness = f0rp.execution_readiness()

    assert readiness["status"] == (
        "F0RP_RATE_PROVENANCE_RECONCILED_EMPIRICAL_EXECUTION_BLOCKED"
    )
    assert readiness["official_rate_provider_adapters_implemented"] is False
    assert readiness["end_to_end_empirical_orchestration_implemented"] is False
    assert readiness["provider_requests_sent"] == 0
    assert readiness["market_observations_accessed"] is False
    assert readiness["rate_observations_accessed"] is False


def test_runner_status_is_nonempirical() -> None:
    from scripts.run_gate_f0rp import run

    result = run(argparse.Namespace(stage="status"))
    assert result == f0rp.execution_readiness()


def test_protocol_artifacts_bind_the_amendment_commit() -> None:
    expected = "62ee708891b8ee056bf8052f74eece2cb71bba49"
    for name in (
        "storage_budget.json",
        "market_recovery_protocol.json",
        "rate_recovery_protocol.json",
        "rate_normalization_protocol.json",
    ):
        artifact = _load(name)
        assert artifact["amendment_pre_data_access_sha"] == expected
        assert artifact["market_observations_accessed"] is False
        assert artifact["rate_observations_accessed"] is False
