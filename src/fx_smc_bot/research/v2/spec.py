"""Canonical typed strategy specification schema for V2.

A :class:`StrategySpec` is an immutable, fully deterministic description of a strategy.
The schema is intentionally strict: every behavioural axis required to execute a trial
without interpretation is a typed field. Incomplete or ambiguous strategies cannot be
represented, and the compiler (see :mod:`compiler`) rejects any spec that fails
validation *before* any outcome data is inspected.

Design intent: reproduce the exact deterministic-execution surface enumerated in the
V2 protocol -- input bars, price representation, bid/ask usage, feature formula and
units, lookback, warm-up, normalization, threshold, direction, signal timestamp,
entry eligibility/latency/side, holding/exit/stop/target rules, same-bar behaviour,
missing-quote behaviour, session/rollover/timezone behaviour, and (for model families)
the full training/validation/embargo/purge/seed/action surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class BarInterval(str, Enum):
    M1 = "M1"
    M5 = "M5"


class PriceRep(str, Enum):
    MID = "mid"
    BID = "bid"
    ASK = "ask"


class FeatureKind(str, Enum):
    SESSION_MOMENTUM = "session_momentum"
    SIGNED_RETURN_RUN = "signed_return_run"
    VOLATILITY_BREAKOUT = "volatility_breakout"
    RANGE_COMPRESSION_EXPANSION = "range_compression_expansion"
    SPREAD_ZSCORE = "spread_zscore"
    LIQUIDITY_SHOCK_M1 = "liquidity_shock_m1"
    SEASONALITY_CELL = "seasonality_cell"
    REGIME_TREND = "regime_trend"
    ML_ABSTENTION = "ml_abstention"


class Normalization(str, Enum):
    NONE = "none"
    ROLLING_ZSCORE = "rolling_zscore"
    ROLLING_VOL_SCALE = "rolling_vol_scale"


class Direction(str, Enum):
    CONTINUATION = "continuation"
    REVERSAL = "reversal"


class ExitRule(str, Enum):
    TIME_EXIT = "time_exit"
    OPPOSITE_SIGNAL = "opposite_signal"


class StopRule(str, Enum):
    NONE = "none"
    FIXED_BPS = "fixed_bps"


class SameBarPolicy(str, Enum):
    ADVERSE_FIRST = "adverse_first"


class ModelClass(str, Enum):
    NONE = "none"
    QUANTILE_BINS = "quantile_bins"
    GAUSSIAN_MIXTURE = "gaussian_mixture"
    LOGISTIC_REGRESSION = "logistic_regression"
    RIDGE_REGRESSION = "ridge_regression"


class MLTarget(str, Enum):
    GROSS_MOVE_EXCEEDS_COST = "gross_move_exceeds_frozen_round_trip_cost"
    NET_RETURN_SIGN = "net_executable_return_sign"


class TrainingWindow(str, Enum):
    EXPANDING = "expanding_prior_only"
    ROLLING = "rolling_prior_only"


def _sorted_extra(extra: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(extra.items()))


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    kind: FeatureKind
    price_representation: PriceRep
    bar_interval: BarInterval
    lookback_bars: int
    warmup_bars: int
    min_observations: int
    normalization: Normalization
    normalization_lookback_bars: int
    units: str
    # feature-specific deterministic parameters, order-independent
    extra: tuple[tuple[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["price_representation"] = self.price_representation.value
        data["bar_interval"] = self.bar_interval.value
        data["normalization"] = self.normalization.value
        data["extra"] = {k: v for k, v in self.extra}
        return data


@dataclass(frozen=True, slots=True)
class SignalSpec:
    direction: Direction
    entry_threshold: float
    session_filter: str  # session anchor label or "all_day"
    signal_timestamp: str = "bar_close_t"
    min_signal_latency_bars: int = 1

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction.value
        return data


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    holding_bars: int
    exit_rule: ExitRule
    stop_rule: StopRule
    stop_bps: float
    target_bps: float
    entry_price_side: str = "side_correct_long_ask_short_bid"
    exit_price_side: str = "side_correct_long_bid_short_ask"
    same_bar_policy: SameBarPolicy = SameBarPolicy.ADVERSE_FIRST
    mandatory_flat_ny: str = "16:45"
    rollover_exclusion_ny: str = "16:30"
    new_entry_resume_ny: str = "17:30"
    intraday_only: bool = True
    missing_quote_policy: str = "no_synthetic_fill"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["exit_rule"] = self.exit_rule.value
        data["stop_rule"] = self.stop_rule.value
        data["same_bar_policy"] = self.same_bar_policy.value
        return data


@dataclass(frozen=True, slots=True)
class CostSpec:
    base_commission_slippage_bps_per_fill: float = 0.10
    spread_cost: str = "side_correct_bid_ask_in_fills"
    stress_multipliers: tuple[float, ...] = (1.5, 2.0)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stress_multipliers"] = list(self.stress_multipliers)
        return data


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Complete model surface for regime (F11) and cost-sensitive ML (F12) families."""

    model_class: ModelClass
    target: MLTarget | None
    feature_kinds: tuple[str, ...]
    training_window: TrainingWindow
    min_train_observations: int
    retrain_cadence_bars: int
    embargo_bars: int
    purge_bars: int
    seed: int
    standardize_features: bool
    action_mapping: str
    abstention_band: tuple[float, float] | None
    n_components_or_bins: int
    hyperparameters: tuple[tuple[str, Any], ...]
    failure_behavior: str = "abstain_flat_no_trade"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["model_class"] = self.model_class.value
        data["target"] = self.target.value if self.target else None
        data["training_window"] = self.training_window.value
        data["abstention_band"] = (
            list(self.abstention_band) if self.abstention_band is not None else None
        )
        data["hyperparameters"] = {k: v for k, v in self.hyperparameters}
        data["feature_kinds"] = list(self.feature_kinds)
        return data


