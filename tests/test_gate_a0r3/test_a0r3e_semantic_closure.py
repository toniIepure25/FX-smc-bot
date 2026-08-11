from __future__ import annotations

import pandas as pd

from fx_smc_bot.research.a0r3e_semantic_closure import (
    certify_trial_a0r3e,
    rank_review,
    rank_survivors,
    signal_f02,
)


def _f02_trial(
    *, stop_rule: str = "none", data_variant: str = "M1-compatible direction-run"
) -> dict:
    return {
        "trial_id": "A0R1-02-X",
        "family_id": "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
        "configuration_sha256": "sha",
        "full_configuration": {
            "frozen_categories": {
                "data_variants": data_variant,
                "horizons": 5,
                "variants": "continuation",
            },
            "required_inputs": ["M1 signed mid return", "rolling spread statistics"],
            "stop_rule": stop_rule,
            "exit_rule": "time_exit",
            "lookback": 3,
            "entry_threshold": 0.5,
            "variant": "continuation",
            "holding_horizon": 5,
            "session_anchor": "tokyo",
            "target_horizon": 5,
            "model_class": "none",
        },
    }


def test_f02_m1_direction_run_without_atr_stop_certifies() -> None:
    status, blockers, matrix = certify_trial_a0r3e(_f02_trial())

    assert status == "CERTIFIED_EXECUTABLE"
    assert blockers == []
    assert any(
        row["field"] == "session_anchor" and row["status"] == "DOCUMENTED_INERT"
        for row in matrix
    )


def test_f02_tick_only_and_atr_stop_remain_blocked() -> None:
    status, blockers, _ = certify_trial_a0r3e(
        _f02_trial(stop_rule="one_atr_adverse", data_variant="tick-only quote-arrival")
    )

    assert status == "IMPLEMENTATION_BLOCKED"
    assert any("required_inputs" in blocker for blocker in blockers)
    assert any("stop_rule" in blocker for blocker in blockers)


def test_f02_signal_continuation_and_exhaustion_are_distinct() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2017-01-01", periods=6, freq="min", tz="UTC"),
            "mid_return": [0.0, 0.1, 0.1, 0.1, -0.1, -0.1],
        }
    )
    cont = _f02_trial()["full_configuration"]
    exh = {**cont, "variant": "exhaustion"}

    continuation = signal_f02(frame, cont)
    exhaustion = signal_f02(frame, exh)

    assert continuation.iloc[3] == 1
    assert exhaustion.iloc[3] == -1


def _row(trial_id: str, net: float, stress: bool) -> dict:
    return {
        "trial_id": trial_id,
        "family_id": "F01",
        "primary_equal_weight": {"net_bps": net, "daily_sharpe": net, "trade_count": 1},
        "corrected_significance": {"bh_fdr_p": 1.0},
        "cost_stress": {"survives_1_5x": stress, "survives_2_0x": stress},
    }


def test_negative_net_candidates_are_review_only_not_survivors() -> None:
    rows = [_row("neg", -1.0, True), _row("pos_no_stress", 1.0, False)]

    assert [row["trial_id"] for row in rank_review(rows)] == ["pos_no_stress", "neg"]
    assert rank_survivors(rows) == []


def test_positive_cost_robust_candidate_can_be_survivor() -> None:
    rows = [_row("survivor", 1.0, True)]

    assert rank_survivors(rows)[0]["trial_id"] == "survivor"
