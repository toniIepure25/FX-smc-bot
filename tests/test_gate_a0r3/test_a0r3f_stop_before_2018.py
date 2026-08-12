from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.research.a0r3d_certified_subset import HoldoutReadGuard, Paths
from fx_smc_bot.research.a0r3f_stop_before_2018 import (
    ADMISSIBLE_SOURCE_KEYS,
    certification_requires_zero_unresolved,
    regression_against_a0r3e,
    survivor_rows,
    unresolved_blocker_matrix,
)


def test_semantic_recovery_uses_only_admissible_source_keys(tmp_path: Path) -> None:
    catalog_sources = {
        "a0_hypothesis_registry",
        "a0_search_space_yaml",
        "a0_search_space_freeze",
        "a0_target_registry",
        "a0r2_configuration_v2_audit",
        "a0r2_materialization_v2",
        "a0r3_pre_a0r3b_source",
    }

    assert catalog_sources == ADMISSIBLE_SOURCE_KEYS
    assert not any(
        "result" in key or "ranking" in key or "survivor" in key for key in catalog_sources
    )


def test_unresolved_blockers_prevent_certification() -> None:
    matrix = unresolved_blocker_matrix(
        [
            {
                "trial_id": "T",
                "family_id": "F03_VOLATILITY_BREAKOUT",
                "blockers": ["family:no exact formula", "stop_rule:no atr"],
            }
        ],
        "hash",
    )

    assert matrix["unresolved_count"] == 2
    assert certification_requires_zero_unresolved(matrix["rows"]) is False


def test_zero_unresolved_is_required_for_certification() -> None:
    assert certification_requires_zero_unresolved([]) is True
    assert (
        certification_requires_zero_unresolved(
            [{"resolution_status": "RESOLVED_EXACT_PRE_OUTCOME"}]
        )
        is True
    )


def test_negative_net_candidates_cannot_enter_scientific_survivors() -> None:
    rows = [
        {
            "trial_id": "negative",
            "primary_equal_weight": {"net_bps": -1.0},
            "cost_stress": {"survives_1_5x": True, "survives_2_0x": True},
        },
        {
            "trial_id": "positive_not_robust",
            "primary_equal_weight": {"net_bps": 1.0},
            "cost_stress": {"survives_1_5x": True, "survives_2_0x": False},
        },
    ]

    assert survivor_rows(rows) == []


def test_positive_cost_robust_candidate_can_enter_scientific_survivors() -> None:
    rows = [
        {
            "trial_id": "survivor",
            "primary_equal_weight": {"net_bps": 1.0},
            "cost_stress": {"survives_1_5x": True, "survives_2_0x": True},
        }
    ]

    assert survivor_rows(rows)[0]["trial_id"] == "survivor"


def test_holdout_guard_rejects_2018_plus_for_a0r3f_boundary(tmp_path: Path) -> None:
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path,
        results=tmp_path,
        docs=tmp_path,
        trials=tmp_path / "trials.jsonl",
        eligibility=tmp_path / "eligibility.json",
        pass_freeze=tmp_path / "freeze.json",
        a0_execution=tmp_path / "a0.json",
        a0r1_execution=tmp_path / "a0r1.json",
    )

    with pytest.raises(ValueError, match="2018_PLUS"):
        HoldoutReadGuard().read_side(paths, "GBPUSD", "bid", 2018, 1)


def test_a0r3e_regression_stability_requires_tiny_delta(tmp_path: Path) -> None:
    prior_dir = tmp_path / "results" / "gate_a0r3e"
    prior_dir.mkdir(parents=True)
    prior_dir.joinpath("corrected_results.json").write_text(
        (
            '{"result_rows":[{"trial_id":"T","primary_equal_weight":'
            '{"gross_bps":1.0,"cost_bps":0.1,"net_bps":0.9,'
            '"daily_sharpe":0.2,"trade_count":3}}]}'
        ),
        encoding="utf-8",
    )
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path,
        results=tmp_path,
        docs=tmp_path,
        trials=tmp_path / "trials.jsonl",
        eligibility=tmp_path / "eligibility.json",
        pass_freeze=tmp_path / "freeze.json",
        a0_execution=tmp_path / "a0.json",
        a0r1_execution=tmp_path / "a0r1.json",
    )

    check = regression_against_a0r3e(
        paths,
        [
            {
                "trial_id": "T",
                "primary_equal_weight": {
                    "gross_bps": 1.0,
                    "cost_bps": 0.1,
                    "net_bps": 0.9,
                    "daily_sharpe": 0.2,
                    "trade_count": 3,
                },
            }
        ],
    )

    assert check["status"] == "PASS"
    assert check["max_abs_delta"] == 0.0
