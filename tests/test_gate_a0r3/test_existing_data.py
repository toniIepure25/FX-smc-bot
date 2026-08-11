from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fx_smc_bot.research.a0r3_existing_data import (
    Paths,
    execution_returns_bps,
    load_month_side_data,
    prospective_split_amendment,
    trial_eligibility,
)
from fx_smc_bot.research.a0r3b_pass_strata import (
    MarketReadGuard,
    evidence_tier,
    pass_strata_trial_eligibility,
    required_pairs_for_trial,
    topology_units,
)


def test_split_amendment_quarantines_2018_plus(tmp_path: Path) -> None:
    trial_file = tmp_path / "trial_materialization_v2.jsonl"
    trial_file.write_text('{"trial_id":"A","candidate_equivalent_weight":1}\n')
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path / "raw",
        results=tmp_path / "results",
        docs=tmp_path / "docs",
        trials=trial_file,
    )

    amendment = prospective_split_amendment(paths)

    assert amendment["boundaries"]["exploratory_discovery"] == ["2015-01-01", "2017-12-31"]
    assert amendment["access_policy"]["metadata_only_years"] == [2018, 2019]
    assert 2025 in amendment["access_policy"]["forbidden_market_or_outcome_years"]


def test_load_month_side_data_rejects_2018_plus(tmp_path: Path) -> None:
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path / "raw",
        results=tmp_path / "results",
        docs=tmp_path / "docs",
        trials=tmp_path / "trials.jsonl",
    )

    with pytest.raises(ValueError, match="A0R3_2018_PLUS_PRICE_DATA_ACCESS_FORBIDDEN"):
        load_month_side_data(paths, "EURUSD", "bid", 2018, 1)


def test_trial_eligibility_filters_topology_without_replacement() -> None:
    trials = [
        {
            "trial_id": "A",
            "family_id": "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
            "candidate_equivalent_weight": 1,
            "configuration_sha256": "abc",
            "full_configuration": {
                "instrument_or_portfolio_scope": "EURUSD",
                "required_inputs": ["session labels", "M1 signed mid return"],
            },
        },
        {
            "trial_id": "B",
            "family_id": "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
            "candidate_equivalent_weight": 1,
            "configuration_sha256": "def",
            "full_configuration": {
                "instrument_or_portfolio_scope": "nine_pair_portfolio",
                "required_inputs": ["session labels"],
            },
        },
    ]

    out = trial_eligibility(trials)

    assert out["eligible_trials"] == 1
    assert out["ineligible_trials"] == 1
    assert out["rows"][1]["ineligibility_reasons"] == ["scope_requires_nine_pair_portfolio"]


def test_execution_returns_apply_one_bar_latency_and_cost_stress() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2017-01-03 12:00", periods=4, freq="min", tz="UTC"),
            "bid_close": [1.0000, 1.0009, 1.0018, 1.0017],
            "ask_close": [1.0002, 1.0011, 1.0020, 1.0019],
            "mid_close": [1.0001, 1.0010, 1.0019, 1.0018],
            "spread": [0.0002, 0.0002, 0.0002, 0.0002],
        }
    )
    signal = pd.Series([1, 1, 1, 0])

    base = execution_returns_bps(frame, signal, 1.0)
    stressed = execution_returns_bps(frame, signal, 2.0)

    assert base.iloc[0] <= 0.0
    assert base.sum() > stressed.sum()


def test_a0r3b_requires_complete_case_pass_strata_without_substitution() -> None:
    trial = {
        "trial_id": "C",
        "family_id": "F03_VOLATILITY_BREAKOUT",
        "candidate_equivalent_weight": 1,
        "configuration_sha256": "ghi",
        "full_configuration": {
            "instrument_or_portfolio_scope": "GBPUSD",
            "required_inputs": ["M1 signed mid return", "rolling realized variance"],
        },
    }
    unavailable = {
        **trial,
        "trial_id": "D",
        "full_configuration": {
            "instrument_or_portfolio_scope": "EURUSD",
            "required_inputs": ["M1 signed mid return"],
        },
    }

    out = pass_strata_trial_eligibility([trial, unavailable])

    assert out["eligible_trials"] == 2
    assert out["rows"][0]["eligible_topology_units"] == [
        {
            "topology_id": "GBPUSD:2017",
            "year": 2017,
            "legs": ["GBPUSD"],
            "evaluation_pair": "GBPUSD",
        }
    ]
    assert out["rows"][1]["eligible_topology_units"][0]["topology_id"] == "EURUSD:2015"


def test_a0r3b_multivariate_requires_simultaneous_pass_legs() -> None:
    config = {
        "instrument_or_portfolio_scope": "GBPUSD",
        "required_inputs": ["lagged cross-pair synchronized returns"],
    }

    required, reasons = required_pairs_for_trial(config, "F07_CURRENCY_FACTOR_RESIDUALS")

    assert not reasons
    assert required == {"EURUSD", "GBPUSD", "USDJPY"}
    assert topology_units(required, "GBPUSD") == []


def test_a0r3b_market_read_guard_rejects_holdout_year(tmp_path: Path) -> None:
    paths = Paths(
        repo=tmp_path,
        raw=tmp_path / "raw",
        results=tmp_path / "results",
        docs=tmp_path / "docs",
        trials=tmp_path / "trials.jsonl",
    )
    guard = MarketReadGuard()

    with pytest.raises(ValueError, match="A0R3B_2018_PLUS_MARKET_DATA_ACCESS_FORBIDDEN"):
        guard.read_side(paths, "EURUSD", "bid", 2018, 1)


def test_a0r3b_single_unit_gets_single_stratum_label() -> None:
    row = {
        "topology_unit_count": 1,
        "cost_stress": {"survives_2_0x": True},
        "cross_stratum_stability": 1.0,
    }

    assert evidence_tier(row) == "SINGLE_STRATUM_EXPLORATORY_LEAD"
