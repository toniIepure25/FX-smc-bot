"""V2 family semantic registry and prospective search-space enumeration.

The twelve V1 idea families (F01-F12) are each given an explicit V2 disposition:

* ADMITTED families get a complete executable feature/signal/model definition and a
  bounded parameter grid enumerated into fully-specified :class:`StrategySpec` objects.
* REJECTED_PRE_OUTCOME families are rejected here, before any outcome is inspected,
  because a required capability (an instrument or tick semantic) is simply not in the
  frozen dataset. They are documented, never silently dropped, and never proxied.

Within admitted families, specific variants that would require an unsupported capability
(e.g. the F02 return-per-quote / F04 quote-gap-rate tick variants) are also rejected
pre-outcome. A handful of these are materialised as *reject probes* -- real
:class:`StrategySpec` objects carrying an unsupported ``required_capabilities`` entry --
so the compiler's reject path is exercised on genuine specs rather than asserted.

The trial budget is a MAXIMUM of 1200 candidate-equivalents; grids are deliberately
modest and never padded to hit a number.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v2.capabilities import SUPPORTED_INSTRUMENTS
from fx_smc_bot.research.v2.features import FEATURE_CAPABILITIES
from fx_smc_bot.research.v2.spec import (
    CostSpec,
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

SEED = 1729


def _exec(holding: int, *, exit_rule: ExitRule = ExitRule.TIME_EXIT,
          stop_bps: float = 0.0, target_bps: float = 0.0) -> ExecutionSpec:
    stop_rule = StopRule.FIXED_BPS if stop_bps > 0 else StopRule.NONE
    return ExecutionSpec(
        holding_bars=holding,
        exit_rule=exit_rule,
        stop_rule=stop_rule,
        stop_bps=stop_bps,
        target_bps=target_bps,
    )


def _caps(kind: FeatureKind, *extra: str) -> tuple[str, ...]:
    return tuple(sorted(set(FEATURE_CAPABILITIES[kind]) | set(extra)))


# --------------------------------------------------------------------------------------
# Admitted family builders
# --------------------------------------------------------------------------------------
def _f01(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for anchor in ("london_open", "new_york_open", "tokyo_open"):
        for lookback in (30, 60):
            for holding in (30, 60):
                for direction in (Direction.CONTINUATION, Direction.REVERSAL):
                    for threshold in (0.5, 1.0):
                        feat = make_feature_spec(
                            FeatureKind.SESSION_MOMENTUM,
                            price_representation=PriceRep.MID,
                            lookback_bars=lookback,
                            normalization=Normalization.ROLLING_VOL_SCALE,
                            units="vol_normalised_return",
                        )
                        specs.append(StrategySpec(
                            family_id="F01_SESSION_OPENING_MOMENTUM_REVERSAL",
                            instrument=instrument,
                            feature=feat,
                            signal=SignalSpec(direction, threshold, anchor),
                            execution=_exec(holding),
                            required_capabilities=_caps(FeatureKind.SESSION_MOMENTUM),
                        ))
    return specs


def _f02(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for lookback in (15, 30, 60):
        for direction in (Direction.CONTINUATION, Direction.REVERSAL):
            for threshold in (0.5, 1.0):
                feat = make_feature_spec(
                    FeatureKind.SIGNED_RETURN_RUN,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.NONE,
                    units="signed_run_over_sqrt_lookback",
                )
                specs.append(StrategySpec(
                    family_id="F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(direction, threshold, "all_day"),
                    execution=_exec(lookback),
                    required_capabilities=_caps(FeatureKind.SIGNED_RETURN_RUN),
                    notes="M1 signed-return run-length variant only; tick quote variants rejected.",
                ))
    return specs


def _f03(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for lookback in (30, 60, 120):
        for direction in (Direction.CONTINUATION, Direction.REVERSAL):
            for threshold in (0.5, 1.0):
                feat = make_feature_spec(
                    FeatureKind.VOLATILITY_BREAKOUT,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.NONE,
                    units="range_over_atr_minus_one",
                )
                specs.append(StrategySpec(
                    family_id="F03_VOLATILITY_BREAKOUT",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(direction, threshold, "all_day"),
                    execution=_exec(holding=lookback, stop_bps=0.0),
                    required_capabilities=_caps(FeatureKind.VOLATILITY_BREAKOUT),
                ))
    return specs


def _f04(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for lookback in (30, 60):
        for threshold in (1.5, 2.0):
            for holding in (15, 30):
                feat = make_feature_spec(
                    FeatureKind.LIQUIDITY_SHOCK_M1,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.ROLLING_ZSCORE,
                    units="spread_and_abnormal_return_zscore",
                )
                specs.append(StrategySpec(
                    family_id="F04_LIQUIDITY_SHOCK_REVERSAL",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(Direction.CONTINUATION, threshold, "all_day"),
                    execution=_exec(holding),
                    required_capabilities=_caps(FeatureKind.LIQUIDITY_SHOCK_M1),
                    notes="M1-observable liquidity proxy (spread-z + abnormal-return-z); "
                          "explicitly NOT tick liquidity; quote-rate triggers rejected.",
                ))
    return specs


def _f05(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for forecaster in ("seasonal_median", "har_linear"):
        for lookback in (30, 60):
            for direction in (Direction.CONTINUATION, Direction.REVERSAL):
                feat = make_feature_spec(
                    FeatureKind.SPREAD_ZSCORE,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.ROLLING_ZSCORE,
                    units="forecast_spread_bps_gate",
                    extra={"forecaster": forecaster, "gate_percentile": 0.8},
                )
                specs.append(StrategySpec(
                    family_id="F05_SPREAD_AWARE_EXECUTION_GATING",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(direction, 0.75, "new_york_open"),
                    execution=_exec(60),
                    required_capabilities=_caps(FeatureKind.SPREAD_ZSCORE),
                    notes="Execution-alpha gating with deterministic linear spread "
                          "forecasters; tree/EN spread forecasters deferred.",
                ))
    return specs


def _f10(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for cell in ("hour_of_session", "day_of_week"):
        for direction in (Direction.CONTINUATION, Direction.REVERSAL):
            for threshold in (0.1, 0.25):
                feat = make_feature_spec(
                    FeatureKind.SEASONALITY_CELL,
                    price_representation=PriceRep.MID,
                    lookback_bars=60,
                    normalization=Normalization.NONE,
                    units="prior_only_cell_mean_return_scaled",
                    extra={"cell": cell},
                )
                specs.append(StrategySpec(
                    family_id="F10_INTRADAY_SEASONALITY",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(direction, threshold, "all_day"),
                    execution=_exec(30),
                    required_capabilities=_caps(FeatureKind.SEASONALITY_CELL),
                    notes="Prior-only expanding cell estimation; estimates from earlier "
                          "bars/years only.",
                ))
    return specs


def _f11(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for model_class in (ModelClass.QUANTILE_BINS, ModelClass.GAUSSIAN_MIXTURE):
        for lookback in (30, 60):
            for threshold in (0.5, 1.0):
                model = ModelSpec(
                    model_class=model_class,
                    target=None,
                    feature_kinds=("realized_vol",),
                    training_window=TrainingWindow.EXPANDING,
                    min_train_observations=500,
                    retrain_cadence_bars=500,
                    embargo_bars=lookback,
                    purge_bars=lookback,
                    seed=SEED,
                    standardize_features=False,
                    action_mapping="turbulent->momentum; calm->reversal; else flat",
                    abstention_band=None,
                    n_components_or_bins=3,
                    hyperparameters=(("covariance_type", "full"), ("n_init", 1)),
                )
                feat = make_feature_spec(
                    FeatureKind.REGIME_TREND,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.ROLLING_ZSCORE,
                    units="regime_conditioned_momentum",
                )
                specs.append(StrategySpec(
                    family_id="F11_REGIME_CONDITIONED_TREND_REVERSAL",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(Direction.CONTINUATION, threshold, "all_day"),
                    execution=_exec(lookback),
                    model=model,
                    required_capabilities=_caps(FeatureKind.REGIME_TREND),
                    notes="Deterministic quantile-bin or fixed-seed GMM regime; HMM "
                          "rejected (no verified deterministic library).",
                ))
    return specs


def _f12(instrument: str) -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    for model_class in (ModelClass.LOGISTIC_REGRESSION, ModelClass.RIDGE_REGRESSION):
        target = (
            MLTarget.GROSS_MOVE_EXCEEDS_COST
            if model_class is ModelClass.LOGISTIC_REGRESSION
            else MLTarget.NET_RETURN_SIGN
        )
        is_logistic = model_class is ModelClass.LOGISTIC_REGRESSION
        for lookback in (30, 60):
            for horizon in (30, 60):
                band = (0.45, 0.55) if is_logistic else (-2.0, 2.0)
                model = ModelSpec(
                    model_class=model_class,
                    target=target,
                    feature_kinds=("ret_lb", "rvol_lb", "atr_norm", "range_comp", "spread_z",
                                   "hour_sin", "hour_cos"),
                    training_window=TrainingWindow.EXPANDING,
                    min_train_observations=1000,
                    retrain_cadence_bars=500,
                    embargo_bars=lookback,
                    purge_bars=horizon,
                    seed=SEED,
                    standardize_features=True,
                    action_mapping="score band -> long/short/abstain; else abstain flat",
                    abstention_band=band,
                    n_components_or_bins=0,
                    hyperparameters=(("label_horizon_bars", horizon), ("regularisation", 1.0)),
                )
                feat = make_feature_spec(
                    FeatureKind.ML_ABSTENTION,
                    price_representation=PriceRep.MID,
                    lookback_bars=lookback,
                    normalization=Normalization.ROLLING_ZSCORE,
                    units="model_score",
                )
                specs.append(StrategySpec(
                    family_id="F12_COST_SENSITIVE_ML_ABSTENTION",
                    instrument=instrument,
                    feature=feat,
                    signal=SignalSpec(Direction.CONTINUATION, 0.0, "all_day"),
                    execution=_exec(horizon),
                    cost=CostSpec(),
                    model=model,
                    required_capabilities=_caps(FeatureKind.ML_ABSTENTION),
                    notes="Fully deterministic linear ML (logistic/ridge) with purge+embargo; "
                          "tree/NN models deferred.",
                ))
    return specs


_ADMITTED_BUILDERS = {
    "F01_SESSION_OPENING_MOMENTUM_REVERSAL": _f01,
    "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": _f02,
    "F03_VOLATILITY_BREAKOUT": _f03,
    "F04_LIQUIDITY_SHOCK_REVERSAL": _f04,
    "F05_SPREAD_AWARE_EXECUTION_GATING": _f05,
    "F10_INTRADAY_SEASONALITY": _f10,
    "F11_REGIME_CONDITIONED_TREND_REVERSAL": _f11,
    "F12_COST_SENSITIVE_ML_ABSTENTION": _f12,
}


# Rejected-pre-outcome families (capability grounded, documented, never proxied).
REJECTED_FAMILIES: dict[str, dict[str, Any]] = {
    "F06_CROSS_PAIR_LEAD_LAG": {
        "reason": "UNSUPPORTED_INSTRUMENT_DEPENDENCY",
        "detail": "Configured edges require EURJPY/GBPJPY/AUDJPY/AUDUSD, never acquired.",
        "required_capability": "JPY_CROSS_INSTRUMENTS",
    },
    "F07_CURRENCY_FACTOR_RESIDUALS": {
        "reason": "INSUFFICIENT_CROSS_SECTION",
        "detail": "Three USD pairs cannot identify robust currency dollar factors.",
        "required_capability": "CURRENCY_FACTOR_CROSS_SECTION",
    },
    "F08_TRIANGULAR_CONSISTENCY_RESIDUALS": {
        "reason": "UNSUPPORTED_CROSS_RATE",
        "detail": "Cross rates not acquired; synthesising them zeroes the residual by "
                  "construction, leaving nothing observable to trade.",
        "required_capability": "TRIANGULAR_CROSS_RATE",
    },
    "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL": {
        "reason": "INSUFFICIENT_CROSS_SECTION",
        "detail": "Currency/JPY-beta-neutral allocations require unavailable legs; three "
                  "USD pairs are too thin a cross-section.",
        "required_capability": "JPY_CROSS_INSTRUMENTS",
    },
}

# Rejected variants inside admitted families (documented).
REJECTED_VARIANTS: list[dict[str, Any]] = [
    {"family_id": "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
     "variant": "return_per_quote / quote_mean_distance / abnormal_update_rate",
     "reason": "TICK_ONLY_SEMANTICS", "required_capability": "TICK_QUOTE_ARRIVAL_RATE"},
    {"family_id": "F04_LIQUIDITY_SHOCK_REVERSAL",
     "variant": "quote_gap_spike / abnormal_update_rate",
     "reason": "TICK_ONLY_SEMANTICS", "required_capability": "TICK_QUOTE_ARRIVAL_RATE"},
    {"family_id": "F05_SPREAD_AWARE_EXECUTION_GATING",
     "variant": "elastic_net / gradient_boosted_trees spread forecaster",
     "reason": "DEFERRED_NONLINEAR_FORECASTER", "required_capability": None},
    {"family_id": "F11_REGIME_CONDITIONED_TREND_REVERSAL",
     "variant": "hmm_frozen_state_count",
     "reason": "NO_VERIFIED_DETERMINISTIC_HMM_LIBRARY", "required_capability": None},
    {"family_id": "F12_COST_SENSITIVE_ML_ABSTENTION",
     "variant": "random_forest / gradient_boosted_trees / small_neural_network",
     "reason": "DEFERRED_NONLINEAR_MODEL", "required_capability": None},
]


def enumerate_admitted_specs() -> list[StrategySpec]:
    """Enumerate all admitted-family specs across supported instruments (deterministic)."""

    specs: list[StrategySpec] = []
    for _family, builder in sorted(_ADMITTED_BUILDERS.items()):
        for instrument in SUPPORTED_INSTRUMENTS:
            specs.extend(builder(instrument))
    return specs


def enumerate_reject_probes() -> list[StrategySpec]:
    """Real StrategySpec objects that require an unsupported capability.

    These exercise the compiler's REJECTED_PRE_OUTCOME path on genuine specs. They are
    never evaluated on data and never inflate the multiple-testing denominator.
    """

    probes: list[StrategySpec] = []
    base_instrument = SUPPORTED_INSTRUMENTS[0]
    # F02 tick "return-per-quote" variant: requires quote arrival rate (unsupported).
    tick_feat = make_feature_spec(
        FeatureKind.SIGNED_RETURN_RUN,
        price_representation=PriceRep.MID,
        lookback_bars=30,
        normalization=Normalization.NONE,
        units="return_per_quote",
    )
    probes.append(StrategySpec(
        family_id="F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
        instrument=base_instrument,
        feature=tick_feat,
        signal=SignalSpec(Direction.CONTINUATION, 1.0, "all_day"),
        execution=_exec(30),
        required_capabilities=("M1_RETURNS", "TICK_QUOTE_ARRIVAL_RATE"),
        notes="Reject probe: return-per-quote requires tick quote arrival rate.",
    ))
    # F04 quote-gap variant: requires tick microstructure (unsupported).
    gap_feat = make_feature_spec(
        FeatureKind.LIQUIDITY_SHOCK_M1,
        price_representation=PriceRep.MID,
        lookback_bars=30,
        normalization=Normalization.ROLLING_ZSCORE,
        units="quote_gap_spike",
    )
    probes.append(StrategySpec(
        family_id="F04_LIQUIDITY_SHOCK_REVERSAL",
        instrument=base_instrument,
        feature=gap_feat,
        signal=SignalSpec(Direction.CONTINUATION, 2.0, "all_day"),
        execution=_exec(15),
        required_capabilities=("M1_SPREAD", "TICK_LEVEL_MICROSTRUCTURE"),
        notes="Reject probe: quote-gap spike requires tick-level microstructure.",
    ))
    return probes


def family_semantic_registry_payload() -> dict[str, Any]:
    admitted = enumerate_admitted_specs()
    by_family: dict[str, int] = {}
    for spec in admitted:
        by_family[spec.family_id] = by_family.get(spec.family_id, 0) + 1
    return {
        "artifact_id": "A0R4_FAMILY_SEMANTIC_REGISTRY_V1",
        "admitted_families": {
            fid: {
                "feature_kind": _feature_kind_for(fid),
                "candidate_specs": by_family.get(fid, 0),
            }
            for fid in sorted(_ADMITTED_BUILDERS)
        },
        "rejected_families": REJECTED_FAMILIES,
        "rejected_variants": REJECTED_VARIANTS,
        "admitted_family_count": len(_ADMITTED_BUILDERS),
        "rejected_family_count": len(REJECTED_FAMILIES),
        "supported_instruments": list(SUPPORTED_INSTRUMENTS),
    }


def _feature_kind_for(family_id: str) -> str:
    mapping = {
        "F01_SESSION_OPENING_MOMENTUM_REVERSAL": FeatureKind.SESSION_MOMENTUM,
        "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": FeatureKind.SIGNED_RETURN_RUN,
        "F03_VOLATILITY_BREAKOUT": FeatureKind.VOLATILITY_BREAKOUT,
        "F04_LIQUIDITY_SHOCK_REVERSAL": FeatureKind.LIQUIDITY_SHOCK_M1,
        "F05_SPREAD_AWARE_EXECUTION_GATING": FeatureKind.SPREAD_ZSCORE,
        "F10_INTRADAY_SEASONALITY": FeatureKind.SEASONALITY_CELL,
        "F11_REGIME_CONDITIONED_TREND_REVERSAL": FeatureKind.REGIME_TREND,
        "F12_COST_SENSITIVE_ML_ABSTENTION": FeatureKind.ML_ABSTENTION,
    }
    return mapping[family_id].value
