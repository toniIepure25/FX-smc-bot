"""Causal Gate Q.0 polarity model and purged nested walk-forward selection."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import log_loss  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

from fx_smc_bot.research.quant_polarity import (
    FEATURES,
    HYPERPARAMETERS,
    PROHIBITED_FEATURES,
    canonical_json_sha256,
)

SEED = 1729
CATEGORICAL_FEATURES = (
    "source_policy_family",
    "source_signal_direction",
    "session",
)
BASE_NUMERIC_FEATURES = tuple(
    feature
    for feature in FEATURES
    if feature not in CATEGORICAL_FEATURES
    and feature
    not in {
        "source_policy_event_quality_scalars",
        "missing_indicator_per_optional_event_quality_scalar",
    }
)


class PolarityAction(str, Enum):
    ORIGINAL = "ORIGINAL"
    INVERSE = "INVERSE"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True)
class LabeledSignal:
    decision_time: datetime
    label_end_time: datetime
    instrument: str
    features: dict[str, Any]
    label: PolarityAction


@dataclass(frozen=True)
class PurgedFold:
    fold_id: str
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_latest_decision: datetime
    train_latest_label_end: datetime
    test_earliest_decision: datetime
    purge_cutoff: datetime
    embargo_days: int


@dataclass(frozen=True)
class HyperparameterSelection:
    inverse_regularization_c: float
    l1_ratio: float
    mean_log_loss: float
    fold_log_losses: tuple[float, ...]
    selection_hash: str


@dataclass(frozen=True)
class OofPrediction:
    signal_index: int
    fold_id: str
    original_probability: float
    inverse_probability: float
    abstain_probability: float
    action: PolarityAction
    model_hash: str
    hyperparameter_selection_hash: str


def construct_label(original_net_r: float, inverse_net_r: float) -> PolarityAction:
    if original_net_r > 0 and original_net_r > inverse_net_r:
        return PolarityAction.ORIGINAL
    if inverse_net_r > 0 and inverse_net_r > original_net_r:
        return PolarityAction.INVERSE
    return PolarityAction.ABSTAIN


def subtract_fx_trading_days(value: datetime, days: int) -> datetime:
    result = value
    remaining = days
    while remaining:
        result -= timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def annual_purged_forward_folds(
    signals: Sequence[LabeledSignal],
    *,
    purge_dependency: timedelta,
    embargo_days: int = 5,
) -> tuple[PurgedFold, ...]:
    """Create annual 2016-2019 tests using strictly earlier observations."""
    if embargo_days != 5:
        raise ValueError("Gate Q.0 requires exactly five FX trading days of embargo")
    folds: list[PurgedFold] = []
    for test_year in (2016, 2017, 2018, 2019):
        test_indices = tuple(
            index for index, signal in enumerate(signals) if signal.decision_time.year == test_year
        )
        if not test_indices:
            continue
        test_start = min(signals[index].decision_time for index in test_indices)
        purge_cutoff = subtract_fx_trading_days(test_start, embargo_days) - purge_dependency
        train_indices = tuple(
            index
            for index, signal in enumerate(signals)
            if signal.decision_time < purge_cutoff and signal.label_end_time < purge_cutoff
        )
        if not train_indices:
            continue
        fold = PurgedFold(
            fold_id=f"OUTER_{test_year}",
            train_indices=train_indices,
            test_indices=test_indices,
            train_latest_decision=max(signals[index].decision_time for index in train_indices),
            train_latest_label_end=max(signals[index].label_end_time for index in train_indices),
            test_earliest_decision=test_start,
            purge_cutoff=purge_cutoff,
            embargo_days=embargo_days,
        )
        if fold.train_latest_label_end >= fold.purge_cutoff:
            raise ValueError("Purging failed to remove an overlapping label horizon")
        if fold.train_latest_decision >= fold.test_earliest_decision:
            raise ValueError("Outer-test observations entered fitting")
        folds.append(fold)
    return tuple(folds)


def temporal_inner_splits(
    signals: Sequence[LabeledSignal],
    indices: Sequence[int],
    *,
    purge_dependency: timedelta,
    embargo_days: int = 5,
    split_count: int = 3,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    ordered = sorted(indices, key=lambda index: signals[index].decision_time)
    if len(ordered) < split_count + 2:
        return ()
    boundaries = np.linspace(0, len(ordered), split_count + 2, dtype=int)
    splits: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for split_number in range(1, split_count + 1):
        test = ordered[boundaries[split_number] : boundaries[split_number + 1]]
        if not test:
            continue
        test_start = signals[test[0]].decision_time
        cutoff = subtract_fx_trading_days(test_start, embargo_days) - purge_dependency
        train = tuple(
            index
            for index in ordered[: boundaries[split_number]]
            if signals[index].decision_time < cutoff and signals[index].label_end_time < cutoff
        )
        if train:
            splits.append((train, tuple(test)))
    return tuple(splits)


def _event_quality_names(rows: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    names: set[str] = set()
    for row in rows:
        values = row.get("source_policy_event_quality_scalars", {})
        if not isinstance(values, dict):
            raise ValueError("Event-quality scalars must be a mapping")
        names.update(str(name) for name in values)
    return tuple(sorted(names))


def build_feature_frame(
    rows: Sequence[dict[str, Any]],
    *,
    event_quality_names: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    for row in rows:
        prohibited = set(row) & set(PROHIBITED_FEATURES)
        if prohibited:
            raise ValueError(f"Prohibited model features: {sorted(prohibited)}")
        missing = set(CATEGORICAL_FEATURES + BASE_NUMERIC_FEATURES) - set(row)
        if missing:
            raise ValueError(f"Missing frozen model features: {sorted(missing)}")
    quality_names = (
        tuple(event_quality_names)
        if event_quality_names is not None
        else _event_quality_names(rows)
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        record = {feature: row[feature] for feature in CATEGORICAL_FEATURES}
        record.update({feature: float(row[feature]) for feature in BASE_NUMERIC_FEATURES})
        quality = row.get("source_policy_event_quality_scalars", {})
        for name in quality_names:
            value = quality.get(name)
            record[f"event_quality__{name}"] = 0.0 if value is None else float(value)
            record[f"event_quality_missing__{name}"] = float(value is None)
        records.append(record)
    return pd.DataFrame.from_records(records), quality_names


def build_pipeline(
    *,
    inverse_regularization_c: float,
    l1_ratio: float,
    event_quality_names: Sequence[str],
) -> Pipeline:
    allowed = {
        (float(row["inverse_regularization_c"]), float(row["l1_ratio"]))
        for row in HYPERPARAMETERS
    }
    if (inverse_regularization_c, l1_ratio) not in allowed:
        raise ValueError("Hyperparameters are outside the frozen nine-combination search")
    numeric = list(BASE_NUMERIC_FEATURES)
    numeric.extend(f"event_quality__{name}" for name in event_quality_names)
    numeric.extend(f"event_quality_missing__{name}" for name in event_quality_names)
    preprocessor = ColumnTransformer(
        transformers=(
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                list(CATEGORICAL_FEATURES),
            ),
            ("numeric", StandardScaler(), numeric),
        )
    )
    classifier = LogisticRegression(
        penalty="elasticnet",
        solver="saga",
        C=inverse_regularization_c,
        l1_ratio=l1_ratio,
        random_state=SEED,
        max_iter=2_000,
        tol=1e-6,
    )
    return Pipeline((("preprocessor", preprocessor), ("classifier", classifier)))


def select_hyperparameters(
    signals: Sequence[LabeledSignal],
    train_indices: Sequence[int],
    *,
    purge_dependency: timedelta,
) -> HyperparameterSelection:
    rows = [signals[index].features for index in train_indices]
    _, quality_names = build_feature_frame(rows)
    splits = temporal_inner_splits(
        signals,
        train_indices,
        purge_dependency=purge_dependency,
    )
    if not splits:
        raise ValueError("Insufficient strictly prior observations for inner model selection")
    evaluations: list[tuple[float, int, dict[str, float], tuple[float, ...]]] = []
    labels = np.asarray([signal.label.value for signal in signals], dtype=object)
    splits = tuple(
        (inner_train, inner_test)
        for inner_train, inner_test in splits
        if len(np.unique(labels[list(inner_train)])) >= 2
    )
    if not splits:
        raise ValueError("Inner model selection requires at least two training classes")
    all_classes = sorted(action.value for action in PolarityAction)
    for order, params in enumerate(HYPERPARAMETERS):
        losses: list[float] = []
        for inner_train, inner_test in splits:
            train_frame, _ = build_feature_frame(
                [signals[index].features for index in inner_train],
                event_quality_names=quality_names,
            )
            test_frame, _ = build_feature_frame(
                [signals[index].features for index in inner_test],
                event_quality_names=quality_names,
            )
            pipeline = build_pipeline(
                inverse_regularization_c=float(params["inverse_regularization_c"]),
                l1_ratio=float(params["l1_ratio"]),
                event_quality_names=quality_names,
            )
            pipeline.fit(train_frame, labels[list(inner_train)])
            probabilities = pipeline.predict_proba(test_frame)
            classifier = pipeline.named_steps["classifier"]
            class_to_column = {name: idx for idx, name in enumerate(classifier.classes_)}
            aligned = np.zeros((len(inner_test), len(all_classes)), dtype=float)
            for class_index, class_name in enumerate(all_classes):
                column = class_to_column.get(class_name)
                if column is not None:
                    aligned[:, class_index] = probabilities[:, column]
            losses.append(float(log_loss(labels[list(inner_test)], aligned, labels=all_classes)))
        evaluations.append((float(np.mean(losses)), order, params, tuple(losses)))
    mean_loss, _order, selected, fold_losses = min(evaluations, key=lambda row: (row[0], row[1]))
    selected_c = float(selected["inverse_regularization_c"])
    selected_l1 = float(selected["l1_ratio"])
    payload: dict[str, Any] = {
        "inverse_regularization_c": selected_c,
        "l1_ratio": selected_l1,
        "mean_log_loss": mean_loss,
        "fold_log_losses": list(fold_losses),
    }
    return HyperparameterSelection(
        inverse_regularization_c=selected_c,
        l1_ratio=selected_l1,
        mean_log_loss=mean_loss,
        fold_log_losses=fold_losses,
        selection_hash=canonical_json_sha256(payload),
    )


def actions_from_probabilities(
    classes: Sequence[str],
    probabilities: np.ndarray,
) -> tuple[PolarityAction, ...]:
    columns = {name: index for index, name in enumerate(classes)}
    original = columns.get(PolarityAction.ORIGINAL.value)
    inverse = columns.get(PolarityAction.INVERSE.value)
    actions: list[PolarityAction] = []
    for row in probabilities:
        original_p = float(row[original]) if original is not None else 0.0
        inverse_p = float(row[inverse]) if inverse is not None else 0.0
        if original_p >= 0.55 and original_p >= inverse_p:
            actions.append(PolarityAction.ORIGINAL)
        elif inverse_p >= 0.55 and inverse_p > original_p:
            actions.append(PolarityAction.INVERSE)
        else:
            actions.append(PolarityAction.ABSTAIN)
    return tuple(actions)


def fitted_model_hash(pipeline: Pipeline, event_quality_names: Sequence[str]) -> str:
    classifier = pipeline.named_steps["classifier"]
    preprocessor = pipeline.named_steps["preprocessor"]
    payload = {
        "classes": classifier.classes_.tolist(),
        "coefficients": np.asarray(classifier.coef_, dtype=float).tolist(),
        "intercepts": np.asarray(classifier.intercept_, dtype=float).tolist(),
        "feature_names": preprocessor.get_feature_names_out().tolist(),
        "event_quality_names": list(event_quality_names),
        "seed": SEED,
    }
    return canonical_json_sha256(payload)


def nested_oof_predictions(
    signals: Sequence[LabeledSignal],
    *,
    purge_dependency: timedelta,
    event_quality_names: Sequence[str],
) -> tuple[tuple[OofPrediction, ...], tuple[HyperparameterSelection, ...]]:
    labels = np.asarray([signal.label.value for signal in signals], dtype=object)
    predictions: list[OofPrediction] = []
    selections: list[HyperparameterSelection] = []
    for fold in annual_purged_forward_folds(
        signals,
        purge_dependency=purge_dependency,
    ):
        selection = select_hyperparameters(
            signals,
            fold.train_indices,
            purge_dependency=purge_dependency,
        )
        selections.append(selection)
        train_frame, _ = build_feature_frame(
            [signals[index].features for index in fold.train_indices],
            event_quality_names=event_quality_names,
        )
        test_frame, _ = build_feature_frame(
            [signals[index].features for index in fold.test_indices],
            event_quality_names=event_quality_names,
        )
        pipeline = build_pipeline(
            inverse_regularization_c=selection.inverse_regularization_c,
            l1_ratio=selection.l1_ratio,
            event_quality_names=event_quality_names,
        )
        pipeline.fit(train_frame, labels[list(fold.train_indices)])
        probabilities = pipeline.predict_proba(test_frame)
        classifier = pipeline.named_steps["classifier"]
        classes = [str(value) for value in classifier.classes_]
        actions = actions_from_probabilities(classes, probabilities)
        columns = {name: index for index, name in enumerate(classes)}
        model_hash = fitted_model_hash(pipeline, event_quality_names)
        for row_index, signal_index in enumerate(fold.test_indices):
            predictions.append(
                OofPrediction(
                    signal_index=signal_index,
                    fold_id=fold.fold_id,
                    original_probability=float(
                        probabilities[row_index, columns[PolarityAction.ORIGINAL.value]]
                    )
                    if PolarityAction.ORIGINAL.value in columns
                    else 0.0,
                    inverse_probability=float(
                        probabilities[row_index, columns[PolarityAction.INVERSE.value]]
                    )
                    if PolarityAction.INVERSE.value in columns
                    else 0.0,
                    abstain_probability=float(
                        probabilities[row_index, columns[PolarityAction.ABSTAIN.value]]
                    )
                    if PolarityAction.ABSTAIN.value in columns
                    else 0.0,
                    action=actions[row_index],
                    model_hash=model_hash,
                    hyperparameter_selection_hash=selection.selection_hash,
                )
            )
    predictions.sort(key=lambda row: row.signal_index)
    return tuple(predictions), tuple(selections)


def select_final_development_model(
    signals: Sequence[LabeledSignal],
    *,
    purge_dependency: timedelta,
    event_quality_names: Sequence[str],
) -> tuple[Pipeline, HyperparameterSelection, str]:
    indices = tuple(range(len(signals)))
    selection = select_hyperparameters(
        signals,
        indices,
        purge_dependency=purge_dependency,
    )
    frame, _ = build_feature_frame(
        [signal.features for signal in signals],
        event_quality_names=event_quality_names,
    )
    pipeline = build_pipeline(
        inverse_regularization_c=selection.inverse_regularization_c,
        l1_ratio=selection.l1_ratio,
        event_quality_names=event_quality_names,
    )
    pipeline.fit(frame, np.asarray([signal.label.value for signal in signals], dtype=object))
    return pipeline, selection, fitted_model_hash(pipeline, event_quality_names)