@dataclass(frozen=True, slots=True)
class StrategySpec:
    family_id: str
    instrument: str
    feature: FeatureSpec
    signal: SignalSpec
    execution: ExecutionSpec
    cost: CostSpec = field(default_factory=CostSpec)
    model: ModelSpec | None = None
    required_capabilities: tuple[str, ...] = ()
    notes: str = ""

    def canonical_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serialisable representation used for hashing."""

        payload: dict[str, Any] = {
            "family_id": self.family_id,
            "instrument": self.instrument,
            "feature": self.feature.as_dict(),
            "signal": self.signal.as_dict(),
            "execution": self.execution.as_dict(),
            "cost": self.cost.as_dict(),
            "model": self.model.as_dict() if self.model else None,
            "required_capabilities": sorted(self.required_capabilities),
        }
        return payload

    def spec_hash(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_feature_spec(
    kind: FeatureKind,
    *,
    price_representation: PriceRep,
    lookback_bars: int,
    normalization: Normalization,
    units: str,
    warmup_bars: int | None = None,
    min_observations: int | None = None,
    normalization_lookback_bars: int | None = None,
    bar_interval: BarInterval = BarInterval.M1,
    extra: dict[str, Any] | None = None,
) -> FeatureSpec:
    """Helper that fills warm-up/min-observation defaults deterministically."""

    warmup = warmup_bars if warmup_bars is not None else lookback_bars
    min_obs = min_observations if min_observations is not None else max(3, lookback_bars // 3)
    norm_lb = (
        normalization_lookback_bars
        if normalization_lookback_bars is not None
        else max(lookback_bars, 20)
    )
    return FeatureSpec(
        kind=kind,
        price_representation=price_representation,
        bar_interval=bar_interval,
        lookback_bars=lookback_bars,
        warmup_bars=warmup,
        min_observations=min_obs,
        normalization=normalization,
        normalization_lookback_bars=norm_lb,
        units=units,
        extra=_sorted_extra(extra or {}),
    )
