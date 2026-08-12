"""Causality and determinism tests for model families (F11 regime, F12 ML)."""

from __future__ import annotations

import numpy as np

from fx_smc_bot.research.v2.signals import generate_signal
from fx_smc_bot.research.v2.spec import (
    Direction,
    ExecutionSpec,
    ExitRule,
    FeatureKind,
    MLTarget,
    ModelClass,
    ModelSpec,
    Normalization,
    PriceRep,
    SignalSpec,
    StopRule,
    StrategySpec,
    TrainingWindow,
    make_feature_spec,
)
from fx_smc_bot.research.v2.synthetic import synthetic_frame


def _ml_spec() -> StrategySpec:
    model = ModelSpec(
        model_class=ModelClass.LOGISTIC_REGRESSION,
        target=MLTarget.NET_RETURN_SIGN,
        feature_kinds=("ret_lb", "rvol_lb", "atr_norm", "range_comp", "spread_z",
                       "hour_sin", "hour_cos"),
        training_window=TrainingWindow.EXPANDING,
        min_train_observations=80,
        retrain_cadence_bars=40,
        embargo_bars=5,
        purge_bars=5,
        seed=1729,
        standardize_features=True,
        action_mapping="band",
        abstention_band=(0.45, 0.55),
        n_components_or_bins=0,
        hyperparameters=(("label_horizon_bars", 5), ("regularisation", 1.0)),
    )
    feat = make_feature_spec(
        FeatureKind.ML_ABSTENTION, price_representation=PriceRep.MID, lookback_bars=10,
        normalization=Normalization.ROLLING_ZSCORE, units="model_score",
    )
    return StrategySpec(
        family_id="F12_COST_SENSITIVE_ML_ABSTENTION", instrument="EURUSD", feature=feat,
        signal=SignalSpec(Direction.CONTINUATION, 0.0, "all_day"),
        execution=ExecutionSpec(holding_bars=5, exit_rule=ExitRule.TIME_EXIT,
                                stop_rule=StopRule.NONE, stop_bps=0.0, target_bps=0.0),
        model=model,
    )


def _regime_spec() -> StrategySpec:
    model = ModelSpec(
        model_class=ModelClass.GAUSSIAN_MIXTURE, target=None, feature_kinds=("realized_vol",),
        training_window=TrainingWindow.EXPANDING,
        min_train_observations=80, retrain_cadence_bars=40, embargo_bars=5, purge_bars=5,
        seed=1729, standardize_features=False, action_mapping="regime", abstention_band=None,
        n_components_or_bins=3, hyperparameters=(("covariance_type", "full"), ("n_init", 1)),
    )
    feat = make_feature_spec(
        FeatureKind.REGIME_TREND, price_representation=PriceRep.MID, lookback_bars=10,
        normalization=Normalization.ROLLING_ZSCORE, units="regime_momentum",
    )
    return StrategySpec(
        family_id="F11_REGIME_CONDITIONED_TREND_REVERSAL", instrument="EURUSD", feature=feat,
        signal=SignalSpec(Direction.CONTINUATION, 0.5, "all_day"),
        execution=ExecutionSpec(holding_bars=10, exit_rule=ExitRule.TIME_EXIT,
                                stop_rule=StopRule.NONE, stop_bps=0.0, target_bps=0.0),
        model=model,
    )


def test_ml_signal_is_deterministic() -> None:
    spec = _ml_spec()
    frame = synthetic_frame("EURUSD", n_bars=400, seed=7)
    s1 = generate_signal(frame, spec)
    s2 = generate_signal(frame, spec)
    assert s1.equals(s2)


def test_ml_signal_no_future_leakage() -> None:
    spec = _ml_spec()
    frame = synthetic_frame("EURUSD", n_bars=400, seed=7)
    base = generate_signal(frame, spec).to_numpy()
    j = 250
    mutated = frame.copy()
    for col in ("mid_close", "mid_high", "mid_low", "mid_return", "spread"):
        mutated.loc[mutated.index[j:], col] = mutated.loc[mutated.index[j:], col] * 1.3
    mut = generate_signal(mutated, spec).to_numpy()
    # signals strictly before the mutated bar cannot change (causality)
    assert np.array_equal(base[:j], mut[:j])


def test_ml_produces_no_signal_before_min_training() -> None:
    spec = _ml_spec()
    frame = synthetic_frame("EURUSD", n_bars=400, seed=7)
    sig = generate_signal(frame, spec).to_numpy()
    guard = 5 + 5 + 5  # horizon + purge + embargo
    warmup = spec.model.min_train_observations + guard  # type: ignore[union-attr]
    assert np.all(sig[:warmup] == 0)


def test_regime_signal_is_deterministic() -> None:
    spec = _regime_spec()
    frame = synthetic_frame("EURUSD", n_bars=400, seed=11)
    s1 = generate_signal(frame, spec)
    s2 = generate_signal(frame, spec)
    assert s1.equals(s2)


def test_regime_signal_no_future_leakage() -> None:
    spec = _regime_spec()
    frame = synthetic_frame("EURUSD", n_bars=400, seed=11)
    base = generate_signal(frame, spec).to_numpy()
    j = 250
    mutated = frame.copy()
    for col in ("mid_close", "mid_high", "mid_low", "mid_return", "spread"):
        mutated.loc[mutated.index[j:], col] = mutated.loc[mutated.index[j:], col] * 1.3
    mut = generate_signal(mutated, spec).to_numpy()
    assert np.array_equal(base[:j], mut[:j])
