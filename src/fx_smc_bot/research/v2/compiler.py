"""Deterministic semantic compiler: StrategySpec -> executable trial or rejection.

The compiler has exactly two scientifically-meaningful terminal states:

* ``ADMITTED_EXECUTABLE`` -- the spec is complete, capability-supported and deterministic;
  it can be executed without any interpretation.
* ``REJECTED_PRE_OUTCOME`` -- the spec cannot be fully specified against the frozen
  dataset (missing capability, unsupported instrument, incomplete/ambiguous field, or a
  non-deterministic model). It is rejected *before* any outcome is inspected.

There is deliberately no ``BLOCKED`` state. A strategy that cannot be completely specified
is rejected here rather than carried into discovery as an unresolved semantic blocker.
This is the structural fix for the V1 recurring-blocker failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fx_smc_bot.research.v2.capabilities import SUPPORTED_INSTRUMENTS, check_required
from fx_smc_bot.research.v2.features import FEATURE_CAPABILITIES
from fx_smc_bot.research.v2.spec import (
    ExitRule,
    FeatureKind,
    ModelClass,
    StopRule,
    StrategySpec,
)

ADMITTED = "ADMITTED_EXECUTABLE"
REJECTED = "REJECTED_PRE_OUTCOME"

_DETERMINISTIC_MODEL_CLASSES = {
    ModelClass.QUANTILE_BINS,
    ModelClass.GAUSSIAN_MIXTURE,
    ModelClass.LOGISTIC_REGRESSION,
    ModelClass.RIDGE_REGRESSION,
}
_REGIME_MODELS = {ModelClass.QUANTILE_BINS, ModelClass.GAUSSIAN_MIXTURE}
_ML_MODELS = {ModelClass.LOGISTIC_REGRESSION, ModelClass.RIDGE_REGRESSION}
_KNOWN_SESSIONS = {
    "all_day", "london_open", "new_york_open", "tokyo_open", "london_1600_fixing_window",
}


@dataclass(frozen=True, slots=True)
class CompileResult:
    family_id: str
    instrument: str
    terminal_state: str
    spec_hash: str
    reasons: tuple[str, ...]
    spec: StrategySpec
    canonical_config: dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.terminal_state == ADMITTED


def _completeness_reasons(spec: StrategySpec) -> list[str]:
    reasons: list[str] = []
    feat = spec.feature
    if feat.lookback_bars < 1:
        reasons.append("feature.lookback_bars < 1")
    if feat.warmup_bars < feat.lookback_bars:
        reasons.append("feature.warmup_bars < lookback_bars")
    if feat.min_observations < 1:
        reasons.append("feature.min_observations < 1")
    if feat.normalization_lookback_bars < 1:
        reasons.append("feature.normalization_lookback_bars < 1")
    if not feat.units:
        reasons.append("feature.units missing")

    sig = spec.signal
    if sig.entry_threshold < 0:
        reasons.append("signal.entry_threshold < 0")
    if sig.min_signal_latency_bars < 1:
        reasons.append("signal.min_signal_latency_bars < 1 (no synthetic same-bar fill)")
    if sig.session_filter not in _KNOWN_SESSIONS:
        reasons.append(f"signal.session_filter unknown: {sig.session_filter!r}")

    exe = spec.execution
    if exe.holding_bars < 1:
        reasons.append("execution.holding_bars < 1")
    if exe.exit_rule not in (ExitRule.TIME_EXIT, ExitRule.OPPOSITE_SIGNAL):
        reasons.append("execution.exit_rule invalid")
    if exe.stop_rule is StopRule.FIXED_BPS and exe.stop_bps <= 0:
        reasons.append("execution.stop_rule FIXED_BPS requires stop_bps > 0")
    if exe.stop_rule is StopRule.NONE and exe.stop_bps != 0:
        reasons.append("execution.stop_rule NONE requires stop_bps == 0")
    if exe.target_bps < 0:
        reasons.append("execution.target_bps < 0")
    if not exe.intraday_only:
        reasons.append("execution.intraday_only must be True for V2")
    if exe.missing_quote_policy != "no_synthetic_fill":
        reasons.append("execution.missing_quote_policy must be no_synthetic_fill")
    return reasons


def _model_reasons(spec: StrategySpec) -> list[str]:
    reasons: list[str] = []
    kind = spec.feature.kind
    needs_model = kind in (FeatureKind.REGIME_TREND, FeatureKind.ML_ABSTENTION)
    if needs_model and spec.model is None:
        reasons.append(f"feature kind {kind.value} requires a ModelSpec")
        return reasons
    if not needs_model:
        if spec.model is not None:
            reasons.append(f"feature kind {kind.value} must not carry a ModelSpec")
        return reasons

    model = spec.model
    assert model is not None
    if model.model_class not in _DETERMINISTIC_MODEL_CLASSES:
        reasons.append(f"model_class {model.model_class.value} is not in deterministic allowlist")
    if kind is FeatureKind.REGIME_TREND and model.model_class not in _REGIME_MODELS:
        reasons.append("regime family requires quantile_bins or gaussian_mixture")
    if kind is FeatureKind.ML_ABSTENTION:
        if model.model_class not in _ML_MODELS:
            reasons.append("ML family requires logistic_regression or ridge_regression")
        if model.target is None:
            reasons.append("ML family requires an explicit target")
        if model.abstention_band is None:
            reasons.append("ML family requires an explicit abstention_band")
    if model.min_train_observations < 1:
        reasons.append("model.min_train_observations < 1")
    if model.retrain_cadence_bars < 1:
        reasons.append("model.retrain_cadence_bars < 1")
    if model.embargo_bars < 0 or model.purge_bars < 0:
        reasons.append("model embargo/purge must be >= 0")
    if kind is FeatureKind.ML_ABSTENTION and model.purge_bars < 1:
        reasons.append("ML family requires purge_bars >= 1 to separate label window")
    if model.n_components_or_bins < 0:
        reasons.append("model.n_components_or_bins < 0")
    if kind is FeatureKind.REGIME_TREND and model.n_components_or_bins < 2:
        reasons.append("regime family requires >= 2 components/bins")
    return reasons


def compile_spec(spec: StrategySpec) -> CompileResult:
    """Compile a single spec to its terminal state. Deterministic and side-effect free."""

    reasons: list[str] = []

    if spec.instrument not in SUPPORTED_INSTRUMENTS:
        reasons.append(f"instrument {spec.instrument!r} not in supported dataset")

    # Feature-kind implied capabilities must be supported and consistent with declaration.
    implied = FEATURE_CAPABILITIES.get(spec.feature.kind, ())
    ok_implied, missing_implied = check_required(implied)
    if not ok_implied:
        reasons.append(f"feature capabilities unsupported: {sorted(missing_implied)}")

    ok_declared, missing_declared = check_required(spec.required_capabilities)
    if not ok_declared:
        reasons.append(f"declared capabilities unsupported: {sorted(missing_declared)}")

    reasons.extend(_completeness_reasons(spec))
    reasons.extend(_model_reasons(spec))

    terminal = ADMITTED if not reasons else REJECTED
    return CompileResult(
        family_id=spec.family_id,
        instrument=spec.instrument,
        terminal_state=terminal,
        spec_hash=spec.spec_hash(),
        reasons=tuple(reasons),
        spec=spec,
        canonical_config=spec.canonical_dict() if terminal == ADMITTED else {},
    )


def compile_all(specs: list[StrategySpec]) -> tuple[list[CompileResult], list[CompileResult]]:
    """Compile many specs, returning ``(admitted, rejected)`` deterministically."""

    admitted: list[CompileResult] = []
    rejected: list[CompileResult] = []
    for spec in specs:
        result = compile_spec(spec)
        (admitted if result.admitted else rejected).append(result)
    return admitted, rejected
